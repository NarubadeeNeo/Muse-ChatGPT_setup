import copy
import datetime as dt
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import prepare_install as prepare
import deployment_admin as admin
import manage_launchd as jobs

class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.values={key:'test-'+key+'-12345' for key in prepare.ID_KEYS}
        self.values.update(log_month='2026-11',generation_start_date='2026-11-11',codex_cli=sys.executable,
                           capture_allowlist={},legacy_exception_date=None,manual_finalize_date=None)
    def test_prepare_is_local_only_and_uploads_disabled(self):
        result=prepare.prepare(self.root,self.values)
        self.assertFalse(result['drive_upload_enabled']);self.assertFalse(result['launchd_loaded'])
        config=json.loads((self.root/'.private/config.json').read_text())
        self.assertFalse(config['allow_handoff_upload']);self.assertFalse(config['full_folder_visibility_confirmed'])
        self.assertEqual((self.root/'.private').stat().st_mode&0o777,0o700)
        for f in (self.root/'.runtime/launchd').glob('*.plist'):
            v=plistlib.loads(f.read_bytes());self.assertEqual(v['WorkingDirectory'],str(self.root))
            self.assertEqual(v['ProgramArguments'][0],str(self.root/'.venv/bin/python'))
            self.assertFalse(v['RunAtLoad'])
    def test_refuses_existing_installation(self):
        prepare.prepare(self.root,self.values);before=(self.root/'.private/config.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'Existing installation'):prepare.prepare(self.root,self.values)
        self.assertEqual(before,(self.root/'.private/config.json').read_bytes())
    def test_manual_mode_does_not_schedule_ai_runtime(self):
        self.values['codex_cli']=None;prepare.prepare(self.root,self.values)
        job=plistlib.loads((self.root/'.runtime/launchd/local.muse.handoff-uploader.plist').read_bytes())
        self.assertEqual(Path(job['ProgramArguments'][1]).name,'scheduled_upload.py')
        self.assertNotIn('daily_pipeline.py',' '.join(job['ProgramArguments']))
    def test_placeholders_rejected_without_writing(self):
        self.values['handoff_folder_id']='YOUR_HANDOFF_FOLDER_ID'
        with self.assertRaises(ValueError):prepare.prepare(self.root,self.values)
        self.assertFalse((self.root/'deployment.json').exists())
    def test_reused_roles_rejected(self):
        self.values['backup_folder_id']=self.values['system_folder_id']
        with self.assertRaisesRegex(ValueError,'Different Drive roles'):prepare.prepare(self.root,self.values)
    def test_month_mismatch_rejected(self):
        self.values['log_month']='2027-01'
        with self.assertRaisesRegex(ValueError,'log_month'):prepare.prepare(self.root,self.values)
    def test_bad_chat_allowlist_rejected(self):
        self.values['capture_allowlist']={'YOUR_CHAT_ID':'A'}
        with self.assertRaisesRegex(ValueError,'capture_allowlist'):prepare.prepare(self.root,self.values)
    def test_empty_destination_requires_human_review_and_explicit_empty(self):
        class Empty:
            def folder(self):pass
            def files(self):return []
        for reviewed,single,empty in [(False,True,True),(True,False,True),(True,True,False)]:
            with self.assertRaises(admin.u.Error):admin.enable_destination({},Empty(),[],reviewed,single,empty)
        result=admin.enable_destination({},Empty(),[],True,True,True)
        self.assertTrue(result['allow_handoff_upload'])
    def test_changed_inventory_rejected(self):
        class Different:
            def folder(self):pass
            def files(self):return [{'id':'new'}]
        with self.assertRaisesRegex(admin.u.Error,'differs'):admin.enable_destination({},Different(),['expected'],True,True)
    def test_uploader_schedule_cannot_be_installed_before_enabling(self):
        prepare.prepare(self.root,self.values);(self.root/'.venv/bin').mkdir(parents=True);(self.root/'.venv/bin/python').touch()
        with self.assertRaisesRegex(ValueError,'Review and enable'):jobs.prerequisites(self.root,'uploader')
    def test_observer_schedule_requires_verified_owned_journal(self):
        prepare.prepare(self.root,self.values);(self.root/'.venv/bin').mkdir(parents=True);(self.root/'.venv/bin/python').touch()
        with self.assertRaises(FileNotFoundError):jobs.prerequisites(self.root,'checkpoint')
    def test_foreign_launchd_job_is_not_overwritten_or_unloaded(self):
        prepare.prepare(self.root,self.values)
        home=self.root/'fake-home';dest=home/'Library/LaunchAgents/local.muse.handoff-uploader.plist'
        dest.parent.mkdir(parents=True);dest.write_bytes(b'foreign installation')
        with patch.object(jobs,'__file__',str(self.root/'manage_launchd.py')),patch.object(jobs.Path,'home',return_value=home),\
             patch.object(jobs.sys,'platform','darwin'),patch.object(jobs.sys,'argv',['manage_launchd.py','install','--job','uploader']),\
             patch.object(jobs.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='foreign job')) as run:
            self.assertEqual(jobs.main(),2)
        self.assertEqual(dest.read_bytes(),b'foreign installation');self.assertEqual(run.call_count,1)
    def test_uninstall_preserves_private_config_and_journals(self):
        prepare.prepare(self.root,self.values)
        home=self.root/'fake-home';dest=home/'Library/LaunchAgents/local.muse.handoff-uploader.plist';dest.parent.mkdir(parents=True)
        dest.write_bytes((self.root/'.runtime/launchd/local.muse.handoff-uploader.plist').read_bytes())
        before=(self.root/'.private/config.json').read_bytes()
        with patch.object(jobs,'__file__',str(self.root/'manage_launchd.py')),patch.object(jobs.Path,'home',return_value=home),\
             patch.object(jobs.sys,'platform','darwin'),patch.object(jobs.sys,'argv',['manage_launchd.py','uninstall','--job','uploader']),\
             patch.object(jobs.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='own job')):
            self.assertEqual(jobs.main(),0)
        self.assertFalse(dest.exists());self.assertEqual((self.root/'.private/config.json').read_bytes(),before)

if __name__=='__main__':unittest.main(verbosity=2)
