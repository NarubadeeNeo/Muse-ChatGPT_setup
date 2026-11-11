"""Per-install constants; the supplied defaults are non-live placeholders for offline tests."""
import json
from pathlib import Path

def value(key):
    path=Path(__file__).with_name('deployment.json')
    values=json.loads(path.read_text()) if path.exists() else {}
    if key in values:return values[key]
    if key=='log_month':return '2026-11'
    if key in ('legacy_exception_date','manual_finalize_date'):return None
    return 'UNCONFIGURED_'+key.upper()
