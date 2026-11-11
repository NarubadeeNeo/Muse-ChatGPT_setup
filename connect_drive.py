#!/usr/bin/env python3
"""Desktop OAuth + isolated Drive connectivity test. Never uploads handoffs."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import uploader as u

SCOPES = ['https://www.googleapis.com/auth/drive.file']

def private_save(path, data):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent,prefix='.oauth-')
    try:
        with os.fdopen(fd,'w') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
        os.chmod(path,0o600)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def authenticate(credentials, token_file, scopes=None):
    scopes = SCOPES if scopes is None else scopes
    client=json.loads(Path(credentials).read_text())
    c=client.get('installed')
    if not isinstance(c,dict) or c.get('auth_uri')!='https://accounts.google.com/o/oauth2/auth' or c.get('token_uri')!='https://oauth2.googleapis.com/token':
        raise u.Error('expected Google Desktop OAuth credentials')
    token_file=Path(token_file)
    creds=None
    if token_file.exists():
        saved=json.loads(token_file.read_text())
        creds=Credentials.from_authorized_user_file(str(token_file),scopes)
        if creds.client_id!=c['client_id'] or creds.token_uri!='https://oauth2.googleapis.com/token':
            raise u.Error('cached token belongs to another client/endpoint')
        if not set(scopes) <= set(saved.get('scopes', [])):
            creds=None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow=InstalledAppFlow.from_client_config(client,scopes,autogenerate_code_verifier=True)
            creds=flow.run_local_server(host='localhost',bind_addr='127.0.0.1',port=0,
                open_browser=True,timeout_seconds=600,
                authorization_prompt_message='Google sign-in opened in your browser. Waiting for your consent.',
                success_message='Google Drive authorization completed. You may close this tab.',
                access_type='offline',prompt='consent')
        private_save(token_file,creds.to_json())
    u.log('oauth_ready',scopes=scopes,token_saved=True)
    return creds

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--credentials',required=True)
    p.add_argument('--token-file',required=True)
    p.add_argument('--config',required=True)
    p.add_argument('--test',action='store_true',help='create isolated test folder, upload non-handoff probe, read back')
    a=p.parse_args()
    try:
        creds=authenticate(a.credentials,a.token_file)
        if not a.test:return 0
        path=Path(a.config).resolve()
        if path.exists():
            c=json.loads(path.read_text())
        else:
            c=json.loads((Path(__file__).parent/'config.example.json').read_text())
        # Never enable production Handoff uploads or claim visibility of existing files.
        c['allow_handoff_upload']=False
        c['full_folder_visibility_confirmed']=False
        c['exclusive_writer_confirmed']=True
        os.environ[c.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=creds.token
        if not c.get('connectivity_folder_id'):
            api=object.__new__(u.Drive)
            api.token=creds.token
            name='muse-uploader-connectivity-tests-'+uuid.uuid4().hex[:12]
            m=json.loads(api.api('POST','files',{'fields':'id,name,webViewLink'},
                json.dumps({'name':name,'mimeType':'application/vnd.google-apps.folder'}).encode(),
                'application/json'))
            c['connectivity_folder_id']=m['id']
            c['connectivity_folder_name']=name
            private_save(path,json.dumps(c,indent=2))
            u.log('isolated_test_folder_created',folder_id=m['id'],name=m['name'],url=m.get('webViewLink'))
        backend=u.Drive(c,True)
        probe=str(uuid.uuid4())
        name='CONNECTIVITY_TEST_NOT_A_HANDOFF_DO_NOT_PROCESS_'+probe+'.txt'
        data=('CONNECTIVITY TEST ONLY — NOT A HANDOFF\nDO NOT PROCESS IN MUSE\nTransport: Python uploader with Google OAuth\nprobe_id: '+probe+'\n').encode()
        state=Path(c['state_dir'])
        if not state.is_absolute():state=path.parent/state
        u.transfer(backend,name,data,None,state,True,'drive:'+backend.folder_id)
        return 0
    except Exception as e:
        # Exceptions from OAuth libraries can contain credentials: log type only.
        u.log('oauth_or_test_error',error=str(e) if isinstance(e,u.Error) else type(e).__name__)
        return 2

if __name__=='__main__':sys.exit(main())
