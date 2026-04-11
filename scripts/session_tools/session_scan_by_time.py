"""Scan all sessions for user messages about scripts organization, across all BSOD windows."""
import json
import os
from datetime import datetime

project_dir = r'C:\Users\Narang\.claude\projects\D--work-project-tools-monitor-page'

# BSOD timestamps (KST → UTC)
BSODS_KST = [
    ('2026-04-06 05:02', '2026-04-05T20:02:00'),
    ('2026-04-06 19:16', '2026-04-06T10:16:00'),
    ('2026-04-07 05:29', '2026-04-06T20:29:00'),
    ('2026-04-11 07:16', '2026-04-10T22:16:00'),
    ('2026-04-11 09:08', '2026-04-11T00:08:00'),
]

# Keywords in user messages that suggest scripts folder organization intent
user_keywords = [
    '스크립트 정리', '스크립트정리', '스크립트 폴더', 'scripts 정리', 'scripts/ 정리',
    'scripts 폴더', 'scripts폴더', '스크립트 재구성', '스크립트 분류',
    'scripts 재구성', 'scripts 카테고리', '스크립트 카테고리',
    'INDEX.md', '하위폴더', '하위 폴더', '폴더별로', '폴더로 구분',
    '150개', '너무 많', 'scripts/에', 'scripts에',
]

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
    lines = text.splitlines()
    # Get first/last ts
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

    # Find user messages with scripts-org intent
    msgs = []
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
            parts = [c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text']
            txt = ' '.join(parts)
        else:
            txt = ''
        if not txt or len(txt) > 1200:
            continue
        if '<system-reminder>' in txt[:200] or '<command-' in txt[:200] or '<task-notification>' in txt[:30]:
            continue
        if 'Base directory for this skill' in txt[:100] or 'This session is being continued' in txt[:100]:
            continue
        matched = [k for k in user_keywords if k in txt]
        if matched:
            msgs.append((d.get('timestamp', ''), i, matched, txt[:400].replace('\n', ' | ')))
    if msgs:
        # Check if session ends near a BSOD (within 30 minutes before)
        near_bsod = None
        if last_ts:
            for bsod_kst, bsod_utc in BSODS_KST:
                if last_ts < bsod_utc:
                    try:
                        last_dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00')).replace(tzinfo=None)
                        bsod_dt = datetime.fromisoformat(bsod_utc)
                        diff_min = (bsod_dt - last_dt).total_seconds() / 60
                        if 0 <= diff_min <= 60:
                            near_bsod = (bsod_kst, diff_min)
                            break
                    except Exception:
                        pass
        hits.append((last_ts, fname, first_ts, near_bsod, msgs))

hits.sort(reverse=True)
print(f'Found {len(hits)} sessions with user messages about scripts organization:\n')
for last_ts, fname, first_ts, near_bsod, msgs in hits:
    bsod_tag = f' 🔴 ENDED {near_bsod[1]:.0f}min BEFORE BSOD {near_bsod[0]}' if near_bsod else ''
    print(f'=== {fname}{bsod_tag}')
    print(f'    span: {first_ts[:19]} ~ {last_ts[:19]}')
    for ts, i, matched, t in msgs[:3]:
        print(f'    [{ts[:19]}] L{i} kw={matched[:3]}: {t[:300]}')
    print()
