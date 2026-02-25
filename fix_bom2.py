import os

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\engines.json'

if os.path.exists(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()

    # Check for UTF-8 BOM
    if content.startswith(b'\xef\xbb\xbf'):
        print("BOM found. Removing...")
        content = content[3:]
        with open(filepath, 'wb') as f:
            f.write(content)
        print("BOM removed and file saved.")
    else:
        print("No BOM found in engines.json.")
else:
    print(f"File not found: {filepath}")
