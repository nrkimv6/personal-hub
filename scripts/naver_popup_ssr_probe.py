#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

TARGET_URL = "https://pcmap.place.naver.com/popupstore/list"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
APOLLO_PATTERN = re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{[^<]*\})")


def build_profiles() -> dict[str, dict[str, str]]:
    return {
        "A": {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Referer": "https://pcmap.place.naver.com/",
        },
        "B": {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
        "C": {
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
    }


def summarize_apollo(html: str) -> dict[str, Any]:
    match = APOLLO_PATTERN.search(html)
    if not match:
        return {
            "has_apollo_state": False,
            "apollo_json_parse_ok": False,
            "apollo_keys_count": 0,
            "root_query_key_count": 0,
            "root_query_popup_keys": [],
            "root_query_keys_sample": [],
            "apollo_keys_sample": [],
            "parse_error": "not_found",
        }

    apollo_raw = match.group(1)
    try:
        apollo_state = json.loads(apollo_raw)
    except json.JSONDecodeError as exc:
        return {
            "has_apollo_state": True,
            "apollo_json_parse_ok": False,
            "apollo_keys_count": 0,
            "root_query_key_count": 0,
            "root_query_popup_keys": [],
            "root_query_keys_sample": [],
            "apollo_keys_sample": [],
            "parse_error": str(exc),
        }

    root_query = apollo_state.get("ROOT_QUERY")
    root_query_keys = sorted(root_query.keys()) if isinstance(root_query, dict) else []
    popup_root_query_keys = sorted(
        key for key in root_query_keys if "popup" in key.lower() or "store" in key.lower()
    )
    apollo_keys = sorted(apollo_state.keys())
    popup_apollo_keys = sorted(
        key for key in apollo_keys if "popup" in key.lower() or "store" in key.lower()
    )

    return {
        "has_apollo_state": True,
        "apollo_json_parse_ok": True,
        "apollo_keys_count": len(apollo_keys),
        "root_query_key_count": len(root_query_keys),
        "root_query_popup_keys": popup_root_query_keys[:30],
        "root_query_keys_sample": root_query_keys[:30],
        "apollo_keys_sample": apollo_keys[:30],
        "apollo_popup_keys_sample": popup_apollo_keys[:30],
        "parse_error": None,
    }


async def fetch_once(
    session: aiohttp.ClientSession,
    profile_name: str,
    attempt_index: int,
    timeout_seconds: float,
    headers: dict[str, str],
) -> dict[str, Any]:
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        async with session.get(TARGET_URL, headers=headers, timeout=timeout) as response:
            body = await response.read()
            text = body.decode("utf-8", "ignore")
            apollo = summarize_apollo(text)
            redirect_chain = [str(history.url) for history in response.history]
            return {
                "profile": profile_name,
                "attempt": attempt_index,
                "started_at": started_at,
                "status": response.status,
                "final_url": str(response.url),
                "content_type": response.headers.get("Content-Type"),
                "body_bytes": len(body),
                "html_length": len(text),
                "redirect_chain": redirect_chain,
                "body_preview": text[:250],
                **apollo,
                "error": None,
            }
    except Exception as exc:  # pragma: no cover - diagnostics script
        return {
            "profile": profile_name,
            "attempt": attempt_index,
            "started_at": started_at,
            "status": None,
            "final_url": None,
            "content_type": None,
            "body_bytes": 0,
            "html_length": 0,
            "redirect_chain": [],
            "body_preview": "",
            "has_apollo_state": False,
            "apollo_json_parse_ok": False,
            "apollo_keys_count": 0,
            "root_query_key_count": 0,
            "root_query_popup_keys": [],
            "root_query_keys_sample": [],
            "apollo_keys_sample": [],
            "apollo_popup_keys_sample": [],
            "parse_error": None,
            "error": repr(exc),
        }


def summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "attempt_count": len(attempts),
        "status_200_count": sum(1 for attempt in attempts if attempt["status"] == 200),
        "apollo_found_count": sum(1 for attempt in attempts if attempt["has_apollo_state"]),
        "apollo_parse_ok_count": sum(
            1 for attempt in attempts if attempt["apollo_json_parse_ok"]
        ),
        "error_count": sum(1 for attempt in attempts if attempt["error"] is not None),
    }


async def run_probe(
    repeats: int,
    timeout_seconds: float,
    pause_seconds: float,
) -> dict[str, Any]:
    profiles = build_profiles()
    results: dict[str, Any] = {}

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for profile_name, headers in profiles.items():
            attempts: list[dict[str, Any]] = []
            for attempt_index in range(1, repeats + 1):
                attempt = await fetch_once(
                    session=session,
                    profile_name=profile_name,
                    attempt_index=attempt_index,
                    timeout_seconds=timeout_seconds,
                    headers=headers,
                )
                attempts.append(attempt)
                if attempt_index < repeats:
                    await asyncio.sleep(pause_seconds)

            results[profile_name] = {
                "headers": headers,
                "summary": summarize_attempts(attempts),
                "attempts": attempts,
            }

    popup_root_query_keys: dict[str, int] = {}
    for profile_data in results.values():
        for attempt in profile_data["attempts"]:
            for key in attempt.get("root_query_popup_keys", []):
                popup_root_query_keys[key] = popup_root_query_keys.get(key, 0) + 1

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "target_url": TARGET_URL,
            "repeats_per_profile": repeats,
            "timeout_seconds": timeout_seconds,
            "pause_seconds": pause_seconds,
            "profile_order": list(profiles.keys()),
        },
        "profiles": results,
        "aggregated": {
            "popup_root_query_key_counts": dict(
                sorted(
                    popup_root_query_keys.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe SSR Apollo state for pcmap place popup list endpoint."
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--pause", type=float, default=1.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("logs") / "naver-popup-feasibility",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be >= 1")

    payload = asyncio.run(
        run_probe(
            repeats=args.repeats,
            timeout_seconds=args.timeout,
            pause_seconds=args.pause,
        )
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output_dir / f"popup_ssr_probe_{stamp}.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[probe] output={output_path.as_posix()}")
    for profile_name, profile_data in payload["profiles"].items():
        summary = profile_data["summary"]
        print(
            f"[probe] profile={profile_name} "
            f"status200={summary['status_200_count']}/{summary['attempt_count']} "
            f"apollo={summary['apollo_found_count']}/{summary['attempt_count']} "
            f"parse_ok={summary['apollo_parse_ok_count']}/{summary['attempt_count']} "
            f"errors={summary['error_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
