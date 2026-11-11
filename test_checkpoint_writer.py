import copy
import datetime as dt
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
import checkpoint_writer as w
import test_check_muse as fixtures

class MemoryDrive:
    folder='isolated-test-folder'
    def __init__(self):self.store={};self.names={};self.calls=[];self.n=0;self.lose_response=False
    def new_id(self):self.n+=1;return 'test-id-'+str(self.n)
    def files(self):return [{'id':fid,'name':name} for fid,name in self.names.items()]
    def read(self,fid):return self.store.get(fid)
    def create(self,fid,name,data,backup=False):
        if fid in self.store:raise AssertionError('overwrite via create')
        self.store[fid]=data;self.names[fid]=name;self.calls.append(('backup' if backup else 'create',fid))
        if self.lose_response:self.lose_response=False;raise OSError('response lost after create')
    def update(self,fid,data):
        self.store[fid]=data;self.calls.append(('update',fid))
        if self.lose_response:self.lose_response=False;raise OSError('response lost after update')

class WriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.backend=MemoryDrive();base=fixtures.CheckerTests();base.setUp();self.addCleanup(base.doCleanups);self.snapshot=base.value
        self.snapshot['handoffs'][0]['file_id']='input';self.snapshot['logs'][0]['file_id']='log'
        self.snapshot['evidence_files']=[{'file_id':'input','sha256':'a'*64,'version':'1'},
                                         {'file_id':'log','sha256':'b'*64,'version':'1'}]
        self.now=base.now;self.date=base.date
    def run_writer(self,apply=True,phase='manual'):
        return w.run(self.backend,self.root,lambda:copy.deepcopy(self.snapshot),self.date,apply,phase,self.now)
    def test_dry_run_has_no_remote_or_journal_mutations(self):
        result=self.run_writer(False);self.assertEqual(result['result'],'would_append')
        self.assertEqual(self.backend.calls,[]);self.assertFalse((self.root/'writer.json').exists())
    def test_create_verified_and_same_source_skips_without_duplicate(self):
        first=self.run_writer();second=self.run_writer()
        self.assertEqual(first['observations'],1);self.assertEqual(first['checkpoints'],1)
        self.assertEqual(second['result'],'duplicate_verified');self.assertEqual(len(self.backend.calls),1)
        doc=json.loads(self.backend.read(first['file_id']));cp=doc['checkpoints'][0]
        self.assertFalse(cp['authorization_granted']);self.assertEqual(cp['steps']['content_review'],'needs_review')
        self.assertEqual(cp['overall_status'],'partial')
    def test_new_phase_preserves_prior_record_and_creates_verified_backup(self):
        first=self.run_writer();before=self.backend.read(first['file_id'])
        second=self.run_writer(phase='after_context')
        self.assertEqual(second['observations'],2)
        backups=[fid for op,fid in self.backend.calls if op=='backup']
        self.assertEqual(len(backups),1);self.assertEqual(self.backend.read(backups[0]),before)
        doc=json.loads(self.backend.read(first['file_id']))
        self.assertEqual(len({r['run_id'] for r in doc['checkpoints']}),2)
    def test_lost_create_response_reuses_identity_and_same_payload(self):
        self.backend.lose_response=True
        with self.assertRaises(OSError):self.run_writer()
        result=self.run_writer();self.assertEqual(result['observations'],1)
        self.assertEqual(sum(op=='create' for op,_ in self.backend.calls),1)
    def test_lost_update_response_recovers_without_second_append(self):
        self.run_writer()
        original=self.backend.update
        def lose(fid,data):original(fid,data);raise OSError('lost update response')
        self.backend.update=lose
        with self.assertRaises(OSError):self.run_writer(phase='after_brief')
        self.backend.update=original
        result=self.run_writer(phase='after_brief');self.assertEqual(result['observations'],2)
        self.assertEqual(sum(op=='update' for op,_ in self.backend.calls),1)
    def test_unknown_existing_ledger_never_adopted(self):
        self.backend.create('other',w.NAME,b'{}')
        with self.assertRaisesRegex(w.u.Error,'refusing to adopt'):self.run_writer()
        self.assertEqual(self.backend.read('other'),b'{}')
    def test_external_edit_stops_and_is_not_overwritten(self):
        first=self.run_writer();self.backend.store[first['file_id']]=b'changed externally'
        with self.assertRaisesRegex(w.u.Error,'changed outside'):self.run_writer()
        self.assertEqual(self.backend.read(first['file_id']),b'changed externally')
    def test_disagreement_is_observed_without_rebasing_expected_checkpoint(self):
        self.snapshot['logs'][0]['meta']['revision']=2
        result=self.run_writer();doc=json.loads(self.backend.read(result['file_id']))
        self.assertEqual(doc['checkpoints'],[]);self.assertTrue(doc['observations'][0]['reconciliation_required'])
    def test_uncommitted_output_never_auto_changes_pending_to_completed(self):
        self.snapshot['checkpoints']['checkpoints'][0]['steps']['daily_log']='pending'
        result=self.run_writer();doc=json.loads(self.backend.read(result['file_id']))
        self.assertEqual(doc['checkpoints'],[]);self.assertTrue(doc['observations'][0]['reconciliation_required'])
    def test_no_handoff_records_observation_not_fabricated_checkpoint(self):
        self.snapshot['handoffs']=[];self.snapshot['registry']={'processed_handoffs':[]};self.snapshot['logs']=[];self.snapshot['checkpoints']=None
        result=self.run_writer();self.assertEqual(result['checkpoints'],0);self.assertEqual(result['observations'],1)
    def test_own_ledger_is_excluded_from_fingerprint(self):
        first=self.run_writer()
        self.snapshot['evidence_files'].append({'file_id':first['file_id'],'sha256':'changed-ledger','version':'2'})
        self.assertEqual(self.run_writer()['result'],'duplicate_verified')
    def test_two_inputs_have_unique_run_ids(self):
        second=copy.deepcopy(self.snapshot['handoffs'][0]);second['meta']['handoff_id']='chatgpt-2026-11-11-second'
        self.snapshot['handoffs'].append(second)
        result=self.run_writer();doc=json.loads(self.backend.read(result['file_id']))
        self.assertEqual(len({r['run_id'] for r in doc['checkpoints']}),2)
    def test_missing_verified_ledger_not_recreated(self):
        first=self.run_writer();self.backend.store.pop(first['file_id']);self.backend.names.pop(first['file_id'])
        with self.assertRaisesRegex(w.u.Error,'disappeared'):self.run_writer()
    def test_pending_payload_tamper_stops_recovery(self):
        self.backend.lose_response=True
        with self.assertRaises(OSError):self.run_writer()
        state=json.loads((self.root/'writer.json').read_text());(self.root/state['pending']['payload']).write_text('tampered')
        with self.assertRaisesRegex(w.u.Error,'payload changed'):self.run_writer()
    def test_backup_failure_never_updates_current_ledger(self):
        first=self.run_writer();old=self.backend.read(first['file_id'])
        original=self.backend.create
        def corrupt(fid,name,data,backup=False):original(fid,name,b'corrupt' if backup else data,backup)
        self.backend.create=corrupt
        with self.assertRaisesRegex(w.u.Error,'backup read-back failed'):self.run_writer(phase='after_brief')
        self.assertEqual(self.backend.read(first['file_id']),old)
        self.assertEqual(sum(op=='update' for op,_ in self.backend.calls),0)
    def test_second_local_writer_is_locked_out(self):
        with open(self.root/'writer.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(w.u.Error,'another Mac checkpoint writer'):self.run_writer()
        self.assertEqual(self.backend.calls,[])
    def test_expired_history_is_not_silently_deleted(self):
        doc={'observations':[{'event_date':'2026-08-01','fingerprint':'old','run_id':'sync-2026-08-01-2130-001'}],'checkpoints':[]}
        before=copy.deepcopy(doc)
        with self.assertRaisesRegex(w.u.Error,'archive required'):w.observation(doc,self.snapshot,self.date,self.now)
        self.assertEqual(doc,before)

class ScheduleTests(unittest.TestCase):
    def test_observer_phase_uses_amended_jst_boundaries(self):
        cases=[(20,29,'manual'),(20,30,'after_initial'),(20,40,'after_initial'),(21,10,'after_retry_1'),(21,38,'after_retry_2'),(21,48,'after_finalize'),(21,55,'after_context'),(22,10,'after_brief')]
        for hour,minute,expected in cases:
            with self.subTest(hour=hour,minute=minute):
                now=dt.datetime(2026,11,11,hour,minute,tzinfo=w.check.JST)
                self.assertEqual(w.phase_for_time(now),expected)
                self.assertEqual(w.phase_for_time(now.astimezone(dt.timezone.utc)),expected)

if __name__=='__main__':unittest.main(verbosity=2)
