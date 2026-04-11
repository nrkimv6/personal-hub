import json
import sys

path = sys.argv[1]
line_num = int(sys.argv[2])
with open(path, 'rb') as f:
    text = f.read().decode('utf-8', errors='replace')
lines = text.splitlines()
d = json.loads(lines[line_num])
msg = d.get('message', {})
content = msg.get('content', [])
if isinstance(content, list):
    for c in content:
        if isinstance(c, dict) and c.get('type') == 'text':
            print(c.get('text', ''))
elif isinstance(content, str):
    print(content)
