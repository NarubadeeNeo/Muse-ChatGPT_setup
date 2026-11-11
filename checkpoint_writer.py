#!/usr/bin/env python3
"""Mac single-writer observation ledger. No Daily Log/Memory updates and no finalize authority."""
from deployment_config import value as deployment_value
import argparse
import copy
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sys
import uuid
import check_muse as check
import uploader as u

NAME='sync_checkpoints.json'
BACKUPS = deployment_value('backup_folder_id')
def encode(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()

class DriveLedger:
    def __init__(self,config,folder=check.SYSTEM,backups=BACKUPS):
        self.drive=u.Drive(config);self.reader=check.ReadOnlyDrive(config)
        self.folder=folder;self.backups=backups
    def files(self):return self.reader.listing(self.folder)
    def read(self,fid):return self.reader.read(fid)
    def new_id(self):return self.drive.new_id()
    def create(self,fid,name,data,backup=False):
        self.reader.listing(self.backups if backup else self.folder)
        self.drive.folder_id=self.backups if backup else self.folder
        self.drive.create(fid,name,data)
    def update(self,fid,data):
        info=self.reader.info(fid)
        if self.folder not in info.get('parents',[]) or info.get('name')!=NAME or info.get('trashed'):
            raise u.Error('ledger identity/parent changed')
        self.drive.api('PATCH','files/'+fid,{'uploadType':'media','supportsAllDrives':'true','fields':'id'},data,'application/json',upload=True)

class Writer:
    def __init__(self,backend,state_dir):
        self.backend=backend;self.root=Path(state_dir);self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path=self.root/'writer.json'
    def save(self):u.save_state(self.path,self.state)
    def load(self):
        found=[f for f in self.backend.files() if f['name']==NAME]
        if len(found)>1:raise u.Error('duplicate checkpoint ledgers; stop for reconciliation')
        if self.path.exists():
            self.state=json.loads(u.read_limited(self.path))
            if self.state['folder']!=self.backend.folder:raise u.Error('writer journal belongs to another folder')
            if found and found[0]['id']!=self.state['remote_id']:raise u.Error('ledger ID differs from writer journal')
        else:
            if found:raise u.Error('existing ledger has no local ownership journal; refusing to adopt/overwrite')
            self.state={'folder':self.backend.folder,'owner_id':'mac-'+uuid.uuid4().hex,
                        'remote_id':self.backend.new_id(),'last_verified_sha256':None,'pending':None}
            self.save()
        self.recover()
        raw=self.backend.read(self.state['remote_id'])
        if raw is None:
            if self.state['last_verified_sha256']:raise u.Error('verified ledger disappeared; do not recreate silently')
            return {'schema_version':1,'writer':'mac-python','owner_id':self.state['owner_id'],
                    'semantics':'observed_file_evidence_not_execution_or_finalize_authorization',
                    'retention_days':90,'checkpoints':[],'observations':[]}
        if u.sha(raw)!=self.state['last_verified_sha256']:raise u.Error('ledger changed outside Mac writer; reconciliation required')
        doc=json.loads(raw)
        if doc.get('owner_id')!=self.state['owner_id'] or doc.get('schema_version')!=1:raise u.Error('ledger ownership/schema changed')
        return doc
    def recover(self):
        pending=self.state.get('pending')
        if not pending:return
        data=u.read_limited(self.root/pending['payload'])
        if u.sha(data)!=pending['new_sha256']:raise u.Error('pending payload changed')
        old=self.backend.read(self.state['remote_id'])
        digest=u.sha(old) if old is not None else None
        if digest==pending['new_sha256']:pass # Lost response or crash after write: never append twice.
        elif digest==pending['base_sha256']:
            if old is None:self.backend.create(self.state['remote_id'],NAME,data)
            else:
                backup=self.backend.read(pending['backup_id'])
                if backup is None:self.backend.create(pending['backup_id'],pending['backup_name'],old,backup=True)
                backup=self.backend.read(pending['backup_id'])
                if backup is None or u.sha(backup)!=digest:raise u.Error('backup read-back failed; ledger untouched')
                # This is a last check, not CAS. The single-writer agreement and local lock are essential.
                current=self.backend.read(self.state['remote_id'])
                if current is None or u.sha(current)!=digest:raise u.Error('ledger changed before write; stop')
                self.backend.update(self.state['remote_id'],data)
        else:raise u.Error('pending ledger disagrees with remote bytes; stop')
        verified=self.backend.read(self.state['remote_id'])
        if verified is None or u.sha(verified)!=pending['new_sha256']:raise u.Error('ledger read-back failed; retry with same journal')
        self.state.update(last_verified_sha256=pending['new_sha256'],pending=None);self.save()
    def publish(self,doc):
        data=encode(doc);base=self.state['last_verified_sha256']
        payload='payload-'+u.sha(data)+'.json'
        path=self.root/payload
        if not path.exists():
            with open(path,'xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        pending={'payload':payload,'new_sha256':u.sha(data),'base_sha256':base}
        if base:
            pending.update(backup_id=self.backend.new_id(),backup_name='sync-checkpoints-before-'+base+'.json')
        self.state['pending']=pending;self.save() # Durable IDs and bytes BEFORE any mutation.
        self.recover()
        return self.state['remote_id']

def observation(doc,snapshot,event_date,now,ledger_id=None,phase='manual'):
    report=check.analyse(snapshot,event_date,now)
    # A checkpoint cannot prove itself. Exclude this ledger from input fingerprint/evidence.
    evidence=[e for e in snapshot.get('evidence_files',[]) if e['file_id']!=ledger_id]
    if not evidence:raise u.Error('source file versions/hashes required for checkpoint observations')
    fingerprint=u.sha(encode({'date':event_date,'phase':phase,'evidence':evidence}))
    if any(o['fingerprint']==fingerprint for o in doc['observations']):return doc,False,report
    if any((now.date()-dt.date.fromisoformat(o['event_date'])).days>=90 for o in doc['observations']):
        raise u.Error('90-day archive required before next append; no history deleted automatically')
    result=copy.deepcopy(doc)
    prior=doc['observations']+doc['checkpoints']
    seq=1+max([int(o['run_id'].rsplit('-',1)[1]) for o in prior if o['event_date']==event_date] or [0])
    rid='sync-'+event_date+'-'+now.strftime('%H%M')+'-'+str(seq).zfill(3)
    row={'run_id':rid,'event_date':event_date,'observed_at':now.isoformat(),'fingerprint':fingerprint,
         'phase':phase,'record_kind':'mac_observation','outcome':report['outcome'],
         'authorization_granted':False,'findings':report['findings'],'evidence_files':evidence}
    result['observations'].append(row)
    # Do not replace a disputed expected checkpoint with the newly observed bytes.
    preserve={'hash_mismatch','registered_handoff_missing','duplicate_handoff_id',
              'checkpoint_input_missing','checkpoint_log_disagreement','checkpoint_log_hash_disagreement',
              'unresolved_conflicts','healthy_but_log_draft','required_step_not_completed'}
    if any(f['code'] in preserve for f in report['findings']):
        row['reconciliation_required']=True
        result['last_observed_at']=now.isoformat()
        return result,True,report
    logs=[f for f in snapshot['logs'] if str(f['meta'].get('event_date'))==event_date]
    for f in snapshot['handoffs']:
        m=f['meta'];date=str(m.get('event_date',m.get('date','')))
        if date!=event_date:continue
        hid=m['handoff_id'];matched=any(e.get('handoff_id')==hid and e.get('sha256_muse_computed',e.get('sha256'))==f['sha256'] for e in snapshot['registry']['processed_handoffs'])
        blockers={e['code'] for e in report['findings']}
        log_ok=len(logs)==1 and not blockers.intersection({'daily_log_source_missing','daily_log_id_disagreement','daily_log_revision_invalid','daily_log_status_invalid'})
        steps={'input_validation':'completed' if f['schema_v2_valid'] else 'failed',
               'integrity':'completed' if matched else 'pending',
               'daily_log':'completed' if log_ok and hid in logs[0]['meta'].get('source_handoffs',[]) else 'pending',
               'content_review':'needs_review','project_tracker':'needs_review','shared_memory':'needs_review',
               'active_context':'pending','muse_handoff':'pending','finalization':'needs_review'}
        outputs={}
        if log_ok:
            meta=logs[0]['meta'];outputs['daily_log']={k:meta[k] for k in ('log_id','revision','source_handoffs') if k in meta}
            outputs['daily_log'].update(file_id=logs[0]['file_id'],sha256=logs[0]['sha256'],status=meta['status'])
        checkpoint_rid='sync-'+event_date+'-'+now.strftime('%H%M')+'-'+str(seq).zfill(3);seq+=1
        result['checkpoints'].append({'run_id':checkpoint_rid,'observation_id':rid,'handoff_id':hid,'event_date':event_date,
             'record_kind':'mac_observation','steps':steps,'outputs':outputs,'input_sha256':f['sha256'],
             'overall_status':'partial','last_attempt_at':now.isoformat(),'authorization_granted':False})
    result['last_observed_at']=now.isoformat()
    return result,True,report

def run(backend,state_dir,snapshot_provider,event_date,apply=False,phase='manual',now=None):
    now=now or dt.datetime.now(check.JST)
    root=Path(state_dir);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(root/'writer.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise u.Error('another Mac checkpoint writer is running') from None
        writer=Writer(backend,root)
        if not apply:
            found=[f for f in backend.files() if f['name']==NAME]
            raw=backend.read(found[0]['id']) if len(found)==1 else None
            if len(found)>1:raise u.Error('duplicate checkpoint ledgers')
            doc=json.loads(raw) if raw else {'observations':[],'checkpoints':[]}
            snapshot=snapshot_provider();_,changed,report=observation(doc,snapshot,event_date,now,found[0]['id'] if found else None,phase)
            return {'result':'would_append' if changed else 'duplicate_skipped','drive_writes':0,'report':report}
        doc=writer.load();snapshot=snapshot_provider()
        doc,changed,report=observation(doc,snapshot,event_date,now,writer.state['remote_id'],phase)
        if changed:writer.publish(doc)
        return {'result':'verified' if changed else 'duplicate_verified','file_id':writer.state['remote_id'],
                'sha256':writer.state['last_verified_sha256'],'observations':len(doc['observations']),
                'checkpoints':len(doc['checkpoints']),'authorization_granted':False,'report':report}

def phase_for_time(now):
    minutes=now.astimezone(check.JST).strftime('%H%M')
    return next((name for cutoff,name in [('2200','after_brief'),('2150','after_context'),('2140','after_finalize'),('2130','after_retry_2'),('2100','after_retry_1'),('2030','after_initial')] if minutes>=cutoff),'manual')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings',required=True)
    p.add_argument('--event-date',default=dt.datetime.now(check.JST).date().isoformat())
    p.add_argument('--phase',default='manual',choices=['auto','manual','after_initial','after_retry_1','after_retry_2','after_finalize','after_context','after_brief'])
    p.add_argument('--apply',action='store_true');p.add_argument('--report',required=True);a=p.parse_args()
    try:
        import scheduled_upload as send
        settings=json.loads(Path(a.settings).read_text());config=json.loads(Path(settings['uploader_config']).read_text())
        os.environ[config.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=send.token_without_login(settings['token_file'])
        phase=a.phase
        if phase=='auto':
            phase=phase_for_time(dt.datetime.now(check.JST))
        result=run(DriveLedger(config),settings['checkpoint_state'],lambda:check.collect(check.ReadOnlyDrive(config)),a.event_date,a.apply,phase)
    except Exception as e:
        result={'result':'technical_error','authorization_granted':False,'error':str(e) if isinstance(e,u.Error) else type(e).__name__}
    path=Path(a.report);path.parent.mkdir(parents=True,exist_ok=True);u.save_state(path,result)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result['result']=='technical_error' else 0

if __name__=='__main__':sys.exit(main())
