import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import uploader as u

FIXTURE = Path(__file__).parent/'examples/valid-test-handoff.md'

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.b = u.Local(self.root/'store')
        self.state = self.root/'state'
        self.data = FIXTURE.read_bytes()
        self.m = u.validate(self.data)
        self.name = self.m['handoff_id']+'.md'
    def send(self, data=None, backend=None, apply=True):
        data = self.data if data is None else data
        with contextlib.redirect_stdout(io.StringIO()) as out:
            u.transfer(backend or self.b,self.name,data,u.validate(data),self.state,apply)
        return out.getvalue()
    def changed(self, old, new):
        return self.data.replace(old.encode(),new.encode())
    def test_valid_schema(self):
        self.assertEqual(self.m['schema_version'],2)
    def test_legacy_copy_rejected_without_mutation(self):
        p = Path(__file__).parent/'examples/existing-handoff-text-copy.md'
        before = p.read_bytes()
        with self.assertRaisesRegex(u.Error,'event_date.*supersedes'):
            u.validate(before)
        self.assertEqual(before,p.read_bytes())
    def test_invalid_schemas(self):
        cases = [('schema_version: 2','schema_version: true'),
                 ('status: partial','status: done'),
                 ('supersedes: null','supersedes: null\ncontent_hash: abc'),
                 ('source: chatgpt','source: muse'),
                 ('event_date: 2026-11-11','event_date: 2026-02-30'),
                 ('conversations_included: unknown','conversations_included: true'),
                 ('full_account_history: false','full_account_history: "false"'),
                 ('type: partial','type: full'),
                 ('sources_reviewed: []','sources_reviewed: [session_summaries]'),
                 ('## Learning','## Other'),
                 ('handoff_id: chatgpt-','handoff_id: ../../chatgpt-')]
        for old,new in cases:
            with self.subTest(new=new),self.assertRaises(u.Error):
                u.validate(self.changed(old,new))
    def test_duplicate_yaml_and_unsafe_yaml(self):
        for data in [self.changed('source: chatgpt','source: chatgpt\nsource: muse'),
                     self.changed('source: chatgpt','source: !!python/object:danger {}'),
                     self.changed('source: chatgpt','source: &x chatgpt')]:
            with self.assertRaises(u.Error): u.validate(data)
    def test_bad_utf8_bom_and_missing_frontmatter(self):
        for data in [b'\xff',b'no yaml',b'---\na: 1',b'\xef\xbb\xbf'+self.data]:
            with self.assertRaises(u.Error): u.validate(data)
    def test_size_limit(self):
        with self.assertRaises(u.Error): u.validate(b'x'*(u.MAX_BYTES+1))
    def test_dry_run_no_writes(self):
        self.assertIn('would_create',self.send(apply=False))
        self.assertEqual(list(self.root.iterdir()),[])
    def test_create_readback_duplicate_no_overwrite(self):
        self.assertIn('verified',self.send())
        before = {p.name:p.read_bytes() for p in self.b.root.iterdir()}
        self.assertIn('duplicate_verified',self.send())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.b.root.iterdir()})
        self.assertEqual(self.b.read(self.b.files()[0]['id']), self.data)
    def test_modified_same_id_rejected(self):
        self.send()
        with self.assertRaisesRegex(u.Error,'different bytes'):
            self.send(self.data+b' ')
        self.assertEqual(self.b.read(self.b.files()[0]['id']), self.data)
    def test_remote_modified_same_id_rejected_without_journal(self):
        self.b.create('one',self.name,self.data+b' ')
        with self.assertRaisesRegex(u.Error,'different SHA-256'): self.send()
    def test_raw_line_endings_hash(self):
        crlf = self.data.replace(b'\n',b'\r\n')
        self.assertNotEqual(u.sha(crlf),u.sha(self.data))
        self.send(crlf)
        self.assertEqual(self.b.read(self.b.files()[0]['id']),crlf)
    def test_duplicate_id_under_other_filename(self):
        self.b.create('one','other.md',self.data)
        self.assertIn('duplicate_verified',self.send())
    def test_multiple_remote_ids_rejected(self):
        self.b.create('one',self.name,self.data)
        self.b.create('two','other.md',self.data)
        with self.assertRaisesRegex(u.Error,'multiple remote'): self.send()
    def test_unparseable_remote_blocks_new_upload(self):
        self.b.create('one','old.md',b'bad')
        with self.assertRaisesRegex(u.Error,'cannot establish uniqueness'): self.send()
    def test_correction_requires_new_id_and_existing_target(self):
        d = self.changed('status: partial','status: correction')
        with self.assertRaises(u.Error): u.validate(d)
        d = d.replace(b'supersedes: null',('supersedes: '+self.m['handoff_id']).encode())
        with self.assertRaises(u.Error): u.validate(d)
        d = d.replace(('handoff_id: '+self.m['handoff_id']).encode(),
                      ('handoff_id: '+self.m['handoff_id']+'-correction').encode())
        m = u.validate(d)
        with self.assertRaisesRegex(u.Error,'target not found'):
            u.transfer(self.b,m['handoff_id']+'.md',d,m,self.state,False)
        self.send()
        with contextlib.redirect_stdout(io.StringIO()):
            u.transfer(self.b,m['handoff_id']+'.md',d,m,self.state,True)
        self.assertEqual(len(self.b.files()),2)
    def test_readback_mismatch_not_verified(self):
        base = self.b
        class Corrupt:
            def __getattr__(self,k): return getattr(base,k)
            def read(self,fid):
                raw = base.read(fid)
                return raw+b'corruption' if raw else raw
        with self.assertRaisesRegex(u.Error,'mismatch'): self.send(backend=Corrupt())
        self.assertEqual(json.loads(next(self.state.glob('*.json')).read_text())['status'],'prepared')
    def test_unknown_create_outcome_reconciles_without_second_create(self):
        base=self.b
        class Crash:
            def __getattr__(self,k): return getattr(base,k)
            def create(self,*args):
                base.create(*args)
                raise u.Error('timeout after create')
        with self.assertRaises(u.Error): self.send(backend=Crash())
        self.assertIn('duplicate_verified',self.send())
        self.assertEqual(len(self.b.files()),1)
    def test_prepared_before_create_reuses_id(self):
        with patch.object(self.b,'create',side_effect=u.Error('network failure')):
            with self.assertRaises(u.Error): self.send()
        fid=json.loads(next(self.state.glob('*.json')).read_text())['id']
        self.send()
        self.assertEqual(self.b.files()[0]['id'],fid)
    def test_verified_deleted_output_not_recreated(self):
        self.send()
        for p in self.b.root.iterdir(): p.unlink()
        with self.assertRaisesRegex(u.Error,'missing'): self.send()
    def test_lock_prevents_parallel_writer(self):
        self.state.mkdir()
        with open(self.state/'uploader.lock','a') as lock:
            u.fcntl.flock(lock,u.fcntl.LOCK_EX)
            with self.assertRaisesRegex(u.Error,'another uploader'): self.send()
    def test_drive_guard_and_missing_token(self):
        c={'handoff_folder_id':u.PRODUCTION,'connectivity_folder_id':u.PRODUCTION,
           'connectivity_folder_name':'tests','token_env':'UNIT_TEST_MISSING_TOKEN'}
        with self.assertRaisesRegex(u.Error,'separate'): u.Drive(c,True)
        with self.assertRaisesRegex(u.Error,'missing OAuth'): u.Drive(c)
    def test_drive_pagination_and_incomplete_search(self):
        d=object.__new__(u.Drive);d.folder_id=u.PRODUCTION
        pages=[json.dumps({'nextPageToken':'second','files':[{'id':'a'}]}).encode(),
               json.dumps({'files':[{'id':'b'}]}).encode()]
        with patch.object(d,'api',side_effect=pages) as api:
            self.assertEqual(len(d.files()),2)
            self.assertEqual(api.call_args_list[1].args[2]['pageToken'],'second')
        with patch.object(d,'api',return_value=b'{"incompleteSearch":true}'):
            with self.assertRaises(u.Error):d.files()
    def test_drive_folder_identity_guard(self):
        d=object.__new__(u.Drive);d.folder_id=u.PRODUCTION;d.expected_name='chatgpt_to_muse'
        with patch.object(d,'api',return_value=b'{"name":"wrong"}'):
            with self.assertRaises(u.Error):d.folder()
    def test_drive_multipart_preserves_bytes_and_only_creates(self):
        d=object.__new__(u.Drive);d.folder_id=u.PRODUCTION
        data=b'raw\r\n\xe0\xb9\x84 \n'
        with patch.object(d,'api',return_value=b'{"id":"test"}') as api:
            d.create('test','test.md',data)
            args=api.call_args.args
            self.assertEqual(args[:2],('POST','files'))
            self.assertIn(data,args[3])
            self.assertIn(b'"id": "test"',args[3])
    def test_drive_errors_redact_token_and_body(self):
        d=object.__new__(u.Drive); d.token='SECRET_TOKEN'
        e=urllib.error.HTTPError('https://example.com',403,'secret body',{},None)
        with patch('urllib.request.urlopen',side_effect=e):
            with self.assertRaises(u.Error) as cm:d.api('GET','files')
        self.assertNotIn('SECRET',str(cm.exception));self.assertNotIn('secret body',str(cm.exception))

if __name__=='__main__':unittest.main(verbosity=2)
