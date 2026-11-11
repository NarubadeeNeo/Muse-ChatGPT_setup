import contextlib
import io
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
try:
    import connect_drive as c
except ModuleNotFoundError:
    c = None

@unittest.skipIf(c is None, 'optional OAuth dependencies not installed')
class OAuthTests(unittest.TestCase):
    def test_private_file_permissions_and_replace(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'private/token.json'
            c.private_save(p,'test token')
            self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(p.parent.stat().st_mode),0o700)
            c.private_save(p,'replacement')
            self.assertEqual(p.read_text(),'replacement')
            self.assertEqual(list(p.parent.iterdir()),[p])
    def test_rejects_untrusted_auth_endpoint(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'client.json'
            p.write_text(json.dumps({'installed':{'auth_uri':'https://example.com','token_uri':'https://oauth2.googleapis.com/token'}}))
            with self.assertRaises(c.u.Error):c.authenticate(p,Path(t)/'token.json')
    def test_rejects_cached_token_other_client(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'client.json'; token=Path(t)/'token.json'
            p.write_text(json.dumps({'installed':{'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token','client_id':'expected'}}))
            token.write_text('{}')
            with patch.object(c.Credentials,'from_authorized_user_file',return_value=SimpleNamespace(client_id='other')):
                with self.assertRaises(c.u.Error):c.authenticate(p,token)
    def test_login_only_does_not_upload(self):
        with patch('sys.argv',['connect_drive.py','--credentials','unused','--config','unused','--token-file','unused']),patch.object(c,'authenticate',return_value=SimpleNamespace(token='TEST_SECRET')),patch.object(c.u,'transfer') as transfer:
            self.assertEqual(c.main(),0)
            transfer.assert_not_called()
    def test_oauth_exception_redacted(self):
        with patch('sys.argv',['connect_drive.py','--credentials','unused','--config','unused','--token-file','unused']),patch.object(c,'authenticate',side_effect=RuntimeError('TEST_SECRET')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(c.main(),2)
        self.assertNotIn('TEST_SECRET',output.getvalue())
        self.assertIn('RuntimeError',output.getvalue())

if __name__=='__main__':unittest.main(verbosity=2)
