import json
import sys

path = sys.argv[1]

with open(path, 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8', errors='replace')
lines = text.splitlines()

# Dump user messages and assistant text summaries
for i, line in enumerate(lines):
    try:
        d = json.loads(line)
    except Exception:
        continue
    typ = d.get('type', '')
    msg = d.get('message', {}) if isinstance(d.get('message'), dict) else {}
    content = msg.get('content')
    if isinstance(content, str):
        txt = content
        kind = 'text'
    elif isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get('type') == 'text':
                    parts.append('[T]' + (c.get('text', '') or '')[:400])
                elif c.get('type') == 'tool_use':
                    name = c.get('name', '')
                    parts.append(f'[U:{name}]')
                elif c.get('type') == 'tool_result':
                    parts.append('[R]')
        txt = ' '.join(parts)
        kind = 'multi'
    else:
        continue
    if not txt:
        continue
    if typ == 'user':
        full_txt = ''
        if isinstance(content, str):
            full_txt = content
        else:
            full_txt = ' '.join([c.get('text','') for c in content if isinstance(c, dict) and c.get('type')=='text'])
        if not full_txt.strip():
            continue
        if '<system-reminder>' in full_txt[:200] or '<command-' in full_txt[:200]:
            continue
        if 'Base directory for this skill' in full_txt[:100]:
            continue
        if 'This session is being continued' in full_txt[:100]:
            continue
        if '<task-notification>' in full_txt[:30]:
            continue
        ts = d.get('timestamp', '')
        clean = full_txt[:600].replace('\n', ' | ')
        print(f'L{i} [{ts}] USER: {clean}')
    elif typ == 'assistant':
        # Only print text parts (not tool_use dumps)
        if isinstance(content, list):
            texts = [c.get('text', '') for c in content if isinstance(c, dict) and c.get('type') == 'text']
            text_joined = ' | '.join(t for t in texts if t)
            if text_joined.strip():
                ts = d.get('timestamp', '')
                clean = text_joined[:400].replace('\n', ' | ')
                print(f'L{i} [{ts}] ASST: {clean}')
