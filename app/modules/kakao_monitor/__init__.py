"""
카카오톡 채팅방 모니터링 모듈.

동작 계약:
1. 감시 설정 로드
2. OCR 기반 메시지 감시
3. 키워드 매칭
4. direct collect(collect) 또는 알림 전용(alert_only) 분기
5. DB 저장 + Redis 알림 발행

운영 점검 순서:
1. 카카오톡 프로세스 실행 여부
2. 워커 등록 상태(`/api/v1/kakao-monitor/status.worker_registered`)
3. 루프 진행 상태(`last_loop_at`, `last_error`)
4. OCR/수집/알림 단계 로그(`[KAKAO_BOOT|CAPTURE|OCR|COLLECT]`)
"""
