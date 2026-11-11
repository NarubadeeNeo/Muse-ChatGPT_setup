#!/usr/bin/env python3
"""Create local config/plists only. Does not authenticate, write Drive or load launchd."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import plistlib
import re

ID_KEYS=('handoff_folder_id','session_folder_id','system_folder_id','sync_status_file_id','registry_file_id','known_log_file_id','backup_folder_id')
def prepare(root,values):
    root=Path(root).resolve()
    for key in ID_KEYS:
        value=values.get(key)
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,100}',value) or value.startswith(('YOUR_','UNCONFIGURED_')):
            raise ValueError('Fill an actual Drive ID for '+key)
    if len({values[k] for k in ID_KEYS})!=len(ID_KEYS):raise ValueError('Different Drive roles require different IDs')
    month=values.get('log_month','')
    dt.date.fromisoformat(month+'-01')
    start=dt.date.fromisoformat(values['generation_start_date'])
    if start.strftime('%Y-%m')!=month:raise ValueError('generation_start_date must be in the configured log_month for this pilot')
    for key in ('legacy_exception_date','manual_finalize_date'):
        if values.get(key) is not None:dt.date.fromisoformat(values[key])
    cli=Path(values['codex_cli']).expanduser().resolve() if values.get('codex_cli') else None
    if cli is not None and (not cli.is_file() or not os.access(cli,os.X_OK)):raise ValueError('codex_cli must point to an installed executable, or be null for manual Handoffs')
    mode=values.get('capture_mode','allowlist')
    if mode not in ('allowlist','all_accessible'):raise ValueError('Unsupported capture_mode')
    days=values.get('capture_window_days',1 if mode=='all_accessible' else 2)
    if type(days) is not int or days not in (1,2):raise ValueError('capture_window_days must be 1 or 2')
    allowed=values.get('capture_allowlist',{}) if mode=='allowlist' else {}
    limit=values.get('source_day_max_bytes',256000 if mode=='all_accessible' else 128000)
    if type(limit) is not int or not 128000<=limit<=2*1024*1024:raise ValueError('Invalid bounded source_day_max_bytes')
    if not isinstance(allowed,dict) or any(not isinstance(k,str) or not k or k.startswith('YOUR_') or not isinstance(v,str) or not v.strip() for k,v in allowed.items()):
        raise ValueError('Fill capture_allowlist or use {} for manual Session Summaries')
    # Never regenerate a live deployment or replace any existing journal/config.
    if (root/'deployment.json').exists() or (root/'.private/config.json').exists():raise ValueError('Existing installation: edit/migrate deliberately; no overwrite')
    private=root/'.private';runtime=root/'.runtime'
    for p in (private,runtime,root/'outbox',root/'logs',root/'capture',runtime/'launchd'):
        p.mkdir(parents=True,exist_ok=True,mode=0o700)
    private.chmod(0o700);runtime.chmod(0o700)
    config={'handoff_folder_id':values['handoff_folder_id'],'connectivity_folder_id':'','connectivity_folder_name':'muse-uploader-connectivity-tests',
            'allow_handoff_upload':False,'exclusive_writer_confirmed':False,'full_folder_visibility_confirmed':False,
            'token_env':'MUSE_DRIVE_ACCESS_TOKEN','local_store':str(runtime/'local-store'),'state_dir':str(private/'uploader-state')}
    settings={'outbox':str(root/'outbox'),'uploader_config':str(private/'config.json'),'token_file':str(private/'handoff-token.json'),
              'log_dir':str(root/'logs'),'generation_state':str(private/'generation-state'),'generation_start_date':str(start),
              'model_runtime':str(runtime/'model-runtime'),'codex_cli':str(cli) if cli else '', 'capture_state':str(private/'capture-state'),
              'capture_receipt':str(private/'capture-latest.json'),'capture_allowlist':allowed,'capture_mode':mode,'capture_window_days':days,'source_day_max_bytes':limit,
              'checkpoint_state':str(private/'checkpoint-state'),'checkpoint_file_id':None}
    def write_json(path,value):
        with open(path,'x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
        path.chmod(0o600)
    for path,value in ((root/'deployment.json',values),(private/'config.json',config),(private/'schedule-settings.json',settings)):
        write_json(path,value)
    jobs=[('local.muse.handoff-uploader','daily_pipeline.py' if cli else 'scheduled_upload.py',[(20,0)],[]),
          ('local.muse.checkpoint-observer','checkpoint_writer.py',[(20,40),(21,10),(21,38),(21,48),(21,55),(22,10)],
           ['--phase','auto','--report',str(root/'logs/checkpoint-latest.json')])]
    for label,script,times,extra in jobs:
        value={'Label':label,'ProgramArguments':[str(root/'.venv/bin/python'),str(root/script),'--settings',str(private/'schedule-settings.json'),'--apply']+extra,
               'WorkingDirectory':str(root),'EnvironmentVariables':{'TZ':'Asia/Tokyo','PYTHONUNBUFFERED':'1'},'RunAtLoad':False,'KeepAlive':False,'ProcessType':'Background','Umask':63,
               'StartCalendarInterval':[{'Hour':h,'Minute':m} for h,m in times],
               'StandardOutPath':str(root/'logs'/(label+'.stdout.log')),'StandardErrorPath':str(root/'logs'/(label+'.stderr.log'))}
        with open(runtime/'launchd'/(label+'.plist'),'xb') as f:plistlib.dump(value,f)
    return {'prepared':True,'drive_upload_enabled':False,'launchd_loaded':False,'settings':str(private/'schedule-settings.json')}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--deployment',required=True);a=p.parse_args()
    try:print(json.dumps(prepare(Path(__file__).parent,json.loads(Path(a.deployment).read_text())),indent=2));return 0
    except Exception as e:print(str(e) if isinstance(e,ValueError) else type(e).__name__);return 2
if __name__=='__main__':raise SystemExit(main())
