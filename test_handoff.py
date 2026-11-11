import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
try:
    import handoff as h
except ModuleNotFoundError:
    h=None

@unittest.skipIf(h is None,'optional OAuth dependencies not installed')
class RealHandoffTests(unittest.TestCase):
    def test_inventory_must_exactly_match(self):
        b=SimpleNamespace(folder=lambda:None,files=lambda:[{'id':'a'}],read=lambda fid:b'ok')
        self.assertEqual(len(h.check_inventory(b,['a'])),1)
        for expected in [[],['b'],['a','b']]:
            with self.assertRaises(h.u.Error):h.check_inventory(b,expected)
    def test_inventory_requires_content_visibility(self):
        b=SimpleNamespace(folder=lambda:None,files=lambda:[{'id':'a'}],read=lambda fid:None)
        with self.assertRaises(h.u.Error):h.check_inventory(b,['a'])
    def test_enable_cannot_upload(self):
        with patch('sys.argv',['handoff.py','file.md','--credentials','unused','--token-file','unused','--config','unused','--enable']),patch.object(h.auth,'authenticate') as authenticate,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(h.main(),2)
            authenticate.assert_not_called()
    def test_example_rejected_before_auth(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config.json';p.write_text(json.dumps({'handoff_folder_id':h.u.PRODUCTION}))
            fixture=Path(__file__).parent/'examples/valid-test-handoff.md'
            with patch('sys.argv',['handoff.py',str(fixture),'--credentials','unused','--token-file','unused','--config',str(p)]),patch.object(h.auth,'authenticate') as authenticate,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h.main(),2)
                authenticate.assert_not_called()
    def test_enable_only_after_inventory_verified(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config.json';baseline=Path(t)/'baseline.json'
            baseline.write_text('["a"]')
            initial={'handoff_folder_id':h.u.PRODUCTION,'exclusive_writer_confirmed':True,'allow_handoff_upload':False,'full_folder_visibility_confirmed':False}
            p.write_text(json.dumps(initial))
            b=SimpleNamespace(folder_id=h.u.PRODUCTION,folder=lambda:None,files=lambda:[{'id':'a'}],read=lambda fid:b'bytes')
            args=['handoff.py','--enable','--credentials','unused','--token-file','unused','--config',str(p),'--baseline',str(baseline)]
            with patch('sys.argv',args),patch.object(h.auth,'authenticate',return_value=SimpleNamespace(token='TEST_SECRET')),patch.object(h.u,'Drive',return_value=b),patch.object(h.u,'transfer') as transfer,patch.dict('os.environ',{},clear=False),contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(h.main(),0)
                transfer.assert_not_called()
                self.assertNotIn('TEST_SECRET',output.getvalue())
            self.assertTrue(json.loads(p.read_text())['allow_handoff_upload'])
            p.write_text(json.dumps(initial));baseline.write_text('["different"]')
            with patch('sys.argv',args),patch.object(h.auth,'authenticate',return_value=SimpleNamespace(token='TEST_SECRET')),patch.object(h.u,'Drive',return_value=b),patch.dict('os.environ',{},clear=False),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(h.main(),2)
            self.assertEqual(json.loads(p.read_text()),initial)

if __name__=='__main__':unittest.main(verbosity=2)
