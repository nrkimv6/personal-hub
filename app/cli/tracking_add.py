"""Create tracking items through the standard intent-keyword CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from calendar import monthrange
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import httpx


DEFAULT_API_BASE = "http://localhost:8001"
TOKEN_RE = re.compile(r"^(\d+)(d|w|mo|h)$", re.IGNORECASE)
MISSING_DATE_MESSAGE = (
    "시작가능일(--wait-until) 또는 마감기한(--deadline) 중 최소 하나는 필수입니다."
)


class CliError(Exception):
    """User-facing CLI error with an exit code."""

    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def add_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def serialize_datetime(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def resolve_date_token(token: str, now: datetime) -> str:
    stripped = token.strip()
    match = TOKEN_RE.fullmatch(stripped)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if amount <= 0:
            raise CliError(f"토큰 형식이 잘못됨: {token}")
        if unit == "h":
            return serialize_datetime(now + timedelta(hours=amount))
        if unit == "d":
            return serialize_datetime(now + timedelta(days=amount))
        if unit == "w":
            return serialize_datetime(now + timedelta(weeks=amount))
        if unit == "mo":
            return serialize_datetime(add_months(now, amount))

    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError as exc:
        raise CliError(f"토큰 형식이 잘못됨: {token}") from exc
    return serialize_datetime(parsed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.tracking_add",
        description="Tracking item 표준 등록 CLI",
    )
    parser.add_argument("--title", required=True, help="Tracking 항목 제목")
    parser.add_argument("--description", help="Tracking 항목 설명")
    parser.add_argument("--wait-until", dest="wait_until", help="시작가능일 의도 토큰")
    parser.add_argument(
        "--earliest-check",
        dest="wait_until",
        help="--wait-until 별칭. 가장 이른 검증 가능일",
    )
    parser.add_argument("--deadline", help="마감기한 의도 토큰")
    parser.add_argument(
        "--link-plan",
        action="append",
        default=[],
        help="연결할 plan path. 여러 번 지정 가능",
    )
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 payload만 출력")
    parser.add_argument(
        "--api-base",
        default=None,
        help="Admin API base URL. 기본값: MONITOR_ADMIN_API_BASE 또는 http://localhost:8001",
    )
    return parser


def build_payload(args: argparse.Namespace, now: datetime | None = None) -> dict[str, Any]:
    base_now = now or datetime.now()
    start_at = resolve_date_token(args.wait_until, base_now) if args.wait_until else None
    due_at = resolve_date_token(args.deadline, base_now) if args.deadline else None
    if start_at is None and due_at is None:
        raise CliError(MISSING_DATE_MESSAGE, exit_code=2)

    payload: dict[str, Any] = {
        "title": args.title,
        "description": args.description,
        "start_at": start_at,
        "due_at": due_at,
    }
    return {key: value for key, value in payload.items() if value is not None}


def build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("MONITOR_ADMIN_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def resolve_api_base(api_base: str | None) -> str:
    return (api_base or os.environ.get("MONITOR_ADMIN_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def _extract_record_id(data: Any) -> int:
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise CliError("plan record 응답에서 id를 찾지 못했습니다.", exit_code=3)
    return data["id"]


def lookup_plan_record_id(client: httpx.Client, plan_path: str) -> int:
    if "/" in plan_path or "\\" in plan_path:
        response = client.get("/api/v1/plans/records/by-path", params={"file_path": plan_path})
        if response.status_code == 200:
            return _extract_record_id(response.json())

    fallback = client.get("/api/v1/plans/records", params={"q": plan_path, "limit": 10})
    fallback.raise_for_status()
    records = fallback.json()
    if not isinstance(records, list) or not records:
        raise CliError(f"plan record를 찾지 못했습니다: {plan_path}", exit_code=3)
    return _extract_record_id(records[0])


def create_tracking_item(client: httpx.Client, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/v1/tracking/items", json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise CliError("tracking item 생성 응답에서 id를 찾지 못했습니다.", exit_code=1)
    return data


def link_tracking_plans(client: httpx.Client, item_id: int, plan_record_ids: Iterable[int]) -> None:
    ids = list(dict.fromkeys(plan_record_ids))
    if not ids:
        return
    response = client.post(
        f"/api/v1/tracking/items/{item_id}/plans",
        json={"plan_record_ids": ids},
    )
    response.raise_for_status()


def print_dry_run(payload: dict[str, Any], link_plans: Sequence[str]) -> None:
    print("DRY-RUN: tracking item payload")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"시작가능일(start_at) = {payload.get('start_at', '<없음>')}")
    print(f"마감기한(due_at) = {payload.get('due_at', '<없음>')}")
    if link_plans:
        print("연결 계획서(link_plan) =")
        for plan_path in link_plans:
            print(f"- {plan_path}")


def run(args: argparse.Namespace) -> int:
    payload = build_payload(args)
    link_plans = list(args.link_plan or [])
    if args.dry_run:
        print_dry_run(payload, link_plans)
        return 0

    api_base = resolve_api_base(args.api_base)
    with httpx.Client(base_url=api_base, headers=build_headers(), timeout=10.0) as client:
        item = create_tracking_item(client, payload)
        item_id = item["id"]
        missing: list[str] = []
        plan_ids: list[int] = []
        for plan_path in link_plans:
            try:
                plan_ids.append(lookup_plan_record_id(client, plan_path))
            except Exception:
                missing.append(plan_path)

        if plan_ids:
            try:
                link_tracking_plans(client, item_id, plan_ids)
            except httpx.HTTPError as exc:
                print(
                    f"item은 생성됨 (id={item_id}). plan link 실패: {exc}",
                    file=sys.stderr,
                )
                return 3

    print(f"Tracking item 생성 완료: id={item_id}")
    if missing:
        print(
            f"item은 생성됨 (id={item_id}). 누락된 plan은 frontend 또는 직접 link API로 추가하세요: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except httpx.HTTPError as exc:
        print(f"HTTP 요청 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
