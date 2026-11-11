#!/usr/bin/env python3
"""Small, create-only Muse v2.2.1 uploader. Python 3.10+, PyYAML."""
from deployment_config import value as deployment_value
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import yaml

MAX_BYTES = 2 * 1024 * 1024
ID = re.compile(r'chatgpt-\d{4}-\d{2}-\d{2}-[A-Za-z0-9][A-Za-z0-9_-]{0,100}\Z')
PRODUCTION = deployment_value('handoff_folder_id')

class Error(Exception):
    pass

class UniqueLoader(yaml.SafeLoader):
    pass

def mapping(loader, node):
    out = {}
    for k, v in node.value:
        key = loader.construct_object(k, deep=True)
        if not isinstance(key, str) or key in out:
            raise Error('YAML keys must be unique strings')
        out[key] = loader.construct_object(v, deep=True)
    return out

UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)

def log(event, **fields):
    print(json.dumps({'time': dt.datetime.now(dt.timezone.utc).isoformat(),
                      'event': event, **fields}, ensure_ascii=False), flush=True)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def frontmatter(data):
    if len(data) > MAX_BYTES:
        raise Error('file exceeds 2 MiB limit')
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeError as e:
        raise Error('file must be UTF-8') from e
    # Parse a separate view; the original bytes alone are hashed and uploaded.
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise Error('missing YAML front matter')
    end = next((i for i in range(1, len(lines)) if lines[i] == '---'), None)
    if end is None:
        raise Error('unterminated YAML front matter')
    try:
        header = '\n'.join(lines[1:end])
        if any(isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
               for t in yaml.scan(header)):
            raise Error('YAML aliases/anchors are not supported')
        meta = yaml.load(header, Loader=UniqueLoader)
    except (yaml.YAMLError, ValueError, RecursionError) as e:
        raise Error('invalid YAML') from e
    if not isinstance(meta, dict):
        raise Error('front matter must be a mapping')
    return meta, '\n'.join(lines[end+1:])

def validate(data):
    m, body = frontmatter(data)
    required = {'schema_version', 'handoff_id', 'source', 'destination', 'event_date',
                'timezone', 'status', 'supersedes', 'conversation_coverage'}
    missing = sorted(required - m.keys())
    if missing:
        raise Error('missing fields: ' + ', '.join(missing))
    if type(m['schema_version']) is not int or m['schema_version'] != 2:
        raise Error('schema_version must be integer 2')
    if 'content_hash' in m:
        raise Error('content_hash is forbidden by v2.2.1')
    hid = m['handoff_id']
    if not isinstance(hid, str) or not ID.fullmatch(hid):
        raise Error('invalid handoff_id; expected chatgpt-YYYY-MM-DD-unique-suffix')
    date = str(m['event_date'])
    try:
        if dt.date.fromisoformat(date).isoformat() != date:
            raise ValueError()
    except ValueError as e:
        raise Error('event_date must be YYYY-MM-DD') from e
    if m['source'] != 'chatgpt' or m['destination'] != 'muse' or m['timezone'] != 'Asia/Tokyo':
        raise Error('expected chatgpt -> muse, Asia/Tokyo')
    if m['status'] not in ('complete', 'partial', 'correction'):
        raise Error('invalid status')
    old = m['supersedes']
    if m['status'] == 'correction':
        if not isinstance(old, str) or not ID.fullmatch(old) or old == hid:
            raise Error('correction needs a different valid supersedes ID')
    elif old is not None:
        raise Error('supersedes must be null except for correction')
    c = m['conversation_coverage']
    if not isinstance(c, dict) or not {'type','sources_reviewed','conversations_included','full_account_history'} <= c.keys():
        raise Error('incomplete conversation_coverage')
    if c['type'] not in ('full','partial','unknown'):
        raise Error('invalid coverage type')
    sources = c['sources_reviewed']
    if not isinstance(sources, list) or not all(isinstance(x,str) and x.strip() for x in sources):
        raise Error('sources_reviewed must list actual source references individually')
    n = c['conversations_included']
    if n != 'unknown' and (type(n) is not int or n < 0):
        raise Error('conversations_included must be unknown or a nonnegative integer')
    if type(c['full_account_history']) is not bool:
        raise Error('full_account_history must be boolean')
    # Conservative pilot rule: full coverage requires human review, beyond YAML checks.
    if c['type'] == 'full' or c['full_account_history']:
        raise Error('full coverage requires separate human evidence review; pilot rejects it')
    if 'session_summaries' in sources:
        raise Error('list individual session summary files, not only session_summaries')
    groups = [('Learning',), ('Projects','Project Progress'),
              ('Decisions','Confirmed Decisions'), ('Open Questions',),
              ('Next Actions','Suggested Next Actions')]
    headings = {x.strip().lower() for x in re.findall(r'^#{1,6}\s+(.+?)\s*$', body, re.M)}
    for group in groups:
        if not any(x.lower() in headings for x in group):
            raise Error('missing Markdown section: ' + group[0])
    return m

def read_limited(path):
    with open(path, 'rb') as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise Error('file exceeds 2 MiB limit')
    return data

class Local:
    def __init__(self, root):
        self.root = Path(root)
    def folder(self):
        return None
    def files(self):
        for p in self.root.glob('*.bin'):
            if not p.with_suffix('.json').exists():
                raise Error('incomplete local store entry; manual inspection required')
        return [json.loads(p.read_text()) for p in sorted(self.root.glob('*.json'))]
    def read(self, fid):
        p = self.root / (fid + '.bin')
        return read_limited(p) if p.exists() else None
    def new_id(self):
        return str(uuid.uuid4())
    def create(self, fid, name, data):
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / (fid + '.bin'), 'xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(self.root / (fid + '.json'), 'x') as f:
            json.dump({'id':fid,'name':name,'mimeType':'text/markdown'}, f)

class Drive:
    def __init__(self, config, connectivity=False):
        self.folder_id = config['connectivity_folder_id' if connectivity else 'handoff_folder_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,100}', self.folder_id or ''):
            raise Error('configure an exact Drive folder ID')
        if connectivity and self.folder_id == config['handoff_folder_id']:
            raise Error('connectivity test must use a separate unwatched folder')
        self.expected_name = config['connectivity_folder_name'] if connectivity else 'chatgpt_to_muse'
        self.token = os.environ.get(config.get('token_env', 'MUSE_DRIVE_ACCESS_TOKEN'))
        if not self.token:
            raise Error('missing OAuth access token environment variable (not the ChatGPT connector)')
    def api(self, method, path, query=None, data=None, content_type=None, upload=False):
        base = 'https://www.googleapis.com/' + ('upload/drive/v3/' if upload else 'drive/v3/')
        url = base + path + '?' + urllib.parse.urlencode(query or {})
        headers = {'Authorization':'Bearer ' + self.token}
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as r:
                raw = r.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise Error('Drive response exceeds limit')
                return raw
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == 'GET' and query and query.get('alt') == 'media':
                return None
            raise Error(f'Drive HTTP {e.code}; no automatic write retry; reconcile by rerunning') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise Error('Drive network failure; write outcome may be unknown; rerun for reconciliation') from None
    def folder(self):
        m = json.loads(self.api('GET', 'files/' + self.folder_id,
                               {'fields':'id,name,mimeType,trashed,capabilities(canAddChildren)', 'supportsAllDrives':'true'}))
        if m.get('name') != self.expected_name or m.get('mimeType') != 'application/vnd.google-apps.folder' or m.get('trashed') or not m.get('capabilities',{}).get('canAddChildren'):
            raise Error('folder identity/type/write permission check failed')
    def files(self):
        files, token = [], None
        while True:
            q = {'q':f"'{self.folder_id}' in parents and trashed = false", 'pageSize':1000,
                 'fields':'nextPageToken,incompleteSearch,files(id,name,mimeType)',
                 'supportsAllDrives':'true','includeItemsFromAllDrives':'true'}
            if token:
                q['pageToken'] = token
            page = json.loads(self.api('GET','files',q))
            if page.get('incompleteSearch'):
                raise Error('Drive search incomplete; cannot establish uniqueness')
            files.extend(page.get('files',[]))
            token = page.get('nextPageToken')
            if not token:
                return files
    def read(self, fid):
        return self.api('GET','files/'+fid, {'alt':'media','supportsAllDrives':'true'})
    def new_id(self):
        return json.loads(self.api('GET','files/generateIds',{'count':1,'space':'drive','type':'files'}))['ids'][0]
    def create(self, fid, name, data):
        boundary = 'muse_' + uuid.uuid4().hex
        meta = json.dumps({'id':fid,'name':name,'parents':[self.folder_id],
                           'mimeType':'application/json' if name.endswith('.json') else 'text/plain' if name.endswith('.txt') else 'text/markdown'}).encode()
        body = (f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n'.encode() + meta +
                f'\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data +
                f'\r\n--{boundary}--\r\n'.encode())
        self.api('POST','files',{'uploadType':'multipart','supportsAllDrives':'true','fields':'id'},
                 body,'multipart/related; boundary='+boundary, upload=True)
        # No update, delete, permission mutation or blind POST retry exists here.

def inspect(backend, name, data, meta):
    matches, seen, ids = [], {}, set()
    for f in backend.files():
        if f.get('mimeType') == 'application/vnd.google-apps.folder':
            continue
        raw = backend.read(f['id'])
        if raw is None:
            raise Error('listed file disappeared; rerun inspection')
        if meta is None:
            if f['name'] == name:
                matches.append((f['id'], raw))
            continue
        # Test probes have no handoff YAML and are never ingested as handoffs.
        probe_name = f['name'].startswith('CONNECTIVITY_TEST_NOT_A_HANDOFF_')
        if probe_name and not raw.startswith(b'---'):
            continue
        try:
            old, _ = frontmatter(raw)
            if probe_name and 'handoff_id' not in old:
                continue
            old_id = old.get('handoff_id')
            if not isinstance(old_id, str) or not ID.fullmatch(old_id):
                raise Error('missing/invalid handoff_id')
        except Error as e:
            raise Error('cannot establish uniqueness: existing file has invalid identity: ' + f['id']) from e
        if old_id in seen:
            raise Error('multiple remote files use the same handoff_id; manual review required')
        seen[old_id] = sha(raw)
        ids.add(old_id)
        if old_id == meta['handoff_id'] or f['name'] == name:
            if old_id != meta['handoff_id']:
                raise Error('filename collision with a different handoff_id')
            matches.append((f['id'], raw))
    if len(matches) > 1:
        raise Error('multiple matching files; manual review required')
    if matches:
        fid, raw = matches[0]
        if sha(raw) != sha(data):
            raise Error('ID/name collision with different SHA-256; rejected, source left untouched')
        return fid
    if meta and meta['status'] == 'correction' and meta['supersedes'] not in ids:
        raise Error('supersedes target not found in destination')
    return None

def save_state(path, value):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value,f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def transfer(backend, name, data, meta, state_dir, apply=False, namespace='local'):
    backend.folder()
    digest = sha(data)
    if not apply:
        existing = inspect(backend,name,data,meta)
        log('dry_run', sha256=digest, bytes=len(data), name=name,
            result='duplicate_verified' if existing else 'would_create', remote_id=existing)
        return
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    with open(root/'uploader.lock','a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error('another uploader is running with this state directory') from None
        key = sha((namespace+'\0'+name).encode())
        path = root / (key+'.json')
        state = json.loads(path.read_text()) if path.exists() else None
        if state and state['sha256'] != digest:
            raise Error('local journal identity reused with different bytes; rejected')
        existing = inspect(backend,name,data,meta)
        if existing:
            log('duplicate_verified', remote_id=existing, sha256=digest)
            return
        if state and state.get('status') == 'verified':
            raise Error('previously verified output is missing; refusing to silently recreate')
        if state is None:
            state = {'id':backend.new_id(),'name':name,'sha256':digest,'status':'prepared'}
            save_state(path,state)  # Persist identity BEFORE the only create request.
        recovered = backend.read(state['id'])
        if recovered is None:
            log('creating', remote_id=state['id'], name=name, sha256=digest)
            backend.create(state['id'],name,data)
        elif sha(recovered) != digest:
            raise Error('prepared Drive ID has different bytes; manual review required')
        result = backend.read(state['id'])
        if result is None or sha(result) != digest:
            raise Error('read-back SHA-256 mismatch/missing file; NOT verified; do not resend under a new ID')
        state['status'] = 'verified'
        save_state(path,state)
        log('verified', remote_id=state['id'], sha256=digest, bytes=len(data))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('file', nargs='?', help='existing UTF-8 Handoff Markdown; never rewritten')
    p.add_argument('--config', required=True)
    p.add_argument('--backend', choices=['local','drive'], default='local')
    p.add_argument('--apply', action='store_true', help='actually create; default is dry-run')
    p.add_argument('--connectivity-test', action='store_true', help='generate a non-handoff .txt probe')
    a = p.parse_args()
    try:
        config_path = Path(a.config).resolve()
        c = json.loads(config_path.read_text())
        def localpath(key):
            q = Path(c[key])
            return q if q.is_absolute() else config_path.parent/q
        if a.connectivity_test:
            if a.file:
                raise Error('connectivity-test accepts no Handoff file')
            probe = str(uuid.uuid4())
            name = 'CONNECTIVITY_TEST_NOT_A_HANDOFF_DO_NOT_PROCESS_'+probe+'.txt'
            data = ('CONNECTIVITY TEST ONLY — NOT A HANDOFF\nDO NOT PROCESS IN MUSE\nprobe_id: '+probe+'\n').encode()
            meta = None
        else:
            if not a.file:
                raise Error('provide an existing Handoff file')
            if Path(a.file).suffix.lower() != '.md':
                raise Error('Handoff input must have .md extension')
            data = read_limited(a.file)
            meta = validate(data)
            name = meta['handoff_id']+'.md'
            log('validated',handoff_id=meta['handoff_id'],sha256=sha(data))
        if a.backend == 'drive':
            if a.apply and not a.connectivity_test and c.get('allow_handoff_upload') is not True:
                raise Error('handoff upload disabled in pilot config; use local/dry-run or separate connectivity test')
            if a.apply and c.get('exclusive_writer_confirmed') is not True:
                raise Error('Drive has no atomic unique-name constraint: confirm single writer and full folder visibility first')
            if a.apply and not a.connectivity_test and c.get('full_folder_visibility_confirmed') is not True:
                raise Error('confirm OAuth identity can list/read ALL destination files before handoff upload')
            backend = Drive(c,a.connectivity_test)
            namespace = 'drive:'+backend.folder_id
        else:
            backend = Local(localpath('local_store'))
            namespace = 'local:'+str(backend.root.resolve())
        transfer(backend,name,data,meta,localpath('state_dir'),a.apply,namespace)
        return 0
    except (Error, OSError, ValueError, TypeError, KeyError, RecursionError) as e:
        # No token, file body, request headers, or HTTP response bodies in logs.
        log('error',error=str(e) if isinstance(e, Error) else type(e).__name__)
        return 2

if __name__ == '__main__':
    sys.exit(main())
