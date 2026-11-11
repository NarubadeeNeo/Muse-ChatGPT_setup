import copy
import datetime as dt
import json
import unittest
from unittest.mock import patch
import capture_batch as b
import daily_pipeline as d

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,11,20,tzinfo=dt.timezone(dt.timedelta(hours=9)))
        self.thread={'id':'new-chat','kind':'chatgpt','title':'New chat','updatedAt':self.now.timestamp()}
        self.pages=[self.page(False,[self.thread]),self.page(True,[])]
    def page(self,archived,threads,cursor=None,next_cursor=None):
        return {'source':'chatgpt','archived':archived,'cursor':cursor,'result':{'content':[{'type':'text','text':json.dumps({'threads':threads,'nextCursor':next_cursor})}]}}
    def test_daily_cutoff_allows_stopping_before_old_pages(self):
        old={**self.thread,'id':'old','updatedAt':self.now.timestamp()-86400}
        self.pages[0]=self.page(False,[self.thread,old],next_cursor='older-history')
        allowed,info=b.discovery_scope(self.pages,self.now)
        self.assertEqual(set(allowed),{'new-chat'});self.assertEqual(info['capture_window_days'],1)
    def test_cutoff_at_jst_midnight_is_inclusive(self):
        midnight=self.now.replace(hour=0)
        self.pages[0]=self.page(False,[{**self.thread,'id':'midnight','updatedAt':midnight.timestamp()},
                                     {**self.thread,'id':'yesterday','updatedAt':midnight.timestamp()-1}],next_cursor='old')
        self.assertEqual(set(b.discovery_scope(self.pages,self.now)[0]),{'midnight'})
    def test_unsorted_pages_cannot_claim_daily_cutoff(self):
        old={**self.thread,'id':'old','updatedAt':self.now.timestamp()-86400}
        self.pages[0]=self.page(False,[old,self.thread],next_cursor='older-history')
        with self.assertRaisesRegex(b.u.Error,'cutoff not verified'):b.discovery_scope(self.pages,self.now)
    def test_unknown_timestamp_prevents_early_stop(self):
        unknown={**self.thread,'id':'unknown'};unknown.pop('updatedAt')
        old={**self.thread,'id':'old','updatedAt':self.now.timestamp()-86400}
        self.pages[0]=self.page(False,[unknown,old],next_cursor='older-history')
        with self.assertRaisesRegex(b.u.Error,'cutoff not verified'):b.discovery_scope(self.pages,self.now)
    def test_today_capture_filters_yesterday_even_in_active_chat(self):
        allowed,info=b.discovery_scope(self.pages,self.now)
        settings={'capture_mode':'all_accessible','capture_window_days':1,'capture_allowlist':allowed,'capture_discovery':info}
        good={'id':'today','startedAt':self.now.timestamp(),'status':'completed','items':[]}
        old={**good,'id':'yesterday','startedAt':self.now.timestamp()-86400}
        value={'thread':self.thread,'page':{'hasMore':False},'turns':[good,old]}
        jobs,r=b.prepare([value],settings,self.now)
        self.assertEqual([t['id'] for t in jobs[0]['turns']],['today']);self.assertEqual(r['window_start'],'2026-11-11')
    def test_message_pagination_can_stop_at_yesterday(self):
        allowed,info=b.discovery_scope(self.pages,self.now)
        settings={'capture_mode':'all_accessible','capture_window_days':1,'capture_allowlist':allowed,'capture_discovery':info}
        old={'id':'old','startedAt':self.now.timestamp()-86400,'status':'completed','items':[]}
        jobs,_=b.prepare([{'thread':self.thread,'page':{'hasMore':True},'turns':[old]}],settings,self.now)
        self.assertEqual(jobs[0]['turns'],[])
    def test_two_day_window_requires_explicit_choice(self):
        old={**self.thread,'id':'yesterday','updatedAt':self.now.timestamp()-86400}
        self.pages[0]=self.page(False,[self.thread,old])
        self.assertEqual(len(b.discovery_scope(self.pages,self.now,2)[0]),2)
    def test_invalid_day_window_cannot_expand_history(self):
        for days in (0,True,3):
            with self.subTest(days=days),self.assertRaises(b.u.Error):b.discovery_scope(self.pages,self.now,days)
    def test_new_chat_requires_no_stored_allowlist(self):
        allowed,info=b.discovery_scope(self.pages,self.now)
        self.assertEqual(allowed,{'new-chat':'New chat'});self.assertEqual(info['discovered_chats'],1)
    def test_archived_recent_chat_is_included(self):
        self.pages[1]=self.page(True,[{**self.thread,'id':'archive-chat'}])
        self.assertEqual(len(b.discovery_scope(self.pages,self.now)[0]),2)
    def test_older_chat_is_counted_but_not_read_for_daily_window(self):
        self.thread['updatedAt']-=3*86400;self.pages[0]=self.page(False,[self.thread])
        allowed,info=b.discovery_scope(self.pages,self.now)
        self.assertEqual(allowed,{});self.assertEqual(info['metadata_only_older_chats'],1)
    def test_missing_timestamp_is_read_conservatively(self):
        del self.thread['updatedAt'];self.pages[0]=self.page(False,[self.thread])
        self.assertIn('new-chat',b.discovery_scope(self.pages,self.now)[0])
    def test_missing_archive_listing_rejected(self):
        with self.assertRaisesRegex(b.u.Error,'both active'):b.discovery_scope(self.pages[:1],self.now)
    def test_unfinished_discovery_rejected(self):
        self.pages[0]=self.page(False,[self.thread],next_cursor='next')
        with self.assertRaisesRegex(b.u.Error,'more discovery'):b.discovery_scope(self.pages,self.now)
    def test_wrong_cursor_chain_rejected(self):
        self.pages=[self.page(False,[],next_cursor='next'),self.page(False,[self.thread],cursor='wrong'),self.pages[1]]
        with self.assertRaisesRegex(b.u.Error,'cursor chain'):b.discovery_scope(self.pages,self.now)
    def test_tool_error_rejected(self):
        self.pages[0]['result']['isError']=True
        with self.assertRaisesRegex(b.u.Error,'tool failed'):b.discovery_scope(self.pages,self.now)
    def test_truncated_turn_does_not_hide_complete_turns(self):
        allowed,info=b.discovery_scope(self.pages,self.now)
        settings={'capture_mode':'all_accessible','capture_allowlist':allowed,'capture_discovery':info}
        turn={'id':'good','startedAt':self.now.timestamp(),'status':'completed','items':[{'id':'m','type':'agentMessage','text':'Source evidence.'}]}
        bad=copy.deepcopy(turn);bad['id']='bad';bad['items'][0]['truncated']=True
        value={'thread':self.thread,'page':{'hasMore':False},'turns':[turn,bad]}
        jobs,r=b.prepare([value],settings,self.now)
        self.assertEqual([t['id'] for t in jobs[0]['turns']],['good']);self.assertEqual(r['coverage'],'partial_accessible_chats')
        self.assertEqual(r['excluded_turns'][0]['turn_id'],'bad');self.assertFalse(r['full_account_history'])
    def test_missing_recent_chat_cannot_be_silently_omitted(self):
        allowed,info=b.discovery_scope(self.pages,self.now)
        with self.assertRaisesRegex(b.u.Error,'every allowlisted'):
            b.prepare([],{'capture_mode':'all_accessible','capture_allowlist':allowed,'capture_discovery':info},self.now)
    def test_empty_discovery_is_valid_without_fabricating_chats(self):
        pages=[self.page(False,[]),self.page(True,[])]
        allowed,info=b.discovery_scope(pages,self.now)
        jobs,r=b.prepare([],{'capture_mode':'all_accessible','capture_allowlist':allowed,'capture_discovery':info},self.now)
        self.assertEqual(jobs,[]);self.assertEqual(r['checked_chats'],0)

class DailyScopeTests(unittest.TestCase):
    def test_session_collision_check_reads_only_matching_filenames(self):
        class Backend:
            def files(self):return [{'id':'other','name':'other.md'},{'id':'same','name':'session.md'}]
            def read(self,fid):
                if fid!='same':raise AssertionError('Unrelated source bytes should not be downloaded')
                return b'evidence'
        self.assertEqual(b.u.inspect(Backend(),'session.md',b'evidence',None),'same')
    def backend(self,raw):
        class Backend:
            folder_id=d.SOURCE_FOLDER
            def api(self,*args):return b'{"name":"session_summaries","mimeType":"application/vnd.google-apps.folder"}'
            def files(self):return [{'id':'old','name':'2026-11-10-old.md'},{'id':'today','name':'2026-11-11-new.md'}]
            def read(self,fid):
                if fid=='old':raise AssertionError('Historical bytes should not be downloaded')
                return raw
        return Backend()
    def test_historical_day_is_skipped_before_size_limit(self):
        result=d.read_sources(self.backend(b'current evidence'),'2026-11-11','2026-11-11')
        self.assertEqual(set(result),{'2026-11-11'})
    def test_explicit_larger_day_limit_is_bounded(self):
        raw=b'x'*138228
        self.assertEqual(len(d.read_sources(self.backend(raw),'2026-11-11','2026-11-11',256000)['2026-11-11']),1)
        with self.assertRaisesRegex(d.u.Error,'no truncation'):d.read_sources(self.backend(raw),'2026-11-11','2026-11-11')
    def test_invalid_limit_cannot_disable_bounds(self):
        for size in (0,-1,True,d.u.MAX_BYTES+1):
            with self.subTest(size=size),self.assertRaises(d.u.Error):d.read_sources(self.backend(b'x'),'2026-11-11',max_day_bytes=size)

if __name__=='__main__':unittest.main(verbosity=2)
