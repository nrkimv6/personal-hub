#!/usr/bin/env python3
"""
Fix Button tag case mismatches in specific files
"""

import re
from pathlib import Path
import sys

def fix_button_case_in_file(file_path: Path) -> int:
    """Fix all </button> to </Button> where there's a corresponding <Button>"""
    content = file_path.read_text(encoding='utf-8')
    original = content

    # Replace all </button> with </Button>
    # This is safe because we only have Svelte Button components, not regular buttons
    content = re.sub(r'</button>', '</Button>', content, flags=re.IGNORECASE)

    if content != original:
        file_path.write_text(content, encoding='utf-8')
        count = original.count('</button>') + original.count('</BUTTON>')
        return count

    return 0

def main():
    if len(sys.argv) > 1:
        file_path = Path(sys.argv[1])
    else:
        # Default to collect/+page.svelte
        file_path = Path(__file__).parent.parent / 'frontend' / 'src' / 'routes' / 'collect' / '+page.svelte'

    if not file_path.exists():
        print(f"[ERROR] File not found: {file_path}")
        return

    count = fix_button_case_in_file(file_path)
    if count > 0:
        print(f"[OK] Fixed {count} button tags in {file_path.name}")
    else:
        print(f"[SKIP] No changes needed in {file_path.name}")

if __name__ == '__main__':
    main()
