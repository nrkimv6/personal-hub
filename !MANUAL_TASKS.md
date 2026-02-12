# Monitor Page - 수동 작업 목록

> Claude가 자동으로 처리할 수 없는 작업들 (브라우저 테스트, 배포, 수동 검증 등)

## Auto-Next API 경로 인코딩 오류 수정 - 로컬 테스트 (2026-02-13)

> 관련 계획: [todo](docs/plan/2026-02-12_auto-next-path-encoding-fix_todo.md)

### 테스트 항목

**1. 로컬 환경 실행**
- [ ] Frontend: `npm run dev` 실행 (http://localhost:5173)
- [ ] Backend: API 서버 실행 (http://localhost:6101)

**2. 기능 테스트**
- [ ] Auto Next 탭 접속
- [ ] Windows 경로가 포함된 Plan 선택 (예: `D:\work\project\service\wtools\...`)
- [ ] 브라우저 개발자 도구 → 네트워크 탭 확인
- [ ] `/api/v1/auto-next/plans/{encoded}/items` 요청이 200 응답 확인
- [ ] Plan Items가 UI에 정상 표시되는지 확인

**3. 회귀 테스트**
- [ ] 상대 경로로 된 Plan도 정상 작동하는지 확인
- [ ] Linux 스타일 경로(`/home/user/...`)도 정상 작동하는지 확인
- [ ] Chrome에서 테스트
- [ ] Firefox에서 테스트 (선택)
- [ ] Safari에서 테스트 (선택)

### 예상 결과

**Before (에러):**
```
GET /api/v1/auto-next/plans/RDpcd29ya1xwcm9qZWN0XHNlcnZpY2Vcd3Rvb2xzXC4uLg/items
Response: 400 Bad Request
{"detail":"Invalid encoded path"}
```

**After (정상):**
```
GET /api/v1/auto-next/plans/RDpcd29ya1xwcm9qZWN0XHNlcnZpY2Vcd3Rvb2xzXC4uLg/items
Response: 200 OK
{
  "path": "D:\\work\\project\\service\\wtools\\...",
  "filename": "plan.md",
  "status": "구현중",
  "phases": [...],
  "progress": {"done": 6, "total": 8, "percent": 75}
}
```

### 테스트 완료 후

테스트가 성공하면 `/done` 스킬을 호출하여 완료 처리합니다.
