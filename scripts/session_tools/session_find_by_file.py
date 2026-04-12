"""Find which session created/edited archive-db-first-rotation plan."""
import json
import os

project_dir = r'C:\Users\Narang\.claude\projects\D--work-project-tools-monitor-page'

target = 'archive-db-first-rotation-and-wtools-ingest-cleanup'

hits = []
for fname in os.listdir(project_dir):
    if not fname.endswith('.jsonl'):
        continue
    path = os.path.join(project_dir, fname)
    try:
        with open(path, 'rb') as fh:
            text = fh.read().decode('utf-8', errors='replace')
    except Exception:
        continue
    if target not in text:
        continue
    lines = text.splitlines()
    # Find line numbers + timestamps of tool_use Write/Edit with that target
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
    # Find Write/Edit ops
    ops = []
    for i, line in enumerate(lines):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('type') != 'assistant':
            continue
        msg = d.get('message', {})
        if not isinstance(msg, dict):
            continue
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') != 'tool_use':
                continue
            inp = c.get('input', {})
            if not isinstance(inp, dict):
                continue
            fp = inp.get('file_path', '') or ''
            if target in fp:
                ops.append((d.get('timestamp', ''), i, c.get('name', ''), fp[:80]))
    hits.append((last_ts, fname, first_ts, ops))

hits.sort(reverse=True)
print(f'Sessions mentioning {target}:')
for last_ts, fname, first_ts, ops in hits:
    print(f'\n=== {fname}')
    print(f'    span: {first_ts[:19]} ~ {last_ts[:19]}')
    for ts, i, name, fp in ops[:5]:
        print(f'    [{ts[:19]}] L{i} {name}: ...{fp[-60:]}')
