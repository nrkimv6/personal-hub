"""Update tracking items through the standard intent-keyword CLI."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Sequence

import httpx

from app.cli.tracking_add import (
    CliError,
    build_auth_headers,
    resolve_api_base,
    resolve_date_token,
)


NO_FIELDS_MESSAGE = "수정할 필드가 없습니다."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.tracking_update",
        description="Tracking item 표준 수정 CLI",
    )
    parser.add_argument("--id", type=int, required=True, help="수정할 Tracking item id")
    parser.add_argument("--title", help="Tracking 항목 제목")
    parser.add_argument("--description", help="Tracking 항목 설명")
    parser.add_argument("--wait-until", dest="wait_until", help="시작가능일 의도 토큰")
    parser.add_argument(
        "--earliest-check",
        dest="wait_until",
        help="--wait-until 별칭. 가장 이른 검증 가능일",
    )
    parser.add_argument("--deadline", help="마감기한 의도 토큰")
    parser.add_argument(
        "--clear-wait-until",
        action="store_true",
        help="시작가능일(start_at)을 null로 명시 수정",
    )
    parser.add_argument(
        "--clear-deadline",
        action="store_true",
        help="마감기한(due_at)을 null로 명시 수정",
    )
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 payload만 출력")
    parser.add_argument(
        "--api-base",
        default=None,
        help="Admin API base URL. 기본값: MONITOR_ADMIN_API_BASE 또는 http://localhost:8001",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.clear_wait_until and args.wait_until:
        raise CliError("`--clear-wait-until`과 `--wait-until`은 동시에 지정할 수 없습니다.")
    if args.clear_deadline and args.deadline:
        raise CliError("`--clear-deadline`과 `--deadline`은 동시에 지정할 수 없습니다.")
    if not any(
        (
            args.title is not None,
            args.description is not None,
            args.wait_until,
            args.deadline,
            args.clear_wait_until,
            args.clear_deadline,
        )
    ):
        raise CliError(NO_FIELDS_MESSAGE)


def build_update_payload(
    args: argparse.Namespace,
    now: datetime | None = None,
) -> dict[str, Any]:
    validate_args(args)
    base_now = now or datetime.now()
    payload: dict[str, Any] = {}

    if args.title is not None:
        payload["title"] = args.title
    if args.description is not None:
        payload["description"] = args.description
    if args.wait_until:
        payload["start_at"] = resolve_date_token(args.wait_until, base_now)
    elif args.clear_wait_until:
        payload["start_at"] = None
    if args.deadline:
        payload["due_at"] = resolve_date_token(args.deadline, base_now)
    elif args.clear_deadline:
        payload["due_at"] = None

    return payload


def _label_value(payload: dict[str, Any], field: str) -> str:
    if field not in payload:
        return "<변경 없음>"
    value = payload[field]
    if value is None:
        return "<지움>"
    return str(value)


def print_update_summary(item_id: int, payload: dict[str, Any]) -> None:
    print(f"item id={item_id}")
    print(f"시작가능일(start_at) = {_label_value(payload, 'start_at')}")
    print(f"마감기한(due_at) = {_label_value(payload, 'due_at')}")


def print_dry_run(item_id: int, payload: dict[str, Any]) -> None:
    print("DRY-RUN: tracking item update payload")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print_update_summary(item_id, payload)


def _response_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])
    return response.text


def patch_tracking_item(
    client: httpx.Client,
    item_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.patch(f"/api/v1/tracking/items/{item_id}", json=payload)
    if response.status_code == 404:
        raise CliError(f"tracking item id={item_id} not found", exit_code=4)
    if response.status_code == 400:
        raise CliError(_response_detail(response), exit_code=5)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise CliError("tracking item 수정 응답에서 id를 찾지 못했습니다.", exit_code=1)
    return data


def run(args: argparse.Namespace) -> int:
    payload = build_update_payload(args)
    if args.dry_run:
        print_dry_run(args.id, payload)
        return 0

    api_base = resolve_api_base(args.api_base)
    with httpx.Client(base_url=api_base, headers=build_auth_headers(), timeout=10.0) as client:
        item = patch_tracking_item(client, args.id, payload)

    print(f"Tracking item 수정 완료: id={item['id']}")
    print_update_summary(args.id, payload)
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
