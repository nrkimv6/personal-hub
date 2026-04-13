"""Claude 세션 요약 CLI 스크립트.

사용법:
  python scripts/diagnostics/summarize_sessions.py --limit 8
  python scripts/diagnostics/summarize_sessions.py --offline
  python scripts/diagnostics/summarize_sessions.py --source-type agent --limit 5
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _offline_list(project_path: str, limit: int, since: datetime | None, source_type: str | None):
    """API 없이 로컬 파일로 세션 목록 출력."""
    from app.modules.claude_sessions.session_parser import SessionParser

    parser = SessionParser()
    sessions = parser.list_sessions(
        project_path=project_path,
        limit=limit,
        since=since,
        source_type=source_type,
    )
    if not sessions:
        print("세션 없음")
        return

    for s in sessions:
        agent = f" / {s.agent_name}" if s.agent_name else ""
        cwd = f" | {s.cwd}" if s.cwd else ""
        print(f"[{s.source_type}{agent}] {s.id[:8]}… | {s.mtime.strftime('%m-%d %H:%M')} | {s.line_count}줄{cwd}")
        if s.first_message:
            print(f"  \"{s.first_message[:80]}\"")


def _api_summarize(api_base: str, encoded: str, session_ids: list[str], timeout_s: int = 60):
    """API를 통해 요약 요청 후 결과 폴링."""
    import urllib.request
    import urllib.error

    def post(url: str) -> dict:
        req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def get(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())

    print(f"요약 요청 중 ({len(session_ids)}개)…")
    request_ids: list[int] = []
    for sid in session_ids:
        url = f"{api_base}/api/v1/claude-sessions/{encoded}/sessions/{sid}/summarize"
        try:
            res = post(url)
            request_ids.append(res["request_id"])
            print(f"  enqueue: {sid[:8]}… → request_id={res['request_id']}")
        except Exception as e:
            print(f"  실패: {sid[:8]}… — {e}")

    if not request_ids:
        return

    print(f"\n결과 대기 중 (최대 {timeout_s}초)…")
    pending = set(session_ids[:len(request_ids)])
    deadline = time.time() + timeout_s

    while pending and time.time() < deadline:
        time.sleep(2)
        done: set[str] = set()
        for sid in list(pending):
            url = f"{api_base}/api/v1/claude-sessions/summary/{sid}"
            try:
                res = get(url)
                status = res.get("status", "unknown")
                if status in ("completed", "failed", "not_found"):
                    done.add(sid)
                    summary = res.get("summary") or "(없음)"
                    print(f"\n[{status}] {sid[:8]}…")
                    if status == "completed":
                        print(f"  {summary}")
            except Exception:
                pass
        pending -= done

    if pending:
        print(f"\n타임아웃: {len(pending)}개 미완료")


def main():
    parser = argparse.ArgumentParser(description="Claude 세션 요약 CLI")
    parser.add_argument("--project", default=str(ROOT), help="프로젝트 절대경로 (기본: 현재 프로젝트)")
    parser.add_argument("--limit", type=int, default=8, help="최대 세션 수 (기본: 8)")
    parser.add_argument("--since", help="ISO8601 시작일시 (예: 2026-04-13T00:00:00)")
    parser.add_argument("--source-type", choices=["user", "agent", "llm-worker"], help="소스 타입 필터")
    parser.add_argument("--api", default="http://localhost:8001", help="API 기본 URL (기본: http://localhost:8001)")
    parser.add_argument("--offline", action="store_true", help="API 없이 로컬 파싱만 실행")
    args = parser.parse_args()

    since: datetime | None = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"오류: since 형식이 잘못됨 ({args.since})")
            sys.exit(1)

    if args.offline:
        _offline_list(args.project, args.limit, since, args.source_type)
        return

    # API 모드: 세션 목록 조회 후 요약 요청
    import urllib.request
    import urllib.parse

    from app.modules.claude_sessions.session_parser import encode_project_path
    encoded = encode_project_path(args.project)

    params: dict = {"limit": args.limit}
    if since:
        params["since"] = since.isoformat()
    if args.source_type:
        params["source_type"] = args.source_type

    qs = urllib.parse.urlencode(params)
    sessions_url = f"{args.api}/api/v1/claude-sessions/{encoded}/sessions?{qs}"
    try:
        with urllib.request.urlopen(sessions_url, timeout=15) as r:
            sessions = json.loads(r.read())
    except Exception as e:
        print(f"세션 목록 조회 실패: {e}")
        print("--offline 옵션으로 재시도해보세요")
        sys.exit(1)

    if not sessions:
        print("세션 없음")
        return

    print(f"세션 {len(sessions)}개:")
    for s in sessions:
        agent = f" / {s.get('agent_name', '')}" if s.get("agent_name") else ""
        print(f"  [{s['source_type']}{agent}] {s['id'][:8]}… | {s['mtime'][:16]} | {s['line_count']}줄")

    session_ids = [s["id"] for s in sessions]
    _api_summarize(args.api, encoded, session_ids)


if __name__ == "__main__":
    main()
