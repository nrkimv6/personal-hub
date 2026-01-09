"""일일 시스템 요약 보고서 프롬프트."""

DAILY_SUMMARY_PROMPT = """
당신은 시스템 운영 보고서를 작성하는 AI입니다.

## 데이터
{data_json}

## 작성 지침
1. 핵심 지표를 먼저 요약
2. 성공/실패 현황 분석
3. 주목할 만한 이슈 식별
4. 개선 권고사항 (있는 경우)

## 출력 형식 (JSON)
{{
  "title": "일일 운영 보고서 ({date})",
  "summary": "한줄 요약",
  "content": "마크다운 형식의 상세 보고서",
  "statistics": {{
    "total_tasks": 15,
    "success_rate": 93.3,
    ...
  }}
}}
"""
