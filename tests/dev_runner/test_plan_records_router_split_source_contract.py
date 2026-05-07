"""Source contract for the Plan Records route split."""

PUBLIC_PLAN_ROUTES = [
    ("POST", "/api/v1/plans/doc-patches/preview"),
    ("POST", "/api/v1/plans/doc-patches/{proposal_id}/apply"),
    ("POST", "/api/v1/plans/doc-patches/{proposal_id}/reject"),
    ("GET", "/api/v1/plans/events"),
    ("POST", "/api/v1/plans/insights/batch"),
    ("GET", "/api/v1/plans/insights/reports"),
    ("GET", "/api/v1/plans/insights/reports/{report_id}"),
    ("PATCH", "/api/v1/plans/insights/reports/{report_id}"),
    ("GET", "/api/v1/plans/insights/reports/{report_id}/evidence/{source_type}/{source_id}"),
    ("POST", "/api/v1/plans/insights/reports/{report_id}/promote-plan"),
    ("GET", "/api/v1/plans/records"),
    ("POST", "/api/v1/plans/records/archive-analyze/{record_id}"),
    ("GET", "/api/v1/plans/records/archive-candidates"),
    ("GET", "/api/v1/plans/records/archive-execution-attempts"),
    ("GET", "/api/v1/plans/records/archive-executions/history"),
    ("POST", "/api/v1/plans/records/archive-executions/run"),
    ("POST", "/api/v1/plans/records/archive-executions/sync"),
    ("GET", "/api/v1/plans/records/archive-health"),
    ("GET", "/api/v1/plans/records/archive-llm-requests"),
    ("GET", "/api/v1/plans/records/archive-llm-requests/{request_id}"),
    ("GET", "/api/v1/plans/records/archive-schedule-dashboard"),
    ("GET", "/api/v1/plans/records/archive-schedule-runs"),
    ("GET", "/api/v1/plans/records/by-path"),
    ("GET", "/api/v1/plans/records/guide-status"),
    ("POST", "/api/v1/plans/records/import-archived"),
    ("POST", "/api/v1/plans/records/index"),
    ("POST", "/api/v1/plans/records/ingest"),
    ("POST", "/api/v1/plans/records/sync"),
    ("GET", "/api/v1/plans/records/{record_id}"),
    ("POST", "/api/v1/plans/records/{record_id}/analyze"),
    ("POST", "/api/v1/plans/records/{record_id}/analyze-dry-run"),
    ("GET", "/api/v1/plans/records/{record_id}/chain"),
    ("GET", "/api/v1/plans/records/{record_id}/content"),
    ("PATCH", "/api/v1/plans/records/{record_id}/memo"),
    ("POST", "/api/v1/plans/records/{record_id}/reanalyze"),
    ("GET", "/api/v1/plans/records/{record_id}/relations"),
    ("POST", "/api/v1/plans/records/{record_id}/restore"),
    ("POST", "/api/v1/plans/retrieval/context"),
    ("POST", "/api/v1/plans/retrieval/cross-repo/index"),
    ("POST", "/api/v1/plans/retrieval/embeddings/index"),
    ("POST", "/api/v1/plans/retrieval/metrics"),
    ("POST", "/api/v1/plans/retrieval/search"),
    ("GET", "/api/v1/plans/statistics/recurrence"),
    ("GET", "/api/v1/plans/statistics/relations"),
]

ADMIN_ONLY_PLAN_ROUTES = [
    ("POST", "/api/v1/plans/records/archive-candidates/preview"),
    ("POST", "/api/v1/plans/records/archive-candidates/queue"),
    ("POST", "/api/v1/plans/records/archive-category-repair"),
    ("POST", "/api/v1/plans/records/archive-schedule/pause"),
    ("POST", "/api/v1/plans/records/archive-schedule/resume"),
]


def _plan_routes(app):
    rows = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        if not path or not path.startswith("/api/v1/plans"):
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            rows.append((method, path))
    return sorted(set(rows))


def _route_index(app, path: str, method: str) -> int:
    for index, route in enumerate(app.routes):
        if route.path == path and method in getattr(route, "methods", set()):
            return index
    raise AssertionError(f"{method} {path} is not registered")


def test_public_plan_records_route_surface_matches_split_baseline():
    from app.main import app

    assert _plan_routes(app) == sorted(PUBLIC_PLAN_ROUTES)


def test_admin_plan_records_route_surface_matches_split_baseline():
    from app.main_admin import app

    assert _plan_routes(app) == sorted(PUBLIC_PLAN_ROUTES + ADMIN_ONLY_PLAN_ROUTES)


def test_fixed_record_get_routes_stay_before_record_id_route():
    from app.main import app

    record_id_index = _route_index(app, "/api/v1/plans/records/{record_id}", "GET")
    for fixed_path in [
        "/api/v1/plans/records/archive-candidates",
        "/api/v1/plans/records/archive-health",
        "/api/v1/plans/records/archive-llm-requests",
        "/api/v1/plans/records/archive-schedule-dashboard",
        "/api/v1/plans/records/by-path",
        "/api/v1/plans/records/guide-status",
    ]:
        assert _route_index(app, fixed_path, "GET") < record_id_index

