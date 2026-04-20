# Frontend Guide

## Expo Surface Boundary

- public booth map: `src/routes/expo/coffee-expo-2026/+page.svelte`
- admin author helper / operations workspace: `src/routes/expo/coffee-expo-2026/author/+page.svelte`, `src/routes/events/+page.svelte?tab=expo`
- publish surface: monitor-page가 아니라 `admin-tools`

expo admin UI는 browser local draft와 export 흐름만 담당합니다. publish 여부 판단, release 상태 추적, 공개 반영은 admin-tools에서 진행합니다.

## Development

- API client 진입점: `src/lib/api/`
- 공통 타입 SoT: `src/lib/types.ts`
- expo 운영 계약 문서: `../docs/dev-guide/expo-data-flow.md`
