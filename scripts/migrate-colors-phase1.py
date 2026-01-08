#!/usr/bin/env python3
"""
Phase 1: 안전한 1:1 색상 클래스 자동 변환
그레이스케일, 테두리, 호버 상태 등 확실한 매핑만 처리
"""

import os
import re
from pathlib import Path

# 변환 매핑 (순서 중요 - 긴 패턴부터)
MAPPINGS = [
    # Borders (먼저 처리)
    ('border-gray-300', 'border-border'),
    ('border-gray-200', 'border-border'),
    ('border-gray-100', 'border-border'),
    ('divide-gray-200', 'divide-border'),
    ('divide-gray-100', 'divide-border'),

    # Hover states - background
    ('hover:bg-gray-200', 'hover:bg-secondary'),
    ('hover:bg-gray-100', 'hover:bg-muted'),
    ('hover:bg-gray-50', 'hover:bg-muted'),

    # Hover states - text
    ('hover:text-gray-900', 'hover:text-foreground'),
    ('hover:text-gray-700', 'hover:text-foreground'),
    ('hover:text-gray-600', 'hover:text-muted-foreground'),

    # Gray text - foreground
    ('text-gray-900', 'text-foreground'),
    ('text-gray-800', 'text-foreground'),
    ('text-gray-700', 'text-foreground'),

    # Gray text - muted
    ('text-gray-600', 'text-muted-foreground'),
    ('text-gray-500', 'text-muted-foreground'),
    ('text-gray-400', 'text-muted-foreground'),

    # Gray background
    ('bg-gray-200', 'bg-secondary'),
    ('bg-gray-100', 'bg-muted'),
    ('bg-gray-50', 'bg-background'),

    # White backgrounds with border (특정 패턴)
    ('bg-white border', 'bg-card border'),
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
        print(f"  ⚠️  Error processing {file_path}: {e}")
        return 0

def main():
    # 대상 디렉토리
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"❌ 디렉토리를 찾을 수 없습니다: {target_dir}")
        return

    # 대상 파일 수집
    files = []
    for ext in ['*.svelte', '*.ts']:
        files.extend(target_dir.rglob(ext))

    # node_modules, test 파일 제외
    files = [f for f in files if 'node_modules' not in str(f) and '.test.' not in f.name]

    print("Phase 1: Safe color class migration started...")
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

    print(f"\nPhase 1 completed!")
    print(f"  - Modified files: {total_files}")
    print(f"  - Total replacements: {total_replacements}")
    print(f"\nNext: Phase 2 (semantic color manual conversion)")

if __name__ == '__main__':
    main()
