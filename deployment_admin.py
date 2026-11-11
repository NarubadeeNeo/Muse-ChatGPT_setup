#!/usr/bin/env python3
"""Explicit setup actions. Defaults never enable uploads or create a production ledger."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import uploader as u

def enable_destination(config,backend,expected,reviewed=False,single_writer=False,confirm_empty=False):
    if not reviewed or not single_writer:raise u.Error('Independently review Drive inventory and confirm one writer first')
    if not isinstance(expected,list) or any(not isinstance(x,str) for x in expected) or len(expected)!=len(set(expected)):
        raise u.Error('baseline must be a JSON list of distinct file IDs')
    if not expected and not confirm_empty:raise u.Error('Empty baseline needs --confirm-empty after verifying empty folder in Drive')
    backend.folder();files=backend.files()
    if {f['id'] for f in files}!=set(expected):raise u.Error('Drive inventory differs from reviewed baseline')
    for f in files:
        if f.get('mimeType')=='application/vnd.google-apps.folder' or backend.read(f['id']) is None:raise u.Error('Cannot read every inbox file')
    updated=dict(config);updated.update(allow_handoff_upload=True,full_folder_visibility_confirmed=True,exclusive_writer_confirmed=True,
                                       visibility_verified_at=dt.datetime.now(dt.timezone.utc).isoformat())
    return updated

def main():
    root=Path(__file__).resolve().parent
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['login','inventory','enable','doctor','checkpoint-test','checkpoint-bootstrap'])
    p.add_argument('--baseline');p.add_argument('--reviewed-in-drive',action='store_true');p.add_argument('--single-writer',action='store_true')
    p.add_argument('--confirm-empty',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:
        import scheduled_upload as send,connect_drive as auth,handoff
        if not (root/'deployment.json').exists():raise u.Error('Run prepare_install.py first')
        settings_path=root/'.private/schedule-settings.json';settings=json.loads(settings_path.read_text())
        config_path=Path(settings['uploader_config']);config=json.loads(config_path.read_text())
        if a.command=='login':
            auth.authenticate(root/'.private/credentials.json',settings['token_file'],handoff.SCOPES)
            print('Authorized using your own Google account. Uploads remain in their previous state.');return 0
        os.environ[config.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=send.token_without_login(settings['token_file'])
        backend=u.Drive(config)
        baseline=Path(a.baseline).resolve() if a.baseline else root/'.private/inbox-baseline.json'
        if a.command=='inventory':
            backend.folder();files=backend.files();rows=[]
            for f in files:
                raw=backend.read(f['id'])
                if raw is None:raise u.Error('Listed file disappeared')
                rows.append({'id':f['id'],'name':f['name'],'sha256':u.sha(raw)})
            if baseline.exists():raise u.Error('Baseline already exists; choose a new --baseline path for a new review')
            auth.private_save(baseline,json.dumps([f['id'] for f in files],indent=2))
            print(json.dumps({'review_in_drive_before_enabling':True,'files':rows,'baseline':str(baseline)},ensure_ascii=False,indent=2));return 0
        if a.command=='enable':
            updated=enable_destination(config,backend,json.loads(baseline.read_text()),a.reviewed_in_drive,a.single_writer,a.confirm_empty)
            auth.private_save(config_path,json.dumps(updated,indent=2));print('Destination enabled; no Handoff uploaded.');return 0
        import check_muse as check,checkpoint_writer as writer
        snapshot=check.collect(check.ReadOnlyDrive(config));date=dt.datetime.now(check.JST).date().isoformat()
        if a.command=='doctor':
            result=check.analyse(snapshot,date)
            u.save_state(root/'logs/doctor.json',result);print(json.dumps(result,ensure_ascii=False,indent=2));return 0
        if a.command=='checkpoint-test':
            test_folder=config.get('connectivity_folder_id')
            if not test_folder or test_folder in {check.SYSTEM,u.PRODUCTION,writer.BACKUPS}:raise u.Error('Use a separate connectivity test folder')
            rd=check.ReadOnlyDrive(config);info=rd.info(test_folder)
            if info.get('name')!=config['connectivity_folder_name'] or not info.get('name','').startswith('muse-uploader-connectivity-tests-'):
                raise u.Error('Test folder identity not verified')
            store=writer.DriveLedger(config,test_folder,test_folder);state=root/'.private/checkpoint-test-state'
            writer.run(store,state,lambda:snapshot,date,False)
            first=writer.run(store,state,lambda:snapshot,date,True)
            repeat=writer.run(store,state,lambda:snapshot,date,True)
            if repeat['result']!='duplicate_verified':raise u.Error('Duplicate test failed')
            second=writer.run(store,state,lambda:snapshot,date,True,phase='after_initial')
            if second['observations']<first['observations']:raise u.Error('History preservation test failed')
            result={'status':'passed','test_folder_id':test_folder,'ledger_id':second['file_id'],'duplicate':repeat['result'],
                    'production_modified':False,'sha256':second['sha256']}
            u.save_state(root/'logs/checkpoint-isolated-test.json',result);print(json.dumps(result,indent=2));return 0
        if not a.single_writer:raise u.Error('Confirm this Mac is the only ledger writer with --single-writer')
        test=json.loads((root/'logs/checkpoint-isolated-test.json').read_text())
        if test.get('status')!='passed':raise u.Error('Run isolated checkpoint test first')
        result=writer.run(writer.DriveLedger(config),settings['checkpoint_state'],lambda:snapshot,date,a.apply)
        if a.apply:
            settings['checkpoint_file_id']=result['file_id'];auth.private_save(settings_path,json.dumps(settings,ensure_ascii=False,indent=2))
        u.save_state(root/'logs/checkpoint-bootstrap.json',result);print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as e:
        print(str(e) if isinstance(e,u.Error) else type(e).__name__);return 2
if __name__=='__main__':raise SystemExit(main())
