import json
from datetime import datetime

path = r'D:\work\project\tools\monitor-page\logs\death_log.json'
cutoff = datetime.fromisoformat('2026-02-24T19:00:00')

kept = []
removed = 0
with open(path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry['timestamp'])
            if ts < cutoff:
                kept.append(line)
            else:
                removed += 1
        except Exception:
            kept.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(kept) + ('\n' if kept else ''))

print(f'removed={removed}, kept={len(kept)}')
