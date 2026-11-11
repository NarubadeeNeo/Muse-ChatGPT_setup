#!/usr/bin/env python3
"""Manage only the two generated Muse launchd jobs. Never replace another installation."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

LABELS={'uploader':'local.muse.handoff-uploader','checkpoint':'local.muse.checkpoint-observer'}
def prerequisites(root,job):
    root=Path(root);settings=json.loads((root/'.private/schedule-settings.json').read_text())
    if not (root/'.venv/bin/python').exists():raise ValueError('Create .venv first')
    if job=='uploader':
        c=json.loads(Path(settings['uploader_config']).read_text())
        if not all(c.get(k) is True for k in ('allow_handoff_upload','exclusive_writer_confirmed','full_folder_visibility_confirmed')):
            raise ValueError('Review and enable the destination before installing live uploader')
    else:
        state=json.loads((Path(settings['checkpoint_state'])/'writer.json').read_text())
        if state.get('pending') or state.get('remote_id')!=settings.get('checkpoint_file_id') or not state.get('last_verified_sha256'):
            raise ValueError('Verified ledger bootstrap and ownership journal required')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['install','status','run','uninstall'])
    p.add_argument('--job',required=True,choices=list(LABELS));a=p.parse_args()
    try:
        if sys.platform!='darwin':raise ValueError('launchd installer requires macOS')
        root=Path(__file__).resolve().parent;label=LABELS[a.job];domain='gui/'+str(os.getuid());target=domain+'/'+label
        src=root/'.runtime/launchd'/(label+'.plist');dest=Path.home()/'Library/LaunchAgents'/(label+'.plist')
        loaded=subprocess.run(['launchctl','print',target],capture_output=True,text=True)
        if a.command=='status':print(loaded.stdout if loaded.returncode==0 else 'Not loaded');return 0
        expected=src.read_bytes()
        if plistlib.loads(expected).get('Label')!=label:raise ValueError('Generated plist label differs')
        if dest.exists() and dest.read_bytes()!=expected:raise ValueError('Another installation owns this label; do not overwrite')
        if a.command in ('install','run'):
            prerequisites(root,a.job)
            if dt.datetime.now().astimezone().utcoffset()!=dt.timedelta(hours=9):raise ValueError('Set/verify the Mac timezone to JST for these schedules')
        if a.command=='install':
            if loaded.returncode==0:
                if not dest.exists():raise ValueError('Loaded job cannot be attributed to this installation')
                print('Already installed; not changed');return 0
            dest.parent.mkdir(parents=True,exist_ok=True)
            with open(dest,'wb') as f:f.write(expected)
            dest.chmod(0o600)
            subprocess.run(['launchctl','bootstrap',domain,str(dest)],check=True)
            print('Installed. It will run at the generated calendar times; not started now.');return 0
        if not dest.exists():raise ValueError('This installation does not own the installed job')
        if a.command=='run':
            if loaded.returncode!=0:raise ValueError('Install job before running it')
            subprocess.run(['launchctl','kickstart',target],check=True);print('Started; verify logs and last exit status.');return 0
        if loaded.returncode==0:subprocess.run(['launchctl','bootout',target],check=True)
        dest.unlink();print('Uninstalled generated schedule; private journals and Drive files preserved.');return 0
    except Exception as e:
        print(str(e) if isinstance(e,ValueError) else type(e).__name__);return 2
if __name__=='__main__':raise SystemExit(main())
