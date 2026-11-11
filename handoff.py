#!/usr/bin/env python3
"""Enable or manually send a real Handoff. Does not schedule or generate content."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import connect_drive as auth
import uploader as u

SCOPES = ['https://www.googleapis.com/auth/drive.file',
          'https://www.googleapis.com/auth/drive.readonly']

def check_inventory(backend, expected):
    backend.folder()
    files=backend.files()
    actual={f['id'] for f in files}
    if not expected or actual != set(expected):
        raise u.Error('folder inventory differs from independently observed baseline; review before enabling')
    # Also prove content visibility, not only metadata visibility.
    for f in files:
        if f.get('mimeType')=='application/vnd.google-apps.folder':
            raise u.Error('unexpected subfolder in flat Handoff inbox')
        if backend.read(f['id']) is None:
            raise u.Error('cannot read all existing inbox files')
    return files

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('file',nargs='?')
    p.add_argument('--credentials',required=True)
    p.add_argument('--token-file',required=True)
    p.add_argument('--config',required=True)
    p.add_argument('--enable',action='store_true',help='authorize and enable manual uploads; does not send a file')
    p.add_argument('--baseline',help='JSON list of file IDs independently read from the designated folder')
    p.add_argument('--apply',action='store_true',help='send the given real Handoff; default is dry-run')
    a=p.parse_args()
    try:
        if a.enable and (a.file or a.apply):
            raise u.Error('enable is a separate step and cannot upload a Handoff')
        if not a.enable and not a.file:
            raise u.Error('provide a real Handoff file or --enable')
        path=Path(a.config).resolve()
        c=json.loads(path.read_text())
        if c.get('handoff_folder_id')!=u.PRODUCTION:
            raise u.Error('real mode is restricted to the verified designated Handoff folder')
        # Validate local input before requesting authentication or reading Drive.
        data=meta=None
        if a.file:
            source=Path(a.file).resolve()
            if source.suffix.lower()!='.md' or 'examples' in source.parts:
                raise u.Error('provide a real .md Handoff, not a bundled example')
            data=u.read_limited(source)
            meta=u.validate(data)
            if b'LOCAL TEST FIXTURE' in data or b'CONNECTIVITY TEST ONLY' in data:
                raise u.Error('test fixtures are prohibited in real Handoff mode')
        if a.enable and (not a.baseline or c.get('exclusive_writer_confirmed') is not True):
            raise u.Error('enabling needs inventory baseline and the single-writer setting')
        creds=auth.authenticate(a.credentials,a.token_file,SCOPES)
        os.environ[c.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=creds.token
        backend=u.Drive(c)
        if a.enable:
            expected=json.loads(Path(a.baseline).read_text())
            files=check_inventory(backend,expected)
            c['allow_handoff_upload']=True
            c['full_folder_visibility_confirmed']=True
            c['visibility_verified_at']=dt.datetime.now(dt.timezone.utc).isoformat()
            auth.private_save(path,json.dumps(c,indent=2))
            u.log('manual_handoff_enabled',folder_id=backend.folder_id,existing_files_verified=len(files),
                  handoff_sent=False,scheduler_changed=False)
            return 0
        if a.apply and not all(c.get(k) is True for k in (
            'allow_handoff_upload','full_folder_visibility_confirmed','exclusive_writer_confirmed')):
            raise u.Error('manual uploads not enabled or single-writer setting absent')
        state=Path(c['state_dir'])
        if not state.is_absolute():state=path.parent/state
        u.transfer(backend,meta['handoff_id']+'.md',data,meta,state,a.apply,'drive:'+backend.folder_id)
        return 0
    except Exception as e:
        u.log('handoff_error',error=str(e) if isinstance(e,u.Error) else type(e).__name__)
        return 2

if __name__=='__main__':sys.exit(main())
