import copy
import datetime as dt
import os
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import check_muse as c

class CheckerTests(unittest.TestCase):
    def setUp(self):
        month_patch=patch.object(c,"LOG_MONTH","2026-11");month_patch.start();self.addCleanup(month_patch.stop)
        self.date='2026-11-11';self.hid='chatgpt-2026-11-11-test-one'
        self.now=dt.datetime(2026,11,11,21,41,tzinfo=c.JST)
        meta={'event_date':self.date,'handoff_id':self.hid}
        log={'event_date':self.date,'log_id':'daily-'+self.date,'revision':1,'status':'draft','source_handoffs':[self.hid]}
        self.value={'registry':{'processed_handoffs':[{'handoff_id':self.hid,'sha256_muse_computed':'a'*64}]},
                    'handoffs':[{'meta':meta,'sha256':'a'*64,'schema_v2_valid':True}],
                    'logs':[{'meta':log,'sha256':'b'*64}],
                    'sync_status':{'date':self.date,'conflicts':0,'sync_health':'partial'},
                    'checkpoints':{'checkpoints':[{'run_id':'sync-2026-11-11-2130-001','event_date':self.date,'handoff_id':self.hid,
                         'steps':{'input_validation':'completed','daily_log':'completed'},'last_attempt_at':'2026-11-11T21:33:00+09:00',
                         'outputs':{'daily_log':{**log,'sha256':'b'*64}}}]}}
    def run_check(self):return c.analyse(self.value,self.date,self.now)
    def codes(self):return {f['code'] for f in self.run_check()['findings']}
    def test_mechanical_agreement_never_authorizes_finalize(self):
        r=self.run_check();self.assertEqual(r['outcome'],'needs_review');self.assertFalse(r['authorization_granted'])
        self.assertEqual(r['drive_writes'],0);self.assertEqual(r['counts']['registered_hashes_matched'],1)
        self.assertIn('content_review',self.codes())
    def test_hash_mismatch_blocks(self):
        self.value['handoffs'][0]['sha256']='c'*64
        self.assertEqual(self.run_check()['outcome'],'not_eligible');self.assertIn('hash_mismatch',self.codes())
    def test_missing_checkpoint_never_inferred_from_registry(self):
        self.value['checkpoints']=None
        self.assertEqual(self.run_check()['outcome'],'input_missing');self.assertIn('sync_checkpoints_missing',self.codes())
    def test_revision_disagreement_blocks(self):
        self.value['logs'][0]['meta']['revision']=2
        self.assertIn('checkpoint_log_disagreement',self.codes())
    def test_output_hash_disagreement_blocks(self):
        self.value['logs'][0]['sha256']='c'*64
        self.assertIn('checkpoint_log_hash_disagreement',self.codes())
    def test_pending_required_step_blocks(self):
        self.value['checkpoints']['checkpoints'][0]['steps']['daily_log']='pending'
        self.assertIn('required_step_not_completed',self.codes())
    def test_unsupported_registry_not_guessed(self):
        self.value['registry']={'items':{}}
        with self.assertRaisesRegex(c.u.Error,'unsupported'):self.run_check()
    def test_duplicate_checkpoint_run_rejected(self):
        self.value['checkpoints']['checkpoints']*=2
        with self.assertRaisesRegex(c.u.Error,'duplicate checkpoint'):self.run_check()
    def test_unregistered_input_and_wrong_sync_date_reported(self):
        self.value['registry']['processed_handoffs']=[];self.value['sync_status']['date']='2026-11-10'
        self.assertIn('handoff_not_registered',self.codes());self.assertIn('sync_status_is_for_other_date',self.codes())
    def test_missing_handoff_and_log_reported(self):
        self.value['handoffs']=[];self.value['logs']=[]
        self.assertIn('no_handoff_for_date',self.codes());self.assertIn('daily_log_missing',self.codes())
    def test_healthy_draft_contradiction_blocks(self):
        self.value['sync_status']['sync_health']='healthy'
        self.assertIn('healthy_but_log_draft',self.codes())
    def test_before_deadline_blocks(self):
        self.now=self.now.replace(hour=21,minute=39)
        self.assertIn('before_finalization_deadline',self.codes())
    def test_new_deadline_boundary_is_2140(self):
        self.now=self.now.replace(hour=21,minute=40)
        self.assertNotIn('before_finalization_deadline',self.codes())
    def test_drive_writes_and_id_allocation_blocked_before_network(self):
        with patch.dict(os.environ,{'MUSE_DRIVE_ACCESS_TOKEN':'unit-test-only'}):
            backend=c.ReadOnlyDrive({'handoff_folder_id':'fakefolderid123'})
        for action in (lambda:backend.create('x','x',b'x'),lambda:backend.new_id(),
                       lambda:backend.api('POST','files'),lambda:backend.api('GET','files/generateIds'),
                       lambda:backend.api('GET','files',data=b'x'),lambda:backend.api('DELETE','files/x')):
            with self.assertRaises(c.u.Error):action()
    def test_out_of_scope_month_fails_closed(self):
        self.date='2026-12-01'
        with self.assertRaisesRegex(c.u.Error,'bounded'):self.run_check()
    def backend(self,change_version=False,change_listing=False):
        raw=(Path(__file__).parent/'examples/valid-test-handoff.md').read_bytes()
        bodies={c.SYNC:b'{"date":"2026-11-11"}',c.REGISTRY:b'{"processed_handoffs":[]}',
                'input':raw,c.KNOWN_LOG:b'---\nevent_date: 2026-11-10\nlog_id: daily-2026-11-10\n---\nPrivate body not to be published'}
        class Fake:
            def __init__(self):self.info_calls={};self.list_calls={}
            def info(self,fid):
                n=self.info_calls.get(fid,0)+1;self.info_calls[fid]=n
                parent='month' if fid==c.KNOWN_LOG else c.u.PRODUCTION if fid=='input' else c.SYSTEM
                return {'id':fid,'parents':[parent],'version':'2' if change_version and fid==c.SYNC and n>1 else '1'}
            def read(self,fid):return bodies[fid]
            def listing(self,fid):
                self.list_calls[fid]=self.list_calls.get(fid,0)+1
                files={c.SYSTEM:[{'id':c.SYNC,'name':'sync_status.json'},{'id':c.REGISTRY,'name':'processed_handoffs.json'}],
                       c.u.PRODUCTION:[{'id':'input','name':'example.md'}],
                       'month':[{'id':c.KNOWN_LOG,'name':'2026-11-10.md'}]}[fid]
                if change_listing and fid==c.u.PRODUCTION and self.list_calls[fid]>1:files=files+[{'id':'new','name':'new.md'}]
                return files
        return Fake()
    def test_collection_redacts_body_and_checks_versions(self):
        result=c.collect(self.backend())
        self.assertEqual(result['files_version_checked'],4)
        self.assertNotIn('Private body',json.dumps(result,default=str))
    def test_change_during_read_never_returns_consistent_snapshot(self):
        with self.assertRaisesRegex(c.u.Error,'changed during audit'):c.collect(self.backend(change_version=True))
    def test_new_file_during_read_never_silently_omitted(self):
        with self.assertRaisesRegex(c.u.Error,'inventory changed'):c.collect(self.backend(change_listing=True))

if __name__=='__main__':unittest.main(verbosity=2)
