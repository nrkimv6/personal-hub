import json
import os
import sys
from datetime import datetime

project_dir = r'C:\Users\Narang\.claude\projects\D--work-project-tools-monitor-page'
keywords = ['스크립트 정리', '스크립트정리', 'script', '스크립트', 'scripts/', 'scripts 정리', '정리', '리오거', 'reorganiz', 'reorg', 'organize']

# Find all jsonl files and their mtime
files = []
for f in os.listdir(project_dir):
    if f.endswith('.jsonl'):
        path = os.path.join(project_dir, f)
        mtime = os.path.getmtime(path)
        files.append((mtime, f, path))

files.sort(reverse=True)

# Scan files from before reboot (2026-04-11 ~09:10 KST = 00:10 UTC)
# mtime before 2026-04-11 00:10 UTC means before reboot
import time
# Actually we want sessions that were active BEFORE reboot
# Reboot was approximately 08:30 KST = 2026-04-10 23:30 UTC on Apr 10 (wait, KST is UTC+9)
# 08:30 KST on 2026-04-11 = 2026-04-10 23:30 UTC
# So any session with mtime < 2026-04-10 23:30 UTC is before reboot
import datetime as dt
reboot_utc = dt.datetime(2026, 4, 10, 23, 30).timestamp()

print(f'Scanning {len(files)} session files for script-related keywords...')
print(f'Reboot cutoff (UTC): {dt.datetime.fromtimestamp(reboot_utc)}\n')

for mtime, name, path in files:
    mt = dt.datetime.fromtimestamp(mtime)
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
        text = raw.decode('utf-8', errors='replace')
    except Exception as e:
        continue
    # Quick scan
    hits = []
    for kw in keywords:
        if kw in text:
            # count occurrences
            cnt = text.count(kw)
            hits.append((kw, cnt))
    if not hits:
        continue
    tag = 'PRE' if mtime < reboot_utc else 'POST'
    # Get first and last timestamps
    lines = text.splitlines()
    first_ts = last_ts = ''
    for line in lines:
        try:
            d = json.loads(line)
            if 'timestamp' in d:
                first_ts = d['timestamp']
                break
        except Exception:
            pass
    for line in reversed(lines):
        try:
            d = json.loads(line)
            if 'timestamp' in d:
                last_ts = d['timestamp']
                break
        except Exception:
            pass
    print(f'[{tag}] {name} mtime={mt.strftime("%m-%d %H:%M")}  span={first_ts[:19]} ~ {last_ts[:19]}')
    print(f'       hits: {hits[:6]}')
