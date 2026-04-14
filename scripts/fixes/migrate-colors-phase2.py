#!/usr/bin/env python3
"""
Phase 2: 시맨틱 색상 변환
Blue(Primary), Green(Success), Red(Error), Yellow/Orange(Warning) 등
"""

import os
import re
from pathlib import Path

# 변환 매핑 (순서 중요 - 긴 패턴부터)
MAPPINGS = [
    # Blue → Primary
    ('hover:text-blue-800', 'hover:text-primary-hover'),
    ('hover:text-blue-700', 'hover:text-primary-hover'),
    ('hover:text-blue-600', 'hover:text-primary'),
    ('hover:bg-blue-700', 'hover:bg-primary-hover'),
    ('hover:bg-blue-600', 'hover:bg-primary-hover'),
    ('hover:bg-blue-500', 'hover:bg-primary-hover'),
    ('focus:ring-blue-500', 'focus:ring-ring'),
    ('focus:border-blue-500', 'focus:border-ring'),
    ('text-blue-800', 'text-primary'),
    ('text-blue-700', 'text-primary'),
    ('text-blue-600', 'text-primary'),
    ('text-blue-500', 'text-primary'),
    ('bg-blue-600', 'bg-primary'),
    ('bg-blue-500', 'bg-primary'),
    ('bg-blue-100', 'bg-primary-light'),
    ('bg-blue-50', 'bg-primary-light'),

    # Green → Success
    ('hover:bg-green-700', 'hover:bg-success/90'),
    ('hover:bg-green-600', 'hover:bg-success/90'),
    ('hover:bg-green-500', 'hover:bg-success/90'),
    ('hover:text-green-700', 'hover:text-success'),
    ('hover:text-green-600', 'hover:text-success'),
    ('text-green-800', 'text-success'),
    ('text-green-700', 'text-success'),
    ('text-green-600', 'text-success'),
    ('text-green-500', 'text-success'),
    ('bg-green-600', 'bg-success'),
    ('bg-green-500', 'bg-success'),
    ('bg-green-100', 'bg-success-light'),
    ('bg-green-50', 'bg-success-light'),

    # Red → Error
    ('hover:bg-red-700', 'hover:bg-error/90'),
    ('hover:bg-red-600', 'hover:bg-error/90'),
    ('hover:bg-red-500', 'hover:bg-error/90'),
    ('hover:text-red-700', 'hover:text-error'),
    ('hover:text-red-600', 'hover:text-error'),
    ('text-red-800', 'text-error'),
    ('text-red-700', 'text-error'),
    ('text-red-600', 'text-error'),
    ('text-red-500', 'text-error'),
    ('bg-red-600', 'bg-error'),
    ('bg-red-500', 'bg-error'),
    ('bg-red-100', 'bg-error-light'),
    ('bg-red-50', 'bg-error-light'),

    # Yellow/Orange → Warning
    ('hover:bg-yellow-600', 'hover:bg-warning/90'),
    ('hover:bg-yellow-500', 'hover:bg-warning/90'),
    ('hover:bg-orange-600', 'hover:bg-warning/90'),
    ('hover:bg-orange-500', 'hover:bg-warning/90'),
    ('hover:text-yellow-700', 'hover:text-warning'),
    ('hover:text-orange-700', 'hover:text-warning'),
    ('text-yellow-800', 'text-warning-foreground'),
    ('text-yellow-700', 'text-warning-foreground'),
    ('text-yellow-600', 'text-warning-foreground'),
    ('text-yellow-500', 'text-warning'),
    ('text-orange-800', 'text-warning'),
    ('text-orange-700', 'text-warning'),
    ('text-orange-600', 'text-warning'),
    ('text-orange-500', 'text-warning'),
    ('bg-yellow-500', 'bg-warning'),
    ('bg-yellow-400', 'bg-warning'),
    ('bg-yellow-100', 'bg-warning-light'),
    ('bg-yellow-50', 'bg-warning-light'),
    ('bg-orange-500', 'bg-warning'),
    ('bg-orange-400', 'bg-warning'),
    ('bg-orange-100', 'bg-warning-light'),
    ('bg-orange-50', 'bg-warning-light'),
    ('bg-amber-600', 'bg-warning'),
    ('bg-amber-100', 'bg-warning-light'),
    ('bg-amber-50', 'bg-warning-light'),
    ('text-amber-600', 'text-warning'),

    # Purple → Purple
    ('bg-purple-100', 'bg-purple-light'),
    ('bg-purple-50', 'bg-purple-light'),
    ('text-purple-700', 'text-purple'),
    ('text-purple-600', 'text-purple'),
    ('bg-violet-100', 'bg-purple-light'),
    ('bg-violet-50', 'bg-purple-light'),
    ('text-violet-800', 'text-purple'),
    ('text-violet-700', 'text-purple'),

    # Pink → Pink
    ('bg-pink-100', 'bg-pink-light'),
    ('bg-pink-50', 'bg-pink-light'),
    ('text-pink-800', 'text-pink'),
    ('text-pink-700', 'text-pink'),
    ('text-pink-600', 'text-pink'),

    # Teal (후기/특수용도) → Success
    ('bg-teal-100', 'bg-success-light'),
    ('text-teal-700', 'text-success'),

    # Indigo (특수) → Primary
    ('bg-indigo-100', 'bg-primary-light'),
    ('text-indigo-600', 'text-primary'),
]

def process_file(file_path: Path) -> int:
    """파일 처리 및 변환 횟수 반환"""
    try:
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        replacements = 0

        for old, new in MAPPINGS:
            if old in content:
                count = content.count(old)
                content = content.replace(old, new)
                replacements += count

        if content != original_content:
            file_path.write_text(content, encoding='utf-8')
            return replacements

        return 0

    except Exception as e:
        print(f"  [WARN] Error processing {file_path}: {e}")
        return 0

def main():
    # 대상 디렉토리
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"[ERROR] Directory not found: {target_dir}")
        return

    # 대상 파일 수집
    files = []
    for ext in ['*.svelte', '*.ts']:
        files.extend(target_dir.rglob(ext))

    # node_modules, test 파일 제외
    files = [f for f in files if 'node_modules' not in str(f) and '.test.' not in f.name]

    print("Phase 2: Semantic color migration started...")
    print(f"Target files: {len(files)}\n")

    total_files = 0
    total_replacements = 0

    for file_path in files:
        replacements = process_file(file_path)

        if replacements > 0:
            total_files += 1
            total_replacements += replacements
            relative_path = file_path.relative_to(target_dir)
            print(f"  [OK] {relative_path} ({replacements} replacements)")

    print(f"\nPhase 2 completed!")
    print(f"  - Modified files: {total_files}")
    print(f"  - Total replacements: {total_replacements}")
    print(f"\nNext: Phase 3 (legacy CSS to components)")

if __name__ == '__main__':
    main()
