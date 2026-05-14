"""System service Redis status source contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_STATUS = ROOT / "frontend" / "src" / "routes" / "system" / "ServiceStatusTab.svelte"
SERVICE_DASHBOARD = ROOT / "frontend" / "src" / "routes" / "system" / "service-status" / "ServiceDashboardSection.svelte"
INFRASTRUCTURE = ROOT / "frontend" / "src" / "routes" / "system" / "service-status" / "InfrastructureSection.svelte"
TYPES = ROOT / "frontend" / "src" / "routes" / "system" / "service-status" / "types.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_service_status_has_redis_fetch_state_R() -> None:
    """R: Redis fetch state is tracked separately from the Redis status payload."""
    source = _read(SERVICE_STATUS)
    types_source = _read(TYPES)

    assert "export type RedisFetchState = 'loading' | 'ok' | 'error';" in types_source
    assert "let redisFetchState = $state<RedisFetchState>('loading');" in source


def test_fetch_extra_status_does_not_map_fetch_failure_to_disconnected_E() -> None:
    """E: A failed fetch must not synthesize connected:false and render Disconnected."""
    source = _read(SERVICE_STATUS)

    assert "fetchRedisWithRetry()" in source
    assert "serviceDashboardApi.redisStatus().catch(() => null)" not in source
    assert "redisStatus = redis ??" not in source
    assert "if (redis !== null) redisStatus = redis;" in source


def test_fetch_retry_sets_error_without_overwriting_redis_status_R() -> None:
    """R: Retry failure reports fetch error while leaving redisStatus untouched."""
    source = _read(SERVICE_STATUS)

    assert "async function fetchRedisWithRetry(): Promise<RedisStatus | null>" in source
    assert "await sleep(1000);" in source
    assert "redisFetchState = 'error';" in source
    assert "return null;" in source


def test_fetch_success_restores_ok_state_R() -> None:
    """R: A later successful poll restores the ok state."""
    source = _read(SERVICE_STATUS)

    assert source.count("redisFetchState = 'ok';") >= 2
    assert "return redis;" in source


def test_service_dashboard_passes_redis_fetch_state_Re() -> None:
    """Re: The fetch state reaches the infrastructure section through typed props."""
    status_source = _read(SERVICE_STATUS)
    dashboard_source = _read(SERVICE_DASHBOARD)
    infra_source = _read(INFRASTRUCTURE)
    types_source = _read(TYPES)

    assert "{redisFetchState}" in status_source
    assert "redisFetchState: RedisFetchState;" in dashboard_source
    assert "{redisFetchState}" in dashboard_source
    assert "redisFetchState: RedisFetchState;" in types_source
    assert "redisFetchState," in infra_source


def test_infrastructure_section_branches_loading_error_ok_Co() -> None:
    """Co: Redis badge distinguishes loading, fetch error, connected, and disconnected."""
    source = _read(INFRASTRUCTURE)

    assert "if (redisFetchState === 'loading') return '확인 중';" in source
    assert "if (redisFetchState === 'error') return '확인 실패';" in source
    assert "return redisStatus?.connected ? 'Connected' : 'Disconnected';" in source
    assert "redisFetchState !== 'ok'" in source


def test_infrastructure_details_require_ok_and_connected_B() -> None:
    """B: Stale successful payload details are hidden while Redis fetch is failing."""
    source = _read(INFRASTRUCTURE)

    assert "{#if redisFetchState === 'ok' && redisStatus.connected}" in source
    assert "pulse={redisFetchState === 'ok' && redisStatus.connected}" in source
