"""
DB 스키마와 서버 동작에 맞춘 모니터링 대상 URL 목록을 정의합니다.
각 항목은 모니터링 대상에 필요한 필드를 포함합니다:
- url: 모니터링할 전체 URL
- base_url: 기본 URL 부분
- label: 모니터링 대상의 식별 레이블
- date: 모니터링 타겟 날짜 (ISO 형식)
- times: 모니터링 시간대 목록 (JSON 배열 형식으로 저장)
- category: 모니터링 카테고리 분류
- service_type: 서비스 유형 분류
- is_active: 활성화 여부 (기본값: True)
- interval: 모니터링 간격 (초, 선택적)
- custom_interval: 사용자 정의 간격 여부 (기본값: False)
"""

# 모니터링할 URL 목록 정의
urls = [
    {
        "url": "https://booking.naver.com/booking/12/bizes/1249231/items/6620152?startDateTime=2025-04-17T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1249231",
        "label": "나전칠기_0417",
        "date": "2025-04-17T00:00:00+09:00",
        "times": ["00:00"],
        "category": "워크샵",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1249231/items/6620152?startDateTime=2025-04-24T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1249231",
        "label": "나전칠기_0424",
        "date": "2025-04-24T00:00:00+09:00",
        "times": ["00:00"],
        "category": "워크샵",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1249231/items/6633589?startDateTime=2025-04-26T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1249231",
        "label": "요가_0426",
        "date": "2025-04-26T00:00:00+09:00",
        "times": ["00:00"],
        "category": "요가",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1182237/items/6604799?startDateTime=2025-04-19T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1182237",
        "label": "케라스타즈_0419",
        "date": "2025-04-19T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1182237/items/6604799?startDateTime=2025-04-20T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1182237",
        "label": "케라스타즈_0420",
        "date": "2025-04-20T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1182237/items/6604799?startDateTime=2025-04-18T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1182237",
        "label": "케라스타즈_0418",
        "date": "2025-04-18T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1182237/items/6604799?startDateTime=2025-04-25T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1182237",
        "label": "케라스타즈_0425",
        "date": "2025-04-25T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1182237/items/6604799?startDateTime=2025-04-26T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1182237",
        "label": "케라스타즈_0426",
        "date": "2025-04-26T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1182237/items/6604799?startDateTime=2025-04-27T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1182237",
        "label": "케라스타즈_0427",
        "date": "2025-04-27T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1357646/items/6616979?startDateTime=2025-04-18T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1357646",
        "label": "삐아_0418",
        "date": "2025-04-18T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/13/bizes/1388009/items/6659924?startDate=2025-04-18T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/13/bizes/1388009",
        "label": "파파레서피_0418",
        "date": "2025-04-18T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/13/bizes/1388009/items/6659924?startDate=2025-04-19T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/13/bizes/1388009",
        "label": "파파레서피_0419",
        "date": "2025-04-19T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/13/bizes/1388009/items/6659924?startDate=2025-04-20T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/13/bizes/1388009",
        "label": "파파레서피_0420",
        "date": "2025-04-20T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1386180/items/6654172?from=myp&startDateTime=2025-04-18T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1386180",
        "label": "바닐라코_0418",
        "date": "2025-04-18T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1386180/items/6654172?from=myp&startDateTime=2025-04-19T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1386180",
        "label": "바닐라코_0419",
        "date": "2025-04-19T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    },
    {
        "url": "https://booking.naver.com/booking/12/bizes/1386180/items/6654172?from=myp&startDateTime=2025-04-20T00%3A00%3A00%2B09%3A00",
        "base_url": "https://booking.naver.com/booking/12/bizes/1386180",
        "label": "바닐라코_0420",
        "date": "2025-04-20T00:00:00+09:00",
        "times": ["00:00"],
        "category": "뷰티",
        "service_type": "네이버예약"
    }
] 