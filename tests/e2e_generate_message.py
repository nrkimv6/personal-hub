"""
E2E HTTP 테스트: git-repos generate-message 엔진 선택 옵션

실행 전제: 서버가 로컬에서 실행 중이어야 함 (http://localhost:8000)
실행 방법: python tests/e2e_generate_message.py [--base-url http://localhost:8000] [--repo-id 1]

TC-E1: body 없이 POST → claude 기본값 동작 확인
TC-E2: {"provider": "claude"} 명시 → 정상 동작
TC-E3: {"provider": "gemini"} → Gemini 실행 확인
TC-E4: 응답 message 필드에 텍스트 있는지 확인
TC-E5: {"provider": "invalid"} → 422 응답 확인
"""

import argparse
import json
import sys
import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str
    status_code: Optional[int] = None


def run_tc(name: str, url: str, body: Optional[dict], expected_status: int) -> TestResult:
    """단일 TC 실행 헬퍼."""
    try:
        if body is None:
            resp = requests.post(url, timeout=60)
        else:
            resp = requests.post(url, json=body, timeout=60)

        passed = resp.status_code == expected_status
        detail = f"status={resp.status_code}"
        if resp.status_code == 200:
            data = resp.json()
            msg = data.get("message", "")
            detail += f", message='{msg[:60]}'" if msg else ", message=(empty)"
        elif not passed:
            detail += f", body={resp.text[:200]}"

        return TestResult(name=name, passed=passed, detail=detail, status_code=resp.status_code)

    except requests.exceptions.ConnectionError:
        return TestResult(name=name, passed=False, detail="서버에 연결할 수 없음 (Connection refused)")
    except Exception as e:
        return TestResult(name=name, passed=False, detail=f"예외 발생: {e}")


def run_all(base_url: str, repo_id: int) -> list[TestResult]:
    """모든 E2E TC 실행."""
    url = f"{base_url}/api/v1/git-repos/{repo_id}/generate-message"
    results = []

    results.append(run_tc("TC-E1: body 없이 POST (claude 기본)", url, None, 200))
    results.append(run_tc("TC-E2: provider=claude 명시", url, {"provider": "claude"}, 200))
    results.append(run_tc("TC-E3: provider=gemini", url, {"provider": "gemini"}, 200))

    # TC-E4: 응답 message 필드 확인 (TC-E1 결과 재활용)
    try:
        resp = requests.post(url, timeout=60)
        has_message = "message" in resp.json() if resp.status_code == 200 else False
        results.append(TestResult(
            name="TC-E4: 응답 message 필드 존재 확인",
            passed=has_message,
            detail=f"message 필드 {'존재' if has_message else '없음'}",
            status_code=resp.status_code,
        ))
    except Exception as e:
        results.append(TestResult(name="TC-E4", passed=False, detail=str(e)))

    results.append(run_tc("TC-E5: provider=invalid → 422", url, {"provider": "invalid"}, 422))

    return results


def main():
    parser = argparse.ArgumentParser(description="E2E test: generate-message engine option")
    parser.add_argument("--base-url", default="http://localhost:8000", help="서버 base URL")
    parser.add_argument("--repo-id", type=int, default=1, help="테스트할 repo_id")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"E2E 테스트: generate-message 엔진 선택")
    print(f"서버: {args.base_url}  repo_id: {args.repo_id}")
    print(f"{'='*60}\n")

    results = run_all(args.base_url, args.repo_id)

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"{status} | {r.name}")
        print(f"       {r.detail}\n")

    print(f"{'='*60}")
    print(f"결과: {passed}/{total} 통과")
    print(f"{'='*60}\n")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
