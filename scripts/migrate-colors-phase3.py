#!/usr/bin/env python3
"""
Phase 3: Legacy CSS to Components
.btn-* → <Button>, .badge-* → <Badge>
"""

import os
import re
from pathlib import Path
from typing import Set

def has_component_import(content: str, component: str) -> bool:
    """컴포넌트가 이미 import 되어 있는지 확인"""
    patterns = [
        rf"import\s+\{{[^}}]*\b{component}\b[^}}]*\}}\s+from\s+['\"].*?/components/ui['\"]",
        rf"import\s+{component}\s+from\s+['\"].*?/components/ui/{component}\.svelte['\"]"
    ]
    for pattern in patterns:
        if re.search(pattern, content):
            return True
    return False

def add_component_import(content: str, components: Set[str]) -> str:
    """컴포넌트 import 추가"""
    if not components:
        return content

    # 기존 ui import 찾기
    ui_import_pattern = r"import\s+\{([^}]+)\}\s+from\s+['\"](\$lib/components/ui)['\"]"
    match = re.search(ui_import_pattern, content)

    if match:
        # 기존 import에 추가
        existing = match.group(1).strip()
        existing_components = {c.strip() for c in existing.split(',')}
        all_components = existing_components | components
        new_import = f"import {{ {', '.join(sorted(all_components))} }} from '{match.group(2)}'"
        content = content.replace(match.group(0), new_import)
    else:
        # 새 import 추가 (script 태그 안에)
        script_pattern = r'(<script[^>]*>)'
        if re.search(script_pattern, content):
            new_import = f"import {{ {', '.join(sorted(components))} }} from '$lib/components/ui';\n"
            content = re.sub(script_pattern, rf'\1\n\t{new_import}', content, count=1)

    return content

def convert_simple_buttons(content: str) -> tuple[str, int]:
    """간단한 버튼 변환 (동적 variant 제외)"""
    count = 0

    # 패턴: <button class="btn btn-{variant} [btn-{size}]" {attrs}>
    patterns = [
        # onclick + class
        (
            r'<button\s+onclick=\{([^}]+)\}\s+class="btn\s+btn-(primary|secondary|success|error|warning|info)(?:\s+btn-(sm|xs|lg))?(?:\s+([^"]*))?"([^>]*)>',
            r'<Button variant="\2"\3 on:click={\1}\5>'
        ),
        # class + onclick
        (
            r'<button\s+class="btn\s+btn-(primary|secondary|success|error|warning|info)(?:\s+btn-(sm|xs|lg))?(?:\s+([^"]*))?"([^>]*)\s+onclick=\{([^}]+)\}>',
            r'<Button variant="\1"\2 on:click={\5}\4>'
        ),
        # class + on:click
        (
            r'<button\s+class="btn\s+btn-(primary|secondary|success|error|warning|info)(?:\s+btn-(sm|xs|lg))?(?:\s+([^"]*))?"([^>]*)\s+on:click=\{([^}]+)\}>',
            r'<Button variant="\1"\2 on:click={\5}\4>'
        ),
        # onclick만 (class 먼저)
        (
            r'<button\s+onclick=\{([^}]+)\}\s+class="btn\s+btn-(primary|secondary|success|error|warning|info)(?:\s+btn-(sm|xs|lg))?"([^>]*)>',
            r'<Button variant="\2"\3 on:click={\1}\4>'
        ),
        # 기본 (속성 없음)
        (
            r'<button\s+class="btn\s+btn-(primary|secondary|success|error|warning|info)(?:\s+btn-(sm|xs|lg))?"([^>]*)>',
            r'<Button variant="\1"\2\3>'
        ),
    ]

    for pattern, replacement in patterns:
        new_content = re.sub(pattern, replacement, content)
        if new_content != content:
            count += len(re.findall(pattern, content))
            content = new_content

    # 사이즈 속성 정리
    content = re.sub(r'variant="(\w+)"\s*btn-(sm|xs|lg)', r'variant="\1" size="\2"', content)
    content = re.sub(r'variant="(\w+)"\s+size="(\w+)"\s+([^>]*)\s+size="\2"', r'variant="\1" size="\2" \3', content)

    # 닫는 태그
    content = re.sub(r'</button>', '</Button>', content)

    return content, count

def convert_simple_badges(content: str) -> tuple[str, int]:
    """간단한 배지 변환"""
    count = 0

    # 패턴: <span class="badge badge-{variant} [extra-classes]">
    pattern = r'<span\s+class="badge\s+badge-(success|error|warning|info|gray)(?:\s+([^"]*))?">'
    matches = re.findall(pattern, content)
    count = len(matches)

    def replace_badge(match):
        variant = match.group(1)
        extra = match.group(2) or ''
        # gray → secondary
        if variant == 'gray':
            variant = 'secondary'

        if extra:
            return f'<Badge variant="{variant}" class="{extra.strip()}">'
        return f'<Badge variant="{variant}">'

    content = re.sub(pattern, replace_badge, content)

    # 닫는 태그 (badge로 시작하는 span만)
    if count > 0:
        # 더 정확한 매칭을 위해 Badge 태그 수만큼만 교체
        span_close_count = 0
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if '<Badge' in line and '</span>' in line:
                lines[i] = line.replace('</span>', '</Badge>')
            elif '<Badge' in line:
                # 다음 줄에서 </span> 찾기
                for j in range(i + 1, min(i + 10, len(lines))):
                    if '</span>' in lines[j]:
                        lines[j] = lines[j].replace('</span>', '</Badge>', 1)
                        break
        content = '\n'.join(lines)

    return content, count

def find_dynamic_cases(content: str, file_path: Path) -> list[str]:
    """수동 변환 필요한 동적 케이스 찾기"""
    issues = []

    # 동적 variant
    if re.search(r'btn-\{', content):
        issues.append("Dynamic button variant detected (e.g., btn-{condition ? 'primary' : 'secondary'})")

    # 조건부 클래스
    if re.search(r'\?\s*["\']btn-', content):
        issues.append("Conditional button class detected")

    if re.search(r'\?\s*["\']badge-', content):
        issues.append("Conditional badge class detected")

    return issues

def process_file(file_path: Path) -> dict:
    """파일 처리"""
    try:
        content = file_path.read_text(encoding='utf-8')
        original = content

        components_needed: Set[str] = set()
        button_count = 0
        badge_count = 0

        # 버튼 변환
        if 'btn btn-' in content:
            content, button_count = convert_simple_buttons(content)
            if button_count > 0:
                components_needed.add('Button')

        # 배지 변환
        if 'badge badge-' in content:
            content, badge_count = convert_simple_badges(content)
            if badge_count > 0:
                components_needed.add('Badge')

        # Import 추가
        if components_needed:
            content = add_component_import(content, components_needed)

        # 수동 변환 필요한 케이스
        issues = find_dynamic_cases(content, file_path)

        # 파일 저장
        if content != original:
            file_path.write_text(content, encoding='utf-8')
            return {
                'status': 'modified',
                'button_count': button_count,
                'badge_count': badge_count,
                'issues': issues
            }

        return {'status': 'skipped'}

    except Exception as e:
        return {'status': 'error', 'error': str(e)}

def main():
    target_dir = Path(__file__).parent.parent / 'frontend' / 'src'

    if not target_dir.exists():
        print(f"[ERROR] Directory not found: {target_dir}")
        return

    # 대상 파일
    files = list(target_dir.rglob('*.svelte'))
    files = [f for f in files if 'node_modules' not in str(f)]

    print("Phase 3: Legacy CSS to Components migration started...")
    print(f"Target files: {len(files)}\n")

    total_files = 0
    total_buttons = 0
    total_badges = 0
    manual_review = []

    for file_path in files:
        result = process_file(file_path)

        if result['status'] == 'modified':
            total_files += 1
            btn = result.get('button_count', 0)
            bdg = result.get('badge_count', 0)
            total_buttons += btn
            total_badges += bdg

            relative = file_path.relative_to(target_dir)
            changes = []
            if btn > 0:
                changes.append(f"{btn} buttons")
            if bdg > 0:
                changes.append(f"{bdg} badges")

            print(f"  [OK] {relative} ({', '.join(changes)})")

            if result.get('issues'):
                manual_review.append((relative, result['issues']))

        elif result['status'] == 'error':
            print(f"  [ERROR] {file_path.name}: {result['error']}")

    print(f"\nPhase 3 completed!")
    print(f"  - Modified files: {total_files}")
    print(f"  - Buttons converted: {total_buttons}")
    print(f"  - Badges converted: {total_badges}")

    if manual_review:
        print(f"\n[WARN] Manual review needed for {len(manual_review)} files:")
        for file, issues in manual_review:
            print(f"  - {file}")
            for issue in issues:
                print(f"    * {issue}")

    print("\nNext: Phase 4 (validation)")

if __name__ == '__main__':
    main()
