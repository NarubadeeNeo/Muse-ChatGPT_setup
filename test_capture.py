import copy
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
import capture_session as c

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.value={'thread':{'id':'academic-thread','kind':'chatgpt'},'turns':[
            {'id':'turn-a','startedAt':1794292965,'items':[
                {'id':'message-u','type':'userMessage','content':[{'type':'text','text':'I have not finished my report.'}]},
                {'id':'message-a','type':'agentMessage','text':'Suggested next action: check the result.'}]}]}
        self.selection=[{'message_id':'message-u','quote':'I have not finished my report.','section':'Progress'}]
        self.settings={'capture_allowlist':{'academic-thread':'Academic example'},'capture_state':str(self.root/'journal')}
    def render(self):return c.render(self.value,self.selection,self.settings['capture_allowlist'])
    def test_deterministic_bytes_and_event_date_from_source(self):
        name,data=self.render()[0]
        self.assertEqual(self.render(),self.render())
        self.assertTrue(name.startswith('2026-11-10-'))
        meta,_=c.u.frontmatter(data)
        self.assertFalse(meta['full_account_history']);self.assertFalse(meta['attachments_reviewed'])
        self.assertIn(b'[user;',data)
    def test_unknown_chat_rejected(self):
        self.settings['capture_allowlist']={}
        with self.assertRaises(c.u.Error):self.render()
    def test_invented_excerpt_rejected(self):
        self.selection[0]['quote']='I finished my report.'
        with self.assertRaisesRegex(c.u.Error,'not present'):self.render()
    def test_changed_source_changes_identity(self):
        first=self.render()
        self.value['turns'][0]['items'][0]['content'][0]['text']+=' More details.'
        self.assertNotEqual(first,self.render())
    def test_local_dry_run_create_readback_duplicate(self):
        backend=c.u.Local(self.root/'store')
        with contextlib.redirect_stdout(io.StringIO()) as log:
            c.publish(self.value,self.selection,self.settings,False,backend)
            self.assertEqual(backend.files(),[])
            c.publish(self.value,self.selection,self.settings,True,backend)
            c.publish(self.value,self.selection,self.settings,True,backend)
        self.assertIn('duplicate_verified',log.getvalue())
        self.assertEqual(len(backend.files()),1)
        name,data=self.render()[0]
        self.assertEqual(backend.read(backend.files()[0]['id']),data)
    def test_duplicate_excerpt_rejected(self):
        self.selection*=2
        with self.assertRaisesRegex(c.u.Error,'duplicate excerpt'):self.render()

if __name__=='__main__':unittest.main(verbosity=2)
