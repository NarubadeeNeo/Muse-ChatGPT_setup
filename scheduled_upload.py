#!/usr/bin/env python3
"""Scan an explicit local outbox and upload existing Handoffs, without login UI."""
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import connect_drive as auth
import handoff
import uploader as u

class Tee:
    def __init__(self,*streams):self.streams=streams
    def write(self,text):
        for s in self.streams:s.write(text);s.flush()
        return len(text)
    def flush(self):
        for s in self.streams:s.flush()

def collect(folder):
    root=Path(folder).resolve(strict=True)
    jobs={}
    for p in sorted(root.glob('*.md')):
        if p.is_symlink() or not p.is_file():
            raise u.Error('outbox accepts regular .md files only')
        data=u.read_limited(p)
        meta=u.validate(data)
        if b'LOCAL TEST FIXTURE' in data or b'CONNECTIVITY TEST ONLY' in data:
            raise u.Error('test fixtures are prohibited in scheduled real uploads')
        hid=meta['handoff_id']
        if hid in jobs:raise u.Error('duplicate handoff_id inside outbox')
        jobs[hid]=(p,data,meta)
    ordered=[]
    active=set()
    done=set()
    def visit(hid):
        if hid in done:return
        if hid in active:raise u.Error('correction dependency cycle in outbox')
        active.add(hid)
        parent=jobs[hid][2].get('supersedes')
        if parent in jobs:visit(parent)
        active.remove(hid);done.add(hid);ordered.append(jobs[hid])
    for hid in jobs:visit(hid)
    return ordered

def token_without_login(path):
    saved=json.loads(Path(path).read_text())
    if not set(handoff.SCOPES)<=set(saved.get('scopes',[])):
        raise u.Error('OAuth scope missing; interactive login required outside scheduled run')
    if saved.get('token_uri')!='https://oauth2.googleapis.com/token':
        raise u.Error('unexpected OAuth token endpoint')
    creds=Credentials.from_authorized_user_file(str(path),handoff.SCOPES)
    if not creds.valid:
        if not creds.refresh_token:
            raise u.Error('interactive login required outside scheduled run')
        creds.refresh(Request())
        auth.private_save(Path(path),creds.to_json())
    return creds.token

def run(settings,apply=False):
    jobs=collect(settings['outbox'])
    if not jobs:
        u.log('no_pending_files',count=0)
        return
    config_path=Path(settings['uploader_config']).resolve()
    c=json.loads(config_path.read_text())
    if c.get('handoff_folder_id')!=u.PRODUCTION:
        raise u.Error('destination is not the designated Handoff folder')
    if not all(c.get(k) is True for k in ('allow_handoff_upload','full_folder_visibility_confirmed','exclusive_writer_confirmed')):
        raise u.Error('real uploads disabled or single-writer setting absent')
    token=token_without_login(settings['token_file'])
    os.environ[c.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=token
    backend=u.Drive(c)
    state=Path(c['state_dir'])
    if not state.is_absolute():state=config_path.parent/state
    # Preflight every file before creating any file in this batch.
    backend.folder()
    batch_ids={m['handoff_id'] for _,_,m in jobs}
    for _,data,meta in jobs:
        check_meta=meta
        if meta.get('supersedes') in batch_ids:
            # Its dependency is validated and ordered locally; still check ID/hash/name collisions now.
            check_meta={**meta,'status':'partial','supersedes':None}
        u.inspect(backend,meta['handoff_id']+'.md',data,check_meta)
    for p,data,meta in jobs:
        if u.read_limited(p)!=data:
            raise u.Error('outbox file changed during run; stopping before upload')
        check_meta=meta
        if not apply and meta.get('supersedes') in batch_ids:
            check_meta={**meta,'status':'partial','supersedes':None}
        u.transfer(backend,meta['handoff_id']+'.md',data,check_meta,state,apply,'drive:'+backend.folder_id)
    u.log('batch_completed',files=len(jobs),apply=apply)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--settings',required=True)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        settings=json.loads(Path(a.settings).read_text())
        logdir=Path(settings['log_dir']);logdir.mkdir(parents=True,exist_ok=True)
        logpath=logdir/(dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()+'.jsonl')
        fd=os.open(logpath,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(fd,'a') as logfile,contextlib.redirect_stdout(Tee(sys.stdout,logfile)):
            with open(logdir/'scheduled-run.lock','a') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise u.Error('scheduled batch already running') from None
                try:
                    u.log('scheduled_run_started',apply=a.apply)
                    run(settings,a.apply)
                    u.log('scheduled_run_finished',result='ok')
                    return 0
                except Exception as e:
                    u.log('scheduled_run_error',error=str(e) if isinstance(e,u.Error) else type(e).__name__)
                    return 2
    except Exception as e:
        u.log('scheduled_setup_error',error=str(e) if isinstance(e,u.Error) else type(e).__name__)
        return 2

if __name__=='__main__':sys.exit(main())
