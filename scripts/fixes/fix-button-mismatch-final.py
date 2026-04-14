#!/usr/bin/env python3
"""
Fix button/Button tag mismatches
<button> should close with </button>
<Button> should close with </Button>
"""

import re
from pathlib import Path

def fix_file(file_path: Path) -> int:
    """Fix button tag mismatches in a file"""
    content = file_path.read_text(encoding='utf-8')
    original = content

    # Strategy: Find all </Button> and check if the corresponding opening tag is <button> (lowercase)
    # If so, change </Button> to </button>

    lines = content.split('\n')
    tag_stack = []  # Stack of (tag_type, line_num) where tag_type is 'button' or 'Button'

    for i, line in enumerate(lines):
        # Find opening tags
        for match in re.finditer(r'<(button|Button)\b', line, re.IGNORECASE):
            tag = match.group(1)
            tag_stack.append((tag, i))

        # Find closing tags
        for match in re.finditer(r'</(button|Button)>', line, re.IGNORECASE):
            close_tag = match.group(1)
            if tag_stack:
                open_tag, _ = tag_stack.pop()
                # Mismatch: lowercase open, uppercase close
                if open_tag.islower() and close_tag[0].isupper():
                    lines[i] = lines[i].replace(f'</{close_tag}>', f'</{open_tag}>')
                # Mismatch: uppercase open, lowercase close
                elif open_tag[0].isupper() and close_tag.islower():
                    lines[i] = lines[i].replace(f'</{close_tag}>', f'</{open_tag}>')

    new_content = '\n'.join(lines)

    if new_content != original:
        file_path.write_text(new_content, encoding='utf-8')
        return 1
    return 0

def main():
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"[ERROR] Directory not found: {target_dir}")
        return

    files = list(target_dir.rglob('*.svelte'))
    files = [f for f in files if 'node_modules' not in str(f)]

    print(f"Fixing button tag mismatches...")
    print(f"Target files: {len(files)}\n")

    total_files = 0

    for file_path in files:
        try:
            if fix_file(file_path):
                total_files += 1
                relative = file_path.relative_to(target_dir)
                print(f"  [OK] {relative}")
        except Exception as e:
            print(f"  [ERROR] {file_path.name}: {e}")

    print(f"\nCompleted! Modified {total_files} files")

if __name__ == '__main__':
    main()
