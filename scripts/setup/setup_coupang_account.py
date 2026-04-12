"""
쿠팡 서비스 계정 자동 생성 스크립트 (로그인 필요 시).

probe_coupang_api.py 실행 결과 로그인이 필요한 경우에만 사용합니다.

사용법:
    python scripts/setup/setup_coupang_account.py
"""
import sys


def main() -> None:
    try:
        import httpx
    except ImportError:
        print("[ERROR] httpx가 설치되어 있지 않습니다. pip install httpx")
        sys.exit(1)

    api_base = "http://localhost:8001/api/v1"

    with httpx.Client(base_url=api_base, timeout=30) as client:
        # 기존 쿠팡 계정 확인
        resp = client.get("/service-accounts/active", params={"service_type": "coupang"})
        if resp.status_code == 200:
            accounts = resp.json()
            if accounts:
                account_id = accounts[0]["id"]
                print(f"[INFO] 기존 쿠팡 계정 사용: account_id={account_id}")
                return

        # 프로필 목록 조회
        resp = client.get("/profiles/")
        if resp.status_code != 200:
            print(f"[ERROR] 프로필 목록 조회 실패: {resp.status_code} {resp.text}")
            sys.exit(1)

        profiles = resp.json()
        if not profiles:
            print("[ERROR] 프로필이 없습니다. 먼저 프로필을 생성하세요.")
            sys.exit(1)

        profile_id = profiles[0]["id"]
        print(f"[INFO] 첫 번째 프로필 사용: profile_id={profile_id}")

        # 쿠팡 계정 생성
        resp = client.post(
            f"/profiles/{profile_id}/accounts",
            json={"service_type": "coupang", "identifier": "coupang_travel"}
        )
        if resp.status_code not in (200, 201):
            print(f"[ERROR] 계정 생성 실패: {resp.status_code} {resp.text}")
            sys.exit(1)

        account_id = resp.json()["id"]
        print(f"[INFO] 쿠팡 계정 생성 완료: account_id={account_id}")

        # 브라우저 로그인 실행
        resp = client.post(f"/service-accounts/{account_id}/browser/login")
        if resp.status_code != 200:
            print(f"[ERROR] 브라우저 로그인 실행 실패: {resp.status_code} {resp.text}")
            sys.exit(1)

        print("[INFO] 브라우저가 열렸습니다. trip.coupang.com에 로그인하세요.")
        input("[WAIT] 로그인 완료 후 Enter를 눌러주세요...")

        # 로그인 확인
        resp = client.post(f"/service-accounts/{account_id}/browser/check-login")
        if resp.status_code == 200:
            print(f"[SUCCESS] 쿠팡 계정 로그인 완료. account_id={account_id}")
        else:
            print(f"[WARNING] 로그인 확인 실패: {resp.status_code} {resp.text}")


if __name__ == "__main__":
    main()
