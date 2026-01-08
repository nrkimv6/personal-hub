#!/usr/bin/env python3
"""
Fix variant size attribute spacing issue
variant="primary"sm → variant="primary" size="sm"
"""

import re
from pathlib import Path

def fix_variant_size(content: str) -> tuple[str, int]:
    """Fix variant size spacing"""
    count = 0

    # Pattern: variant="value"(sm|xs|lg|md)
    pattern = r'variant="([^"]+)"(sm|xs|lg|md)'

    def replace(match):
        nonlocal count
        count += 1
        return f'variant="{match.group(1)}" size="{match.group(2)}"'

    content = re.sub(pattern, replace, content)
    return content, count

def main():
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"[ERROR] Directory not found: {target_dir}")
        return

    files = list(target_dir.rglob('*.svelte'))
    files = [f for f in files if 'node_modules' not in str(f)]

    print("Fixing variant size spacing...")
    print(f"Target files: {len(files)}\n")

    total_files = 0
    total_fixes = 0

    for file_path in files:
        try:
            content = file_path.read_text(encoding='utf-8')
            new_content, count = fix_variant_size(content)

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
