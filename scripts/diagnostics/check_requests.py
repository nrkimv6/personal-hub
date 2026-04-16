#!/usr/bin/env python3
"""레거시 Instagram crawl request 진단 스크립트.

`instagram_crawl_requests`는 2025-12-31 정리로 삭제되었고 현재 운영 경로는
`crawl_requests` / request service 기반으로 대체되었다.

이 스크립트는 더 이상 직접 진단을 수행하지 않고, 레거시 도구임을 명시한다.
"""


def main() -> int:
    print("DEPRECATED: scripts/diagnostics/check_requests.py")
    print("  - 레거시 테이블 instagram_crawl_requests 는 운영 스키마에서 제거되었습니다.")
    print("  - 현재 요청 상태는 crawl_requests 및 Instagram request service 경로를 사용해 확인하세요.")
    print("  - 필요 시 /api/v1/instagram/requests 또는 app/modules/instagram/services/request_service.py 를 기준으로 새 진단 스크립트를 작성해야 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
