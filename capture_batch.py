#!/usr/bin/env python3
"""Validate a bounded source-chat collection, publish current excerpts, record coverage."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import capture_session as capture
import uploader as u

def window_start(now,days):
    if type(days) is not int or days not in (1,2):raise u.Error('capture_window_days must be 1 or 2')
    return now.date()-dt.timedelta(days=days-1)

def discovery_scope(records,now,days=1):
    """Validate newest-first pages; stop when a page crosses the requested JST day."""
    cutoff=dt.datetime.combine(window_start(now,days),dt.time(),now.tzinfo).timestamp()
    inventory={}
    for archived in (False,True):
        pages=[r for r in records if r.get('source')=='chatgpt' and r.get('archived') is archived]
        if not pages:raise u.Error('both active and archived discovery are required')
        cursor=None;visited=set();previous=None;ordered=True;older_seen=False
        for index,record in enumerate(pages):
            if record.get('cursor')!=cursor:raise u.Error('discovery cursor chain is incomplete')
            raw=record['result']
            if raw.get('isError'):raise u.Error('discovery tool failed')
            value=json.loads(next(x['text'] for x in raw['content'] if x.get('type')=='text'))
            for thread in value['threads']:
                if thread.get('kind')!='chatgpt' or not thread.get('id'):raise u.Error('invalid discovered ChatGPT conversation')
                inventory[thread['id']]=thread
                timestamp=thread.get('updatedAt')
                if type(timestamp) not in (int,float):ordered=False
                else:
                    if previous is not None and timestamp>previous:ordered=False
                    previous=timestamp
                    if timestamp<cutoff:older_seen=True
            cursor=value.get('nextCursor')
            if cursor in visited or (cursor is None and index!=len(pages)-1):raise u.Error('invalid discovery pagination')
            if cursor is not None:visited.add(cursor)
        if cursor is not None and not (ordered and older_seen):raise u.Error('more discovery pages required; daily cutoff not verified')
    recent={tid:t.get('title') or 'Untitled' for tid,t in inventory.items()
            if not isinstance(t.get('updatedAt'),(int,float)) or t['updatedAt']>=cutoff}
    return recent,{'discovered_chats':len(inventory),'candidate_chats':len(recent),
                   'metadata_only_older_chats':len(inventory)-len(recent),
                   'discovery_pages':len(records),'active_and_archived':True,
                   'discovery_scope':'date_window_only','capture_window_days':days}

def prepare(values,settings,now=None):
    now=now or dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    today=now.date();start=window_start(now,settings.get('capture_window_days',1 if settings.get('capture_mode')=='all_accessible' else 2))
    allowed=settings['capture_allowlist'];seen=set();jobs=[];issues=[]
    all_accessible=settings.get('capture_mode')=='all_accessible'
    unavailable=settings.get('capture_unavailable_chats',[])
    if any(not isinstance(e,dict) or e.get('id') not in allowed for e in unavailable):raise u.Error('invalid unavailable-chat evidence')
    for raw in values:
        value=capture.snapshot(raw);tid=value['thread']['id']
        if tid not in allowed:raise u.Error('unapproved chat in collection')
        seen.add(tid)
        filtered=[];dates=[]
        for turn in value['turns']:
            date=dt.datetime.fromtimestamp(turn['startedAt'],now.tzinfo).date();dates.append(date)
            if start<=date<=today:
                reason=None
                if turn.get('status')!='completed':reason='unfinished_turn'
                for item in turn['items']:
                    if item.get('truncated') or item.get('isTruncated'):
                        reason='truncated_message'
                    text=item.get('text','')
                    if item.get('type')=='userMessage':text='\n'.join(x.get('text','') for x in item.get('content',[]))
                    if len(text)>=20000 or '[truncated]' in text.lower():reason='truncated_message'
                if reason:
                    if not all_accessible:raise u.Error('unfinished turn in capture window; retry later' if reason=='unfinished_turn' else 'truncated message; collection is partial')
                    issues.append({'chat_id':tid,'turn_id':turn['id'],'reason':reason});continue
                filtered.append(turn)
        jobs.append({**value,'turns':filtered})
    if seen|{e['id'] for e in unavailable}!=set(allowed):raise u.Error('capture did not check every allowlisted conversation')
    # A page ending inside the window needs another page for that chat.
    for tid in seen:
        pages=[capture.snapshot(v) for v in values if capture.snapshot(v)['thread']['id']==tid]
        if all(p['page'].get('hasMore') for p in pages):
            dates=[dt.datetime.fromtimestamp(t['startedAt'],now.tzinfo).date() for p in pages for t in p['turns']]
            if not dates or min(dates)>=start:raise u.Error('more source pages required for capture window')
    receipt={'event_date':today.isoformat(),'window_start':start.isoformat(),'checked_chats':len(seen),
                 'allowlisted_chats':len(allowed),'coverage':'partial_allowlist_only','full_account_history':False,
                 'captured_at':now.isoformat()}
    if all_accessible:
        receipt.pop('allowlisted_chats')
        receipt.update(settings['capture_discovery'],capture_mode='all_accessible',
                       coverage='partial_accessible_chats' if issues or unavailable else 'accessible_chat_window',
                       excluded_turns=issues,unavailable_chats=unavailable)
    return jobs,receipt

def run(paths,settings,apply=False):
    if settings.get('capture_mode')=='all_accessible':
        if not isinstance(paths,dict) or not isinstance(paths.get('discovery'),list):raise u.Error('all-accessible capture requires discovery manifest')
        now=dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
        records=[json.loads(u.read_limited(p)) for p in paths['discovery']]
        allowed,info=discovery_scope(records,now,settings.get('capture_window_days',1))
        settings={**settings,'capture_allowlist':allowed,'capture_discovery':info,
                  'capture_unavailable_chats':paths.get('read_errors',[])}
        paths=paths['snapshots']
    values=[json.loads(u.read_limited(p)) for p in paths]
    jobs,receipt=prepare(values,settings);files=[]
    for value in jobs:
        if value['turns']:
            files.extend(capture.publish(value,capture.full_excerpts(value),settings,apply))
    partial=bool(receipt.get('excluded_turns') or receipt.get('unavailable_chats'))
    receipt.update(files=files,status=('partial' if partial else 'verified') if apply else 'dry_run')
    if apply:
        path=Path(settings['capture_receipt']);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        u.save_state(path,receipt)
    u.log('capture_batch_finished',**receipt)
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--settings',required=True)
    p.add_argument('--manifest',required=True,help='JSON list of source snapshot paths');p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:
        run(json.loads(Path(a.manifest).read_text()),json.loads(Path(a.settings).read_text()),a.apply);return 0
    except Exception as e:
        u.log('capture_batch_error',error=str(e) if isinstance(e,u.Error) else type(e).__name__);return 2

if __name__=='__main__':sys.exit(main())
