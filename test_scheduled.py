import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import scheduled_upload as s
except ModuleNotFoundError:
    s=None

@unittest.skipIf(s is None,'optional OAuth dependencies not installed')
class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.outbox=self.root/'outbox';self.outbox.mkdir()
        self.data=(Path(__file__).parent/'examples/valid-test-handoff.md').read_bytes().replace(b'LOCAL TEST FIXTURE',b'SYNTHETIC UNIT TEST')
        self.config=self.root/'config.json'
        self.config.write_text(json.dumps({'handoff_folder_id':s.u.PRODUCTION,'allow_handoff_upload':True,'full_folder_visibility_confirmed':True,'exclusive_writer_confirmed':True,'state_dir':str(self.root/'state')}))
        self.settings={'outbox':str(self.outbox),'uploader_config':str(self.config),'token_file':'unused'}
        self.backend=s.u.Local(self.root/'remote')
        self.backend.folder_id=s.u.PRODUCTION
    def run_local(self,apply=True):
        with patch.object(s,'token_without_login',return_value='TEST_SECRET'),patch.object(s.u,'Drive',return_value=self.backend),patch.dict('os.environ',{},clear=False),contextlib.redirect_stdout(io.StringIO()) as out:
            s.run(self.settings,apply)
        return out.getvalue()
    def test_empty_queue_never_authenticates(self):
        with patch.object(s,'token_without_login') as auth,contextlib.redirect_stdout(io.StringIO()) as out:s.run(self.settings,True)
        auth.assert_not_called();self.assertIn('no_pending_files',out.getvalue())
    def test_invalid_input_prevents_all_uploads(self):
        (self.outbox/'a.md').write_bytes(self.data);(self.outbox/'z.md').write_bytes(b'invalid')
        with self.assertRaises(s.u.Error):self.run_local()
        self.assertFalse(self.backend.root.exists())
    def test_test_fixture_and_symlink_rejected(self):
        p=self.outbox/'a.md';p.write_bytes(self.data.replace(b'SYNTHETIC UNIT TEST',b'LOCAL TEST FIXTURE'))
        with self.assertRaises(s.u.Error):s.collect(self.outbox)
        p.unlink();p.symlink_to(Path(__file__).parent/'examples/valid-test-handoff.md')
        with self.assertRaises(s.u.Error):s.collect(self.outbox)
    def test_send_and_repeat_no_duplicates(self):
        (self.outbox/'a.md').write_bytes(self.data)
        self.assertIn('verified',self.run_local())
        self.assertIn('duplicate_verified',self.run_local())
        self.assertEqual(len(self.backend.files()),1)
    def test_duplicate_batch_id_rejected(self):
        (self.outbox/'a.md').write_bytes(self.data);(self.outbox/'b.md').write_bytes(self.data)
        with self.assertRaises(s.u.Error):s.collect(self.outbox)
    def test_correction_order_and_dryrun(self):
        original=s.u.validate(self.data)['handoff_id']
        correction=self.data.replace(('handoff_id: '+original).encode(),('handoff_id: '+original+'-correction').encode()).replace(b'status: partial',b'status: correction').replace(b'supersedes: null',('supersedes: '+original).encode())
        (self.outbox/'a-correction.md').write_bytes(correction);(self.outbox/'z-original.md').write_bytes(self.data)
        self.assertEqual(s.collect(self.outbox)[0][2]['handoff_id'],original)
        self.run_local(False);self.assertFalse(self.backend.root.exists())
        self.run_local(True);self.assertEqual(len(self.backend.files()),2)
    def test_collision_preflight_no_partial_upload(self):
        original=s.u.validate(self.data)['handoff_id']
        other=self.data.replace(original.encode(),(original+'-other').encode())
        self.backend.create('existing','other.md',other+b'changed')
        (self.outbox/'a.md').write_bytes(self.data);(self.outbox/'b.md').write_bytes(other)
        with self.assertRaises(s.u.Error):self.run_local(True)
        self.assertEqual(len(self.backend.files()),1)
    def test_refresh_missing_scope_requires_login(self):
        p=self.root/'token.json';p.write_text('{"scopes":[]}')
        with self.assertRaisesRegex(s.u.Error,'scope missing'):s.token_without_login(p)

if __name__=='__main__':unittest.main(verbosity=2)
