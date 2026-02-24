# Changelog

## [0.11.1] - 2026-02-24
### Fixed
- ReviewTab 카테고리 표시 race condition 수정 — category_path 직접 사용, getCategoryDisplay() 패턴 적용

## [0.11.0] - 2026-02-24
### Added
- LLM 프리셋: cwd 지원 추가 — Claude CLI가 wtools 디렉토리에서 실행되어 /plan 스킬 자동 로드
- LLM 프리셋: PLAN_SYSTEM_PROMPT 하드코딩 제거, promptPrefix + cliOptions 구조로 교체
- 백엔드: execute_claude에 cwd 파라미터 지원 및 허용 경로 검증 추가
- API 스키마: LLMRequestCreate에 cli_options 필드 노출

## [0.10.0] - 2026-02-23
### Added
- Dev Runner: 데스크톱 2-grid 레이아웃 (LogViewer + Task History 좌우 분할, md 브레이크포인트)
- Dev Runner: 데스크톱에서 Task History 항상 펼침, 모바일에서 토글 유지

## [0.9.0] - 2026-02-23
### Added
- Dev Runner: Plans Card를 Task History 탭으로 이동 (Tasks/Plans 탭 전환)
- Dev Runner: 모바일(< 640px)에서 Control Panel 기본 접힘

## [0.6.0] - 2026-02-23
### Added
- 메모 별표(즐겨찾기) 기능: 별표 토글 버튼 (NoteCard, NoteDetailModal)
- 별표 필터 (NoteList 필터 바에 즐겨찾기 토글 버튼 추가)
- POST /api/notes/{id}/star 엔드포인트
- GET /api/notes?starred=true|false 필터 지원

## [0.3.0] - 2026-02-20
### Added
- 중복 이미지 탭 페이지네이션 (이전/다음 버튼, 전체 그룹 수 표시)
- 크기 다른 중복 그룹: 가장 큰 파일 자동 선택 + 확정 전용 간소화 UI
- 크기 같은 중복 그룹: 폴더 경로 강조 표시 (파일명 서브텍스트로)
- 페이지 로드 시 pending 그룹 자동 펼치기 및 자동선택
