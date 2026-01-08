#!/usr/bin/env python3
"""
Fix mismatched button tags: <button> with </Button>
This happens when Phase 3 script converted closing tags but not opening tags.
"""

import re
from pathlib import Path

def fix_button_tags(content: str) -> tuple[str, int]:
    """Fix <button> ... </Button> to <button> ... </button>"""
    count = 0

    # Find all <button> tags and their corresponding </Button>
    # Replace </Button> with </button> if there's an unmatched <button> before it

    lines = content.split('\n')
    button_stack = []  # Track <button> openings

    for i, line in enumerate(lines):
        # Check for <button or <Button tags
        if re.search(r'<button\b', line, re.IGNORECASE):
            if '<button' in line.lower():
                button_stack.append(('button', i))

        # Check for closing tags
        if '</Button>' in line and button_stack and button_stack[-1][0] == 'button':
            # Mismatch! Replace </Button> with </button>
            lines[i] = line.replace('</Button>', '</button>')
            button_stack.pop()
            count += 1
        elif '</button>' in line.lower():
            if button_stack:
                button_stack.pop()

    return '\n'.join(lines), count

def main():
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"[ERROR] Directory not found: {target_dir}")
        return

    files = list(target_dir.rglob('*.svelte'))
    files = [f for f in files if 'node_modules' not in str(f)]

    print("Fixing mismatched button tags...")
    print(f"Target files: {len(files)}\n")

    total_files = 0
    total_fixes = 0

    for file_path in files:
        try:
            content = file_path.read_text(encoding='utf-8')
            new_content, count = fix_button_tags(content)

            if count > 0:
                file_path.write_text(new_content, encoding='utf-8')
                total_files += 1
                total_fixes += count
                relative = file_path.relative_to(target_dir)
                print(f"  [OK] {relative} ({count} fixes)")
        except Exception as e:
            print(f"  [ERROR] {file_path.name}: {e}")

    print(f"\nCompleted!")
    print(f"  - Modified files: {total_files}")
    print(f"  - Total fixes: {total_fixes}")

if __name__ == '__main__':
    main()
