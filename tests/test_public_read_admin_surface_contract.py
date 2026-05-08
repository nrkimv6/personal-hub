"""Static contract for public read allowlist and admin-only router seeds."""

from pathlib import Path

from app.core.middleware import ADMIN_ONLY_READ_PREFIXES, PUBLIC_SAFE_READ_PREFIXES, is_admin_only_read_path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_admin_only_seed_prefixes_are_classified() -> None:
    expected = {
        "/api/v1/dev-runner",
        "/api/v1/plans",
        "/api/v1/git-repos",
        "/api/v1/file-search",
        "/api/v1/system",
        "/api/v1/worker",
        "/api/v1/llm",
        "/api/v1/ss",
        "/api/ic",
        "/api/fc",
    }

    assert expected.issubset(set(ADMIN_ONLY_READ_PREFIXES))


def test_admin_only_matching_uses_path_segment_boundaries() -> None:
    assert is_admin_only_read_path("/api/v1/system/services/workers") is True
    assert is_admin_only_read_path("/api/v1/system") is True
    assert is_admin_only_read_path("/api/v1/systemic/status") is False
    assert is_admin_only_read_path("/api/v1/dev-runner-status") is False


def test_public_safe_prefixes_have_source_comment() -> None:
    source = (REPO_ROOT / "app/core/middleware.py").read_text(encoding="utf-8")

    assert "PUBLIC_SAFE_READ_PREFIXES" in source
    assert "product or health surfaces" in source
    assert "Keep this list narrow" in source
    assert "/api/v1/system/liveness" in PUBLIC_SAFE_READ_PREFIXES
    assert "/api/v1/monitoring/events/coupang-public-history" in PUBLIC_SAFE_READ_PREFIXES


def test_router_registry_admin_seed_surface_is_not_left_unclassified() -> None:
    registry = (REPO_ROOT / "app/router_registry.py").read_text(encoding="utf-8")
    middleware = (REPO_ROOT / "app/core/middleware.py").read_text(encoding="utf-8")
    seed_prefix_pairs = (
        ("dev-runner", "/api/v1/dev-runner"),
        ("plans/records", "/api/v1/plans"),
        ("git-repos", "/api/v1/git-repos"),
        ("file-search", "/api/v1/file-search"),
        ("system", "/api/v1/system"),
        ("worker", "/api/v1/worker"),
        ("llm", "/api/v1/llm"),
        ("/api/ic", "/api/ic"),
        ("/api/fc", "/api/fc"),
        ("/api/v1/ss", "/api/v1/ss"),
    )

    for seed, prefix in seed_prefix_pairs:
        assert seed in registry
        assert prefix in middleware
