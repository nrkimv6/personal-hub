#!/usr/bin/env python3
"""
Fix event modifiers on Button components
on:click|stopPropagation → on:click with e.stopPropagation()
"""

import re
from pathlib import Path

def fix_event_modifiers(content: str) -> tuple[str, int]:
    """Fix event modifiers"""
    count = 0

    # Pattern: on:click|stopPropagation={handler}
    # Replace with: on:click={(e) => { e.stopPropagation(); handler}}

    def replace_stopp(match):
        nonlocal count
        count += 1
        handler = match.group(1).strip()
        # If handler is already a function with params, wrap it
        if handler.startswith('('):
            # Already has params like (e) => ...
            # Just add stopPropagation call
            return f'on:click={{(e) => {{ e.stopPropagation(); {handler[handler.index("=>")+2:].strip()} }}}}'
        elif handler.startswith('()'):
            # No params arrow function
            return f'on:click={{(e) => {{ e.stopPropagation(); {handler[handler.index("=>")+2:].strip()} }}}}'
        else:
            # Simple handler like functionName or inline code
            return f'on:click={{(e) => {{ e.stopPropagation(); ({handler})(); }}}}'

    # Match on:click|stopPropagation={...}
    content = re.sub(
        r'on:click\|stopPropagation=\{([^}]+)\}',
        replace_stopp,
        content
    )

    return content, count

def main():
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"[ERROR] Directory not found: {target_dir}")
        return

    files = list(target_dir.rglob('*.svelte'))
    files = [f for f in files if 'node_modules' not in str(f)]

    print("Fixing event modifiers...")
    print(f"Target files: {len(files)}\n")

    total_files = 0
    total_fixes = 0

    for file_path in files:
        try:
            content = file_path.read_text(encoding='utf-8')
            new_content, count = fix_event_modifiers(content)

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
