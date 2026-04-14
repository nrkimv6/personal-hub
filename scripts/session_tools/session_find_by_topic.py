import json
import os

project_dir = r'C:\Users\Narang\.claude\projects\D--work-project-tools-monitor-page'
REBOOT_UTC_ISO = '2026-04-10T23:30:00'

# Find sessions where user TYPED a short message mentioning scripts/script/스크립트
results = []

for fname in os.listdir(project_dir):
    if not fname.endswith('.jsonl'):
        continue
    path = os.path.join(project_dir, fname)
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
        text = raw.decode('utf-8', errors='replace')
    except Exception:
        continue
    lines = text.splitlines()
    last_ts = ''
    for line in reversed(lines):
        try:
            d = json.loads(line)
            if 'timestamp' in d:
                last_ts = d['timestamp']
                break
        except Exception:
            pass
    if not last_ts or last_ts >= REBOOT_UTC_ISO:
        continue  # only pre-reboot sessions

    matches = []
    for i, line in enumerate(lines):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('type') != 'user':
            continue
        msg = d.get('message', {})
        if not isinstance(msg, dict):
            continue
        content = msg.get('content')
        if isinstance(content, str):
            txt = content
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'text':
                    parts.append(c.get('text', ''))
            txt = ' '.join(parts)
        else:
            txt = ''
        if not txt:
            continue
        # Short user-typed messages only
        if len(txt) > 600:
            continue
        # Skip system/command/result wrappers
        if '<system-reminder>' in txt[:200] or '<command-' in txt[:200]:
            continue
        if 'This session is being continued' in txt[:100]:
            continue
        if '[tool_result]' in txt[:50]:
            continue
        if 'Base directory for this skill' in txt[:100]:
            continue
        if 'Route this request to' in txt[:100]:
            continue
        # Mention scripts/script/스크립트
        if 'scripts' in txt.lower() or '스크립트' in txt or 'script/' in txt:
            matches.append((d.get('timestamp', ''), i, txt[:500].replace('\n', ' | ')))
    if matches:
        results.append((last_ts, fname, matches))

results.sort(reverse=True)
print(f'Found {len(results)} pre-reboot sessions with short user messages mentioning scripts:\n')
for last_ts, fname, matches in results[:40]:
    print(f'=== {fname} (last: {last_ts}) — {len(matches)} matches ===')
    for ts, i, t in matches[:6]:
        print(f'  [{ts}] L{i}: {t[:300]}')
    print()
