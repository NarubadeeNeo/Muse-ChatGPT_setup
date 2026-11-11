#!/usr/bin/env python3
"""Publish evidence excerpts from app read_thread snapshots; no chat scraping or login UI."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import yaml
import uploader as u
import scheduled_upload as send
from daily_pipeline import SOURCE_FOLDER

SECTIONS=('Topics','Progress','Corrected Misunderstandings','Open Questions','Next Actions')

def full_excerpts(value):
    """Deterministic capture: full messages, without AI selection or paraphrase."""
    value=snapshot(value);items=[]
    for turn in value['turns']:
        for m in turn['items']:
            if m['type']=='userMessage':
                text='\n'.join(x['text'] for x in m.get('content',[]) if x.get('type')=='text');section='Topics'
            elif m['type']=='agentMessage':text=m.get('text','');section='Progress'
            else:continue
            if text.strip():items.append({'message_id':m['id'],'quote':text,'section':section})
    return items

def snapshot(value):
    if 'content' in value:
        value=json.loads(next(x['text'] for x in value['content'] if x.get('type')=='text'))
    if value.get('thread',{}).get('kind')!='chatgpt':raise u.Error('expected ChatGPT read_thread snapshot')
    return value

def render(value,selection,allowed):
    value=snapshot(value);thread=value['thread'];tid=thread['id']
    if tid not in allowed:raise u.Error('conversation not in academic allowlist')
    index={}
    for turn in value['turns']:
        date=dt.datetime.fromtimestamp(turn['startedAt'],dt.timezone(dt.timedelta(hours=9))).date().isoformat()
        for item in turn['items']:
            if item['type']=='userMessage':
                text='\n'.join(c['text'] for c in item.get('content',[]) if c.get('type')=='text');role='user'
            elif item['type']=='agentMessage':text=item.get('text','');role='assistant'
            else:continue
            index[item['id']]={'turn_id':turn['id'],'date':date,'role':role,'text':text}
    if not selection or not isinstance(selection,list):raise u.Error('nonempty excerpt selection required')
    groups={};seen=set()
    for chosen in selection:
        if set(chosen)!={'message_id','quote','section'}:raise u.Error('invalid excerpt fields')
        m=index.get(chosen['message_id']);quote=chosen['quote']
        if not m or not isinstance(quote,str) or not quote.strip() or quote not in m['text']:
            raise u.Error('excerpt not present in source message')
        if chosen['section'] not in SECTIONS:raise u.Error('unknown Session Summary section')
        identity=(chosen['message_id'],quote)
        if identity in seen:raise u.Error('duplicate excerpt in selection')
        seen.add(identity)
        groups.setdefault((m['date'],m['turn_id']),[]).append({**chosen,'turn_id':m['turn_id'],'role':m['role'],
                                                'message_sha256':u.sha(m['text'].encode())})
    results=[]
    for (date,turn_id),items in sorted(groups.items()):
        items.sort(key=lambda x:(x['turn_id'],x['message_id'],x['section'],x['quote']))
        digest=u.sha(json.dumps({'thread_id':tid,'event_date':date,'items':items},ensure_ascii=False,sort_keys=True).encode())
        sid='session-'+tid+'-'+digest
        meta={'session_summary_schema':1,'session_summary_id':sid,'source':'chatgpt','event_date':date,
              'timezone':'Asia/Tokyo','source_conversation_id':tid,'source_title':allowed[tid],
              'capture_method':'app_read_thread_exact_excerpts','coverage':'partial',
              'full_account_history':False,'attachments_reviewed':False,
              'source_turn_id':turn_id,'source_message_ids':sorted({x['message_id'] for x in items})}
        lines=['---',yaml.safe_dump(meta,allow_unicode=True,sort_keys=False).rstrip(),'---','',
               '# Session Summary: '+allowed[tid],'',
               'ข้อความคัดตรงจากบทสนทนา บทบาท assistant คือคำตอบที่เสนอในแชต ไม่ใช่ผลการทดลองที่ตรวจยืนยันแล้ว',
               'เก็บเฉพาะข้อความที่ระบุ ไม่ได้ตรวจไฟล์แนบ ไม่ยืนยันการทำงานเสร็จหรือความเข้าใจจากการสนทนาเพียงอย่างเดียว','']
        for section in SECTIONS:
            lines+=['## '+section]
            entries=[x for x in items if x['section']==section]
            if not entries:lines+=['ไม่มีข้อความที่เลือกสำหรับหัวข้อนี้ในรอบนี้']
            for item in entries:
                lines+=['- ['+item['role']+'; message '+item['message_id']+'; turn '+item['turn_id']+']',
                        '  '+json.dumps(item['quote'],ensure_ascii=False)]
            lines+=['']
        results.append((date+'-'+sid+'.md',('\n'.join(lines)+'\n').encode()))
    return results

def publish(value,selection,settings,apply=False,backend=None):
    allowed=settings['capture_allowlist']
    files=render(value,selection,allowed)
    if backend is None:
        c=json.loads(Path(settings['uploader_config']).read_text())
        os.environ[c.get('token_env','MUSE_DRIVE_ACCESS_TOKEN')]=send.token_without_login(settings['token_file'])
        backend=u.Drive(c);backend.folder_id=SOURCE_FOLDER;backend.expected_name='session_summaries'
    # Never accept an arbitrary destination in live capture.
    if isinstance(backend,u.Drive) and (backend.folder_id!=SOURCE_FOLDER or backend.expected_name!='session_summaries'):
        raise u.Error('unexpected capture destination')
    receipts=[]
    for name,data in files:
        u.transfer(backend,name,data,None,Path(settings['capture_state']),apply,'session-capture:'+backend.folder_id if isinstance(backend,u.Drive) else 'local-capture')
        receipts.append({'name':name,'sha256':u.sha(data),'bytes':len(data),'apply':apply})
    return receipts

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--settings',required=True);p.add_argument('--snapshot',required=True);p.add_argument('--selection',help='optional exact excerpt JSON; omit for deterministic full-message capture')
    p.add_argument('--apply',action='store_true');a=p.parse_args()
    try:
        value=json.loads(u.read_limited(a.snapshot))
        selection=json.loads(u.read_limited(a.selection)) if a.selection else full_excerpts(value)
        receipts=publish(value,selection,json.loads(Path(a.settings).read_text()),a.apply)
        u.log('session_capture_finished',files=receipts);return 0
    except Exception as e:
        u.log('session_capture_error',error=str(e) if isinstance(e,u.Error) else type(e).__name__);return 2

if __name__=='__main__':sys.exit(main())
