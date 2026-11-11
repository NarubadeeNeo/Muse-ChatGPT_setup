#!/usr/bin/env python3
"""Verify distributed files against MANIFEST.sha256; no network or account access."""
import hashlib
from pathlib import Path

def main():
    root=Path(__file__).resolve().parent;checked=0
    for line in (root/'MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);path=(root/name).resolve()
        if root not in path.parents:raise ValueError('Unsafe manifest path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Hash mismatch: '+name)
        checked+=1
    print(str(checked)+' distributed files verified (runtime files are not in the distribution manifest).')
    return 0
if __name__=='__main__':raise SystemExit(main())
