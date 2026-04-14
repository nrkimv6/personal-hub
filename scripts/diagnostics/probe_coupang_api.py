"""
쿠팡 여행상품 API 비로그인 접근 가능 여부 검증 스크립트.

로그인 쿠키 없이 vendor-items API가 200을 반환하는지 확인합니다.
결과에 따라 service_account 필요 여부를 결정합니다.

사용법:
    python scripts/diagnostics/probe_coupang_api.py
"""
import asyncio
import json
import sys


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[ERROR] playwright가 설치되어 있지 않습니다. pip install playwright")
        sys.exit(1)

    # 테스트용 상품 — 실제 존재하는 쿠팡 여행상품 ID
    product_id = "10000011218760"
    vendor_item_package_id = "999999999"  # 임의값, API 호출 여부 확인용
    test_date = "2026-05-01"

    js_code = """
    async (args) => {
        const response = await fetch(
            'https://trip.coupang.com/tp/gateway/api/v1/vendor-items',
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({
                    vendorItemPackageId: args.vendorItemPackageId,
                    productType: 'TICKET',
                    selectDate: args.selectDate
                })
            }
        );
        return { status: response.status, ok: response.ok };
    }
    """

    print(f"[PROBE] 쿠팡 API 비로그인 접근 검증 시작 (product_id={product_id})")
    print("[PROBE] 빈 프로필(쿠키 없음)으로 테스트합니다.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()  # 쿠키 없는 빈 컨텍스트
        page = await context.new_page()

        print(f"[PROBE] 상품 페이지 이동: https://trip.coupang.com/tp/products/{product_id}")
        try:
            await page.goto(
                f"https://trip.coupang.com/tp/products/{product_id}",
                timeout=15000
            )
        except Exception as e:
            print(f"[PROBE] 페이지 이동 실패: {e}")
            await browser.close()
            return

        print(f"[PROBE] vendor-items API 호출 (vendorItemPackageId={vendor_item_package_id}, date={test_date})")
        try:
            result = await page.evaluate(
                js_code,
                {"vendorItemPackageId": vendor_item_package_id, "selectDate": test_date}
            )
        except Exception as e:
            print(f"[PROBE] API 호출 예외: {e}")
            await browser.close()
            return

        await browser.close()

    http_status = result.get("status")
    ok = result.get("ok")

    print(f"\n[RESULT] HTTP Status: {http_status}")
    if ok or http_status in (200, 400, 422):
        # 400/422는 파라미터 오류이지만 API 자체는 응답함 — 로그인 불필요
        print("[RESULT] ✅ 비로그인 접근 가능 — service_account_id 없이 모니터링 동작 가능")
        print("[ACTION] Phase 2-B (비로그인 모드)가 이미 구현됨. 별도 계정 불필요.")
    elif http_status in (401, 403):
        print("[RESULT] ❌ 로그인 필요 — service_account_id 필수")
        print("[ACTION] scripts/setup/setup_coupang_account.py 실행하여 계정 생성 및 로그인 필요.")
    else:
        print(f"[RESULT] ⚠️ 예상치 못한 상태 코드: {http_status} — 수동 확인 필요")


if __name__ == "__main__":
    asyncio.run(main())
