"""
네이버 예약 URL 빌더 유틸리티
"""


def build_naver_booking_url(
    business_type_id: int,
    business_id: str,
    biz_item_id: str,
    date: str
) -> str:
    """
    네이버 예약 URL 생성

    Args:
        business_type_id: 네이버 비즈니스 타입 ID
        business_id: 네이버 비즈니스 ID
        biz_item_id: 네이버 아이템 ID
        date: 예약 날짜 (YYYY-MM-DD)

    Returns:
        완전한 네이버 예약 URL
    """
    # startDateTime 형식 사용 (00:00:00+09:00)
    start_datetime = f"{date}T00%3A00%3A00%2B09%3A00"
    return (
        f"https://booking.naver.com/booking/{business_type_id}"
        f"/bizes/{business_id}/items/{biz_item_id}"
        f"?startDateTime={start_datetime}"
    )
