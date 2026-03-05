"""Git 일괄 정리 자동화를 위한 Claude 프롬프트 템플릿."""
from typing import List


def render_cleanup_prompt(repo_path: str, date: str, patterns: List[str]) -> str:
    """
    git 레포지토리 일괄 정리를 위한 프롬프트를 렌더링합니다.
    
    Args:
        repo_path: 레포지토리 절대 경로
        date: 오늘 날짜 (YYYY-MM-DD)
        patterns: 임시 파일 매칭 패턴 리스트
        
    Returns:
        Claude에게 전달할 프롬프트 문자열
    """
    patterns_str = ", ".join([f'"{p}"' for p in patterns])
    
    return f'''당신은 git 정리 전문가입니다. 아래 절차를 순서대로 실행하세요.

레포지토리 경로: {repo_path}
오늘 날짜: {date}
임시 파일 패턴: [{patterns_str}]

## 절차
1. `git -C "{repo_path}" status --porcelain` 실행 → 변경 파일 확인
2. untracked 중 패턴 매칭 파일 → `{repo_path}/archive/{date}/` 로 이동
3. 나머지 변경 파일 diff 확인: `git -C "{repo_path}" diff HEAD`
4. diff 기반 논리 그룹 분류 + Conventional Commits 메시지 작성
5. 그룹별 순서대로: git add {{파일}} → git commit -m "{{메시지}}"
6. 완료 후 마지막 줄에 JSON만 출력 (코드블럭 없이):
   {{"success": true, "moved": [...], "commits": [{{"files": [...], "message": "..."}}]}}

변경사항 없으면: {{"success": true, "moved": [], "commits": []}}'''
