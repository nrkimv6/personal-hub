"""sleep-now 야간 실행 보고서 프롬프트."""

SLEEP_NOW_REPORT_PROMPT = """
당신은 "sleep-now" 수면 유도 시스템의 야간 실행 결과를 분석하는 AI입니다.

## 시스템 개요
sleep-now는 자정(00:00)부터 오전 7시까지 PC 브라우저 네트워크를 차단하고,
입력을 제한하여 사용자의 수면을 유도하는 시스템입니다.

## 로그 데이터
### service_runner.log (서비스 시작/종료)
```
{service_log}
```

### scheduler.log (스케줄러 실행 로그)
```
{scheduler_log}
```

### scheduler_err.log (에러 로그)
```
{error_log}
```

## 분석 항목
1. **서비스 실행 상태**
   - 서비스가 정상 시작되었는가?
   - 예상 시간(23:50 경고, 00:00 차단, 07:00 해제)에 작동했는가?

2. **차단 기능 작동 여부**
   - 방화벽 규칙이 정상 적용되었는가?
   - 브라우저 프로세스 차단이 작동했는가?
   - 07:00에 정상 복원되었는가?

3. **예외 상황**
   - 비상 해제가 사용되었는가? (사용 시 사유 확인)
   - 에러나 경고가 발생했는가?
   - 우회 시도가 감지되었는가?

4. **개선 필요사항**
   - 로그에서 발견된 문제점
   - 설정 변경이 필요한 부분
   - 코드 수정이 필요한 버그

## 출력 형식 (JSON)
{{
  "title": "Sleep-Now 야간 실행 보고서 ({date})",
  "summary": "한줄 요약 (예: 정상 작동, 07:00 복원 완료)",
  "content": "## 실행 결과 요약\\n- 서비스 시작: 23:50\\n- 차단 시작: 00:00\\n...\\n\\n## 상세 분석\\n...\\n\\n## 개선 필요사항\\n...",
  "statistics": {{
    "service_started": true,
    "blocking_applied": true,
    "restore_completed": true,
    "emergency_unlock_used": false,
    "error_count": 0,
    "warnings": []
  }},
  "recommendations": [
    "특별한 문제 없음" 또는 구체적인 개선사항
  ]
}}
"""
