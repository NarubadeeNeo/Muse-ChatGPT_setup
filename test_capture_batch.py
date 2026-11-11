import copy
import datetime as dt
import unittest
import capture_batch as b

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,11,20,30,tzinfo=dt.timezone(dt.timedelta(hours=9)))
        self.settings={'capture_allowlist':{'chat-a':'Example'}}
        self.value={'thread':{'kind':'chatgpt','id':'chat-a'},'page':{'hasMore':False},'turns':[
            {'id':'turn','startedAt':dt.datetime(2026,11,10,13,tzinfo=self.now.tzinfo).timestamp(),
             'status':'completed','items':[{'type':'agentMessage','id':'m','text':'Not completed.'}]}]}
    def prepare(self):return b.prepare([self.value],self.settings,self.now)
    def test_missing_conversation_fails_coverage_receipt(self):
        self.settings['capture_allowlist']['chat-b']='Other'
        with self.assertRaisesRegex(b.u.Error,'every allowlisted'):self.prepare()
    def test_previous_day_included_older_day_filtered(self):
        jobs,receipt=self.prepare();self.assertEqual(len(jobs[0]['turns']),1)
        self.assertFalse(receipt['full_account_history'])
        self.value['turns'][0]['startedAt']-=86400
        jobs,_=self.prepare();self.assertEqual(jobs[0]['turns'],[])
    def test_pending_turn_never_certified(self):
        self.value['turns'][0]['status']='in_progress'
        with self.assertRaisesRegex(b.u.Error,'unfinished'):self.prepare()
    def test_more_pages_inside_window_required(self):
        self.value['page']['hasMore']=True
        with self.assertRaisesRegex(b.u.Error,'more source pages'):self.prepare()
        self.value['turns'][0]['startedAt']-=86400
        self.prepare()
    def test_truncated_messages_rejected(self):
        self.value['turns'][0]['items'][0]['truncated']=True
        with self.assertRaisesRegex(b.u.Error,'truncated'):self.prepare()
    def test_unapproved_chat_rejected(self):
        self.value['thread']['id']='private-other'
        with self.assertRaisesRegex(b.u.Error,'unapproved'):self.prepare()

if __name__=='__main__':unittest.main(verbosity=2)
