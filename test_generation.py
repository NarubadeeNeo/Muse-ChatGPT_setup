import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
try:
    import daily_pipeline as d
except ModuleNotFoundError:
    d=None

@unittest.skipIf(d is None,'optional OAuth dependencies not installed')
class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        text='The user practiced algebra.\n\nAssignment completion is not confirmed.'
        self.sources=[{'id':'source1','name':'2026-11-11-algebra.md','text':text,'sha256':d.u.sha(text.encode())}]
        self.summary={k:[] for k in d.SECTIONS}
        self.summary['learning']=[{'text':'ผู้ใช้ฝึกพีชคณิต','evidence':[{'source_id':'source1','quote':'The user practiced algebra.'}]}]
        self.settings={'generation_state':str(self.root/'state'),'outbox':str(self.root/'outbox'),'codex_cli':'unused','model_runtime':str(self.root/'runtime')}
    def generate(self,model=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return d.generate_date('2026-11-11',self.sources,self.settings,model or (lambda *args:copy.deepcopy(self.summary)))
    def test_render_matches_schema_and_lists_sources(self):
        data=d.render(self.summary,self.sources,'2026-11-11','chatgpt-2026-11-11-unit-test',None)
        m=d.u.validate(data)
        self.assertEqual(m['status'],'partial')
        self.assertFalse(m['conversation_coverage']['full_account_history'])
        self.assertIn('source1',m['conversation_coverage']['sources_reviewed'][0])
        self.assertNotIn('content_hash',m)
    def test_unverifiable_claims_rejected(self):
        for change in ['quote','source','empty','missing']:
            summary=copy.deepcopy(self.summary)
            e=summary['learning'][0]['evidence']
            if change=='quote':e[0]['quote']='Invented evidence'
            elif change=='source':e[0]['source_id']='unknown'
            elif change=='empty':e[0]['quote']=''
            else:e.clear()
            with self.subTest(change=change),self.assertRaises(d.u.Error):d.verify_summary(summary,self.sources)
    def test_generate_once_then_no_model_recall(self):
        p=self.generate();before=p.read_bytes()
        with patch.object(d,'ask_chatgpt',side_effect=AssertionError('must not call')):
            self.generate(lambda *args:(_ for _ in ()).throw(AssertionError('must not call')))
        self.assertEqual(p.read_bytes(),before)
        self.assertEqual(len(list(p.parent.glob('*.md'))),1)
    def test_inverted_paraphrase_never_published(self):
        self.summary['learning'][0]['text']='Assignment finished'
        self.summary['learning'][0]['evidence'][0]['quote']='Assignment completion is not confirmed.'
        p=self.generate()
        self.assertNotIn(b'Assignment finished',p.read_bytes())
        self.assertIn(b'Assignment completion is not confirmed.',p.read_bytes())
    def test_substring_omitting_negation_rejected(self):
        self.sources[0]['text']='The assignment is not finished.'
        self.summary['learning'][0]['evidence'][0]['quote']='finished.'
        with self.assertRaisesRegex(d.u.Error,'complete source paragraph'):self.generate()
    def test_crash_after_publish_recovers_without_model(self):
        real=d.u.save_state
        def crash(path,record):
            if record.get('status')=='generated':raise OSError('simulated crash')
            return real(path,record)
        with patch.object(d.u,'save_state',side_effect=crash),self.assertRaises(OSError):self.generate()
        p=self.generate(lambda *a:(_ for _ in ()).throw(AssertionError('model recalled')))
        self.assertEqual(len(list(p.parent.glob('*.md'))),1)
    def test_lost_manifest_never_creates_second_identity(self):
        p=self.generate()
        for record in (self.root/'state').glob('*.json'):record.unlink()
        with self.assertRaisesRegex(d.u.Error,'cannot be verified'):self.generate()
        self.assertEqual(len(list(p.parent.glob('*.md'))),1)
    def test_changed_source_creates_new_correction_id(self):
        first=self.generate();old=d.u.validate(first.read_bytes())
        self.sources[0]['text']+=' Another session was recorded.'
        self.sources[0]['sha256']=d.u.sha(self.sources[0]['text'].encode())
        second=self.generate();new=d.u.validate(second.read_bytes())
        self.assertNotEqual(first,second)
        self.assertEqual(new['status'],'correction')
        self.assertEqual(new['supersedes'],old['handoff_id'])
        self.assertEqual(len(list(first.parent.glob('*.md'))),2)
    def test_modified_generated_file_not_overwritten(self):
        p=self.generate();p.write_bytes(p.read_bytes()+b'changed')
        with self.assertRaisesRegex(d.u.Error,'missing or changed'):self.generate()
    def test_model_failure_leaves_no_published_file(self):
        with self.assertRaises(RuntimeError):self.generate(lambda *args:(_ for _ in ()).throw(RuntimeError('model error')))
        self.assertFalse((self.root/'outbox').exists())
        record=json.loads(next((self.root/'state').glob('*.json')).read_text())
        self.assertEqual(record['status'],'prepared')
        p=self.generate();self.assertEqual(d.u.validate(p.read_bytes())['handoff_id'],record['handoff_id'])
    def test_source_change_during_pending_generation_stops(self):
        with self.assertRaises(RuntimeError):self.generate(lambda *args:(_ for _ in ()).throw(RuntimeError()))
        self.sources[0]['sha256']='new'
        with self.assertRaisesRegex(d.u.Error,'unfinished'):self.generate()
    def backend(self,files,raw):
        class Backend:
            folder_id=d.SOURCE_FOLDER
            def api(self,*args):return b'{"name":"session_summaries","mimeType":"application/vnd.google-apps.folder"}'
            def files(self):return files
            def read(self,fid):return raw
        return Backend()
    def test_empty_collection(self):
        self.assertEqual(d.read_sources(self.backend([],b''),'2026-11-11'),{})
    def test_date_conflict_rejected(self):
        b=self.backend([{'id':'a','name':'2026-11-11-algebra.md'}],b'---\nevent_date: 2026-11-10\n---\nText')
        with self.assertRaisesRegex(d.u.Error,'date conflicts'):d.read_sources(b,'2026-11-11')
    def test_unsupported_or_undated_sources_fail_closed(self):
        for name in ['summary.md','2026-11-11-source.pdf']:
            with self.subTest(name=name),self.assertRaises(d.u.Error):d.read_sources(self.backend([{'id':'a','name':name}],b'text'),'2026-11-11')
    def test_future_source_skipped(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(d.read_sources(self.backend([{'id':'a','name':'2026-11-12-source.md'}],None),'2026-11-11'),{})
    def test_size_limit_never_silently_truncates(self):
        b=self.backend([{'id':'a','name':'2026-11-11-source.md'}],b'x'*128001)
        with self.assertRaisesRegex(d.u.Error,'no truncation'):d.read_sources(b,'2026-11-11')

if __name__=='__main__':unittest.main(verbosity=2)
