"""
log_viewer — logs.ps1 Python 이식 모듈

logs.ps1의 핵심 로직(로그 파일 탐색, stale 판정, plan-runner 조회)을
Python으로 이식하여 pytest 단위 테스트가 가능한 구조로 제공한다.

서브모듈:
    finder  — 로그 파일 탐색/선택 로직
    stale   — stale 판정 로직
    runner  — plan-runner Redis 조회
    config  — 로그 소스 설정 (패턴, 색상, tail 줄수)
    cli     — CLI 진입점 (static 모드 출력)
"""
