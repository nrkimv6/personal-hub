"""plan 헤더 조작 공통 유틸 — validate_done_preconditions / update_plan_headers

plan_service.py · plan_done_service.py · plan_worktree_helpers.py 에서 중복 구현된
두 함수를 단일 사본으로 통합한다. 외부 의존성 없음(re, pathlib 만 사용).
"""

import re
from pathlib import Path


def validate_done_preconditions(file_path: str, content: str) -> list:
    """done 처리 전 사전 검증. 실패 사유 리스트 반환 (빈 리스트 = 통과)"""
    errors = []
    # branch/worktree 필드 잔존 (worktree-owner 포함)
    if re.search(r">\s*(branch|worktree(-owner)?):", content[:2000]):
        errors.append("branch/worktree 필드 잔존 — /merge-test 먼저 실행 필요")
    # fix plan 판정
    name = Path(file_path).name
    is_fix = "_fix-" in name or "_fix_" in name
    if not is_fix:
        for line in content.split("\n")[:5]:
            if line.startswith("# fix") and len(line) > 5 and line[5] in (":", "-", " "):
                is_fix = True
                break
        if not is_fix and re.search(r">\s*유형:\s*fix", content[:1000]):
            is_fix = True
    if is_fix:
        has_pr = "Phase R" in content or "재발 경로 분석" in content
        if not has_pr:
            errors.append("fix plan Phase R 섹션 필수 — /implement에서 Phase R 먼저 실행")
        elif has_pr:
            m = re.search(r"### Phase R.*?(?=\n### |\Z)", content, re.DOTALL)
            if m:
                section = re.sub(r"```.*?```", "", m.group(0), flags=re.DOTALL)
                if "미방어" in section:
                    errors.append("Phase R에 미방어 경로 잔존 — 모든 경로 방어 완료 필요")
    return errors


def update_plan_headers(content: str, total: int) -> str:
    """상태→구현완료, 진행률→100%, [→ID]→[x] 치환, 푸터 갱신"""
    content = re.sub(r'^(>\s*상태:\s*).*$', r'\1구현완료', content, flags=re.MULTILINE)
    # branch/worktree 헤더 제거 — 잔존 시 /done 스킬 2.5단계에서 차단됨 (post-merge 이후이므로 삭제 안전)
    content = re.sub(r'^>\s*(branch|worktree(-owner)?):.*\n?', '', content, flags=re.MULTILINE)
    content = re.sub(
        r'^(>\s*진행률:\s*)[\d/\s()%]+$',
        f'> 진행률: {total}/{total} (100%)',
        content, flags=re.MULTILINE
    )
    # [→ID] 형태 → [x]
    content = re.sub(r'\[→[^\]]*\]', '[x]', content)
    # 푸터 갱신: *상태: ... | 진행률: ...*
    content = re.sub(
        r'\*상태:[^|*]+\|[^*]*진행률:[^*]*\*',
        f'*상태: 구현완료 | 진행률: {total}/{total} (100%)*',
        content
    )
    return content
