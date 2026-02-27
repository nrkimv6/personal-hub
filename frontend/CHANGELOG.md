# Changelog

## [2.69.0] - 2026-02-27
### Added
- Dev Runner Logs 탭: Automation 페이지에 실행 이력 조회 + 로그 뷰어 + Listener 시스템 로그 서브탭 추가
- 백엔드 API: `/logs/history`, `/logs/full`, `/logs/system` 엔드포인트 추가
- `RunHistoryPanel.svelte`, `LogsTab.svelte` 신규 컴포넌트

## [2.68.0] - 2026-02-27
### Added
- 시스템 메모리 대시보드: `/system` 페이지에 `💾 메모리` 탭 추가
- `GET /api/v1/system/memory` 엔드포인트: RAM/PageFile/프로세스 Top 15 + 위험도 판정
- 위험도 배지: available < 2GB → 경고(amber), < 1GB → 위험(red)

## [2.67.1] - 2026-02-27
### Fixed
- LlmTab.svelte runes 모드 오류 수정: `$:` → `$effect`, `createForm` → `$state`

## [2.64.0] - 2026-02-26
### Added
- LLM 요청 시 Quota 정지 경고 표시: LLM 관리/글쓰기/수집/이벤트 페이지에서 provider quota pause 중일 때 토스트 경고 표시
- 백엔드 자동 요청 시 quota pause 경고 로그 출력 (universal_crawl_analyzer, instagram llm_classifier)
- quota warn 유닛 테스트 추가 (create_request, create_requests_batch 중복 방지)

## [2.62.0] - 2026-02-26
### Added
- 중복 감지 배치 처리 리팩토링: `_batch_delete_files` + `_merge_metadata` 헬퍼 함수
- Review API (`GET /duplicates/review`): N+1 쿼리 없이 그룹+멤버+자동선택 일괄 반환
- Auto-resolve API (`POST /duplicates/auto-resolve`): 자동선택 로직으로 일괄 해결
- DuplicatesTab 갤러리 뷰 모드: confidence 시각화 + 인라인 확장 + 일괄 확정
- removeAndFill(): 확정 후 자동 보충 + 스크롤 위치 유지

## [2.57.0] - 2026-02-25
### Added
- PlanViewer 컴포넌트: 마크다운 렌더링으로 plan 파일 내용 표시
- PlanListTab 상세 패널에 내용/메모 탭 전환 UI 추가
- devRunnerPlanApi에 content() 메서드 추가

## [2.50.0] - 2026-02-24
### Added
- PageHeader ������Ʈ ǥ��ȭ ? ��� classify �������� ���� ��� ����
### Fixed
- Vite HMR WebSocket ?�정??(timeout 60s, watch 최적??
- Service Worker dev 모드 ?�동 ?�제, prod ?�동 ?�록?�로 변�?
- SW skipWaiting/clients.claim ?�거 ???�연?�러???�데?�트 ?�략

## [0.11.1] - 2026-02-24
### Fixed
- ReviewTab 카테고리 ?�시 race condition ?�정 ??category_path 직접 ?�용, getCategoryDisplay() ?�턴 ?�용

## [0.11.0] - 2026-02-24
### Added
- LLM ?�리?? cwd 지??추�? ??Claude CLI가 wtools ?�렉?�리?�서 ?�행?�어 /plan ?�킬 ?�동 로드
- LLM ?�리?? PLAN_SYSTEM_PROMPT ?�드코딩 ?�거, promptPrefix + cliOptions 구조�?교체
- 백엔?? execute_claude??cwd ?�라미터 지??�??�용 경로 검�?추�?
- API ?�키�? LLMRequestCreate??cli_options ?�드 ?�출

## [0.10.0] - 2026-02-23
### Added
- Dev Runner: ?�스?�톱 2-grid ?�이?�웃 (LogViewer + Task History 좌우 분할, md 브레?�크?�인??
- Dev Runner: ?�스?�톱?�서 Task History ??�� ?�침, 모바?�에???��? ?��?

## [0.9.0] - 2026-02-23
### Added
- Dev Runner: Plans Card�?Task History ??���??�동 (Tasks/Plans ???�환)
- Dev Runner: 모바??< 640px)?�서 Control Panel 기본 ?�힘

## [0.6.0] - 2026-02-23
### Added
- 메모 별표(즐겨찾기) 기능: 별표 ?��? 버튼 (NoteCard, NoteDetailModal)
- 별표 ?�터 (NoteList ?�터 바에 즐겨찾기 ?��? 버튼 추�?)
- POST /api/notes/{id}/star ?�드?�인??
- GET /api/notes?starred=true|false ?�터 지??

## [0.3.0] - 2026-02-20
### Added
- 중복 ?��?지 ???�이지?�이??(?�전/?�음 버튼, ?�체 그룹 ???�시)
- ?�기 ?�른 중복 그룹: 가?????�일 ?�동 ?�택 + ?�정 ?�용 간소??UI
- ?�기 같�? 중복 그룹: ?�더 경로 강조 ?�시 (?�일�??�브?�스?�로)
- ?�이지 로드 ??pending 그룹 ?�동 ?�치�?�??�동?�택
