# Changelog

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
