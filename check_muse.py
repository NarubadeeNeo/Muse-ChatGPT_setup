#!/usr/bin/env python3
"""Mac-only P0: read Drive evidence and report blockers; never write Drive or authorize finalize."""
from deployment_config import value as deployment_value
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import uploader as u

JST=dt.timezone(dt.timedelta(hours=9))
SYSTEM = deployment_value('system_folder_id')
SYNC = deployment_value('sync_status_file_id')
REGISTRY = deployment_value('registry_file_id')
KNOWN_LOG = deployment_value('known_log_file_id')
LOG_MONTH = deployment_value('log_month')

class ReadOnlyDrive(u.Drive):
    def api(self,method,path,query=None,data=None,content_type=None,upload=False):
        if method!='GET' or data is not None or upload or path.endswith('generateIds'):
            raise u.Error('P0 forbids Drive mutation and ID allocation')
        return super().api(method,path,query,data,content_type,upload)
    def info(self,fid):
        return json.loads(self.api('GET','files/'+fid,{'fields':'id,name,mimeType,trashed,parents,version,modifiedTime','supportsAllDrives':'true'}))
    def create(self,*args):raise u.Error('P0 forbids Drive writes')
    def new_id(self):raise u.Error('P0 forbids Drive ID allocation')
    def listing(self,fid):
        info=self.info(fid)
        if info.get('trashed') or info.get('mimeType')!='application/vnd.google-apps.folder':raise u.Error('expected live folder')
        self.folder_id=fid
        return self.files()

def collect(backend):
    """Version-check every read file. No raw academic/personal body is saved in the report."""
    versions={};digests={}
    def read(fid,parent=None):
        info=backend.info(fid)
        if info.get('trashed') or (parent and parent not in info.get('parents',[])):raise u.Error('file identity/parent invalid')
        versions[fid]=info.get('version')
        if versions[fid] is None:raise u.Error('cannot establish file version')
        raw=backend.read(fid)
        if raw is None:raise u.Error('listed file disappeared')
        digests[fid]=u.sha(raw)
        return raw
    system=backend.listing(SYSTEM);inbox=backend.listing(u.PRODUCTION)
    snapshot={'sync_status':json.loads(read(SYNC,SYSTEM)),
              'registry':json.loads(read(REGISTRY,SYSTEM)),
              'system_files':[f['name'] for f in system],'handoffs':[],'logs':[],
              'checkpoints':None,'checked_at':dt.datetime.now(JST).isoformat()}
    ledger=[f for f in system if f['name']=='sync_checkpoints.json']
    if len(ledger)>1:raise u.Error('duplicate checkpoint ledgers')
    if ledger:snapshot['checkpoints']=json.loads(read(ledger[0]['id'],SYSTEM))
    for f in inbox:
        if f.get('mimeType')=='application/vnd.google-apps.folder':raise u.Error('unexpected subfolder in Handoff inbox')
        raw=read(f['id'],u.PRODUCTION)
        if f['name'].startswith('CONNECTIVITY_TEST_NOT_A_HANDOFF_') and b'handoff_id:' not in raw:continue
        meta,_=u.frontmatter(raw)
        try:u.validate(raw);schema_ok=True
        except u.Error:schema_ok=False
        snapshot['handoffs'].append({'file_id':f['id'],'name':f['name'],'sha256':u.sha(raw),'meta':meta,'schema_v2_valid':schema_ok})
    parents=backend.info(KNOWN_LOG).get('parents',[])
    if len(parents)!=1:raise u.Error('known Daily Log has ambiguous parent')
    log_folder=parents[0];log_files=backend.listing(log_folder)
    for f in log_files:
        # This pilot is explicitly bounded to the known November 2026 log folder.
        if not re.fullmatch(rf'{re.escape(LOG_MONTH)}-\d{{2}}\.md',f['name']):continue
        raw=read(f['id'],log_folder);meta,_=u.frontmatter(raw)
        snapshot['logs'].append({'file_id':f['id'],'name':f['name'],'sha256':u.sha(raw),'meta':meta})
    for fid,version in versions.items():
        if backend.info(fid).get('version')!=version:raise u.Error('file changed during audit; rerun read-only inspection')
    def identity(files):return sorted((f['id'],f['name'],f.get('mimeType')) for f in files)
    for fid,before in ((SYSTEM,system),(u.PRODUCTION,inbox),(log_folder,log_files)):
        if identity(backend.listing(fid))!=identity(before):raise u.Error('folder inventory changed during audit')
    snapshot['files_version_checked']=len(versions)
    snapshot['evidence_files']=[{'file_id':fid,'version':versions[fid],'sha256':digests[fid]} for fid in sorted(versions)]
    return snapshot

def analyse(snapshot,event_date,now=None):
    dt.date.fromisoformat(event_date);now=now or dt.datetime.now(JST)
    if not event_date.startswith(LOG_MONTH+'-'):raise u.Error('P0 is bounded to configured log_month; verify a new log folder before changing it')
    findings=[]
    def add(kind,code,**detail):findings.append({'kind':kind,'code':code,**detail})
    registry=snapshot['registry'].get('processed_handoffs')
    if not isinstance(registry,list):raise u.Error('unsupported processed_handoffs wrapper; do not guess schema')
    entries={}
    for entry in registry:
        hid=entry.get('handoff_id')
        if not isinstance(hid,str) or hid in entries:raise u.Error('invalid/duplicate registry identity')
        entries[hid]=entry
    handoffs={};current=[]
    for file in snapshot['handoffs']:
        meta=file['meta'];hid=meta.get('handoff_id')
        if not isinstance(hid,str) or not u.ID.fullmatch(hid):raise u.Error('invalid remote Handoff identity')
        if hid in handoffs:add('not_eligible','duplicate_handoff_id',handoff_id=hid)
        handoffs[hid]=file
        date=str(meta.get('event_date',meta.get('date',hid[8:18])))
        if date==event_date:
            current.append(hid)
            if not file['schema_v2_valid']:
                add('needs_review' if event_date==deployment_value('legacy_exception_date') else 'not_eligible','schema_v2_invalid',handoff_id=hid)
            if hid not in entries:add('input_missing','handoff_not_registered',handoff_id=hid)
    hashes_matched=0
    for hid,entry in entries.items():
        file=handoffs.get(hid)
        if file is None:add('not_eligible','registered_handoff_missing',handoff_id=hid);continue
        expected=entry.get('sha256_muse_computed',entry.get('sha256'))
        if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
            add('input_missing','registered_sha256_missing',handoff_id=hid)
        elif expected!=file['sha256']:add('not_eligible','hash_mismatch',handoff_id=hid)
        else:hashes_matched+=1
    if not current:add('input_missing','no_handoff_for_date')
    logs=[f for f in snapshot['logs'] if str(f['meta'].get('event_date'))==event_date]
    if len(logs)>1:add('not_eligible','duplicate_daily_log')
    log=logs[0]['meta'] if len(logs)==1 else None
    if log is None:add('input_missing','daily_log_missing')
    else:
        if log.get('status') not in ('draft','finalized','amended','incomplete'):add('not_eligible','daily_log_status_invalid')
        if type(log.get('revision')) is not int or log['revision']<1:add('not_eligible','daily_log_revision_invalid')
        if log.get('log_id')!='daily-'+event_date:add('not_eligible','daily_log_id_disagreement')
        sources=log.get('source_handoffs')
        if not isinstance(sources,list):add('input_missing','daily_log_sources_missing')
        else:
            for hid in sources:
                if hid not in handoffs:add('not_eligible','daily_log_source_missing',handoff_id=hid)
        if log.get('status')=='incomplete':add('not_eligible','daily_log_incomplete')
    sync=snapshot['sync_status']
    if str(sync.get('date'))!=event_date:add('input_missing','sync_status_is_for_other_date',observed_date=str(sync.get('date')))
    else:
        if type(sync.get('conflicts')) is not int:add('needs_review','conflict_count_unknown')
        elif sync['conflicts']!=0:add('not_eligible','unresolved_conflicts')
        if sync.get('sync_health')=='failed':add('not_eligible','sync_failed')
        if sync.get('sync_health')=='healthy' and log and log.get('status')=='draft':add('not_eligible','healthy_but_log_draft')
    ledger=snapshot.get('checkpoints')
    if ledger is None:add('input_missing','sync_checkpoints_missing')
    else:
        runs=ledger if isinstance(ledger,list) else ledger.get('checkpoints') if isinstance(ledger,dict) else None
        if not isinstance(runs,list):raise u.Error('unsupported checkpoint wrapper; manual schema mapping required')
        run_ids=set();relevant=[]
        for run in runs:
            if not isinstance(run,dict) or not all(k in run for k in ('run_id','handoff_id','event_date','steps','last_attempt_at')):raise u.Error('incomplete checkpoint record')
            if run['run_id'] in run_ids:raise u.Error('duplicate checkpoint run_id')
            run_ids.add(run['run_id'])
            if str(run['event_date'])==event_date:relevant.append(run)
        if not relevant:add('input_missing','checkpoint_for_date_missing')
        else:
            for run in relevant:
                if run['handoff_id'] not in handoffs:add('not_eligible','checkpoint_input_missing',run_id=run['run_id'])
            latest=max(relevant,key=lambda r:(dt.datetime.fromisoformat(r['last_attempt_at']),r['run_id']))
            if not isinstance(latest['steps'],dict):raise u.Error('checkpoint steps must be an object')
            for key in ('input_validation','daily_log'):
                if latest['steps'].get(key)!='completed':add('not_eligible','required_step_not_completed',step=key)
            expected=latest.get('outputs',{}).get('daily_log')
            if not expected:add('needs_review','checkpoint_has_no_output_identity')
            elif log is None or any(expected.get(k)!=log.get(k) for k in ('log_id','revision','source_handoffs')):
                add('not_eligible','checkpoint_log_disagreement')
            elif expected.get('sha256') and expected['sha256']!=logs[0]['sha256']:
                add('not_eligible','checkpoint_log_hash_disagreement')
            elif not expected.get('sha256'):add('needs_review','checkpoint_has_no_output_hash')
    if now.astimezone(JST)<dt.datetime.combine(dt.date.fromisoformat(event_date),dt.time(21,40),JST):
        add('not_eligible','before_finalization_deadline')
    for code in ('content_review','unverified_new_information','pending_user_decisions','required_output_scope'):
        add('needs_review',code)
    if event_date==deployment_value('manual_finalize_date'):add('needs_review','explicit_finalize_confirmation')
    outcome=next((kind for kind in ('technical_error','not_eligible','input_missing','needs_review') if any(f['kind']==kind for f in findings)),'needs_review')
    return {'pilot':'P0-read-only-on-Mac','event_date':event_date,'checked_at':now.isoformat(),
            'outcome':outcome,'authorization_granted':False,'drive_writes':0,
            'counts':{'handoffs_in_inbox':len(snapshot['handoffs']),'handoffs_for_date':len(current),'registry_entries':len(entries),'registered_hashes_matched':hashes_matched,'logs_for_date':len(logs)},
            'findings':findings,'limitations':['Configured monthly log folder only','Evidence is read over an interval, not an atomic multi-file snapshot','P0 does not authorize finalize, validate academic truth or replace Muse jobs']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings');p.add_argument('--snapshot',help='offline JSON fixture (no Drive access)')
    p.add_argument('--event-date',default=dt.datetime.now(JST).date().isoformat());p.add_argument('--report',required=True);a=p.parse_args()
    try:
        if bool(a.snapshot)==bool(a.settings):raise u.Error('choose --snapshot or --settings')
        if a.snapshot:snapshot=json.loads(u.read_limited(a.snapshot))
        else:
            import scheduled_upload as send
            settings=json.loads(Path(a.settings).read_text());config=json.loads(Path(settings['uploader_config']).read_text())
            os.environ[config.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=send.token_without_login(settings['token_file'])
            snapshot=collect(ReadOnlyDrive(config))
        report=analyse(snapshot,a.event_date)
    except Exception as e:
        report={'pilot':'P0-read-only-on-Mac','event_date':a.event_date,'outcome':'technical_error','authorization_granted':False,'drive_writes':0,
                'error':str(e) if isinstance(e,u.Error) else type(e).__name__}
    path=Path(a.report);path.parent.mkdir(parents=True,exist_ok=True)
    u.save_state(path,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 2 if report['outcome']=='technical_error' else 0

if __name__=='__main__':sys.exit(main())
