#!/usr/bin/env python3
"""Validate a bounded source-chat collection, publish current excerpts, record coverage."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import capture_session as capture
import uploader as u

def prepare(values,settings,now=None):
    now=now or dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    today=now.date();start=today-dt.timedelta(days=1)
    allowed=settings['capture_allowlist'];seen=set();jobs=[]
    for raw in values:
        value=capture.snapshot(raw);tid=value['thread']['id']
        if tid not in allowed:raise u.Error('unapproved chat in collection')
        seen.add(tid)
        filtered=[];dates=[]
        for turn in value['turns']:
            date=dt.datetime.fromtimestamp(turn['startedAt'],now.tzinfo).date();dates.append(date)
            if start<=date<=today:
                if turn.get('status')!='completed':raise u.Error('unfinished turn in capture window; retry later')
                for item in turn['items']:
                    if item.get('truncated') or item.get('isTruncated'):
                        raise u.Error('truncated message; collection is partial')
                    text=item.get('text','')
                    if item.get('type')=='userMessage':text='\n'.join(x.get('text','') for x in item.get('content',[]))
                    if len(text)>=20000 or '[truncated]' in text.lower():raise u.Error('possibly truncated message; collection is partial')
                filtered.append(turn)
        jobs.append({**value,'turns':filtered})
    if seen!=set(allowed):raise u.Error('capture did not check every allowlisted conversation')
    # A page ending inside the window needs another page for that chat.
    for tid in seen:
        pages=[capture.snapshot(v) for v in values if capture.snapshot(v)['thread']['id']==tid]
        if all(p['page'].get('hasMore') for p in pages):
            dates=[dt.datetime.fromtimestamp(t['startedAt'],now.tzinfo).date() for p in pages for t in p['turns']]
            if not dates or min(dates)>=start:raise u.Error('more source pages required for capture window')
    return jobs,{'event_date':today.isoformat(),'window_start':start.isoformat(),'checked_chats':len(seen),
                 'allowlisted_chats':len(allowed),'coverage':'partial_allowlist_only','full_account_history':False,
                 'captured_at':now.isoformat()}

def run(paths,settings,apply=False):
    values=[json.loads(u.read_limited(p)) for p in paths]
    jobs,receipt=prepare(values,settings);files=[]
    for value in jobs:
        if value['turns']:
            files.extend(capture.publish(value,capture.full_excerpts(value),settings,apply))
    receipt.update(files=files,status='verified' if apply else 'dry_run')
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
