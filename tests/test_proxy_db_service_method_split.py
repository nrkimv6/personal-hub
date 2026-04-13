from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.proxy import ProxyBase
from app.schemas.proxy import ProxyCheckHistoryCreate, ProxyCreate, ProxyListParams
from app.services.proxy_db_service import ProxyDBService


@pytest.fixture
def proxy_db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    ProxyBase.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def proxy_db_service(proxy_db_session):
    return ProxyDBService(proxy_db_session)


def _create_proxy(service: ProxyDBService, url: str) -> object:
    return service.create(
        ProxyCreate(
            url=url,
            protocol="http",
            host=url.split("//", 1)[1].split(":", 1)[0],
            port=8080,
            source="test",
        )
    )


def test_get_stats_separates_get_and_post_snapshots(proxy_db_service):
    get_proxy = _create_proxy(proxy_db_service, "http://10.0.0.1:8080")
    post_proxy = _create_proxy(proxy_db_service, "http://10.0.0.2:8080")

    proxy_db_service.add_check_history(
        ProxyCheckHistoryCreate(
            proxy_id=get_proxy.id,
            is_valid=True,
            response_time=0.25,
            request_method="get",
        )
    )
    proxy_db_service.add_check_history(
        ProxyCheckHistoryCreate(
            proxy_id=post_proxy.id,
            is_valid=True,
            response_time=0.8,
            request_method="post",
        )
    )

    get_stats = proxy_db_service.get_stats("get")
    post_stats = proxy_db_service.get_stats("post")

    assert get_stats.request_method == "get"
    assert post_stats.request_method == "post"

    assert get_stats.total == 2
    assert post_stats.total == 2
    assert get_stats.active == 1
    assert post_stats.active == 1
    assert get_stats.avg_response_time == 0.25
    assert post_stats.avg_response_time == 0.8

    assert get_stats.by_method["get"]["active"] == 1
    assert get_stats.by_method["post"]["active"] == 1
    assert get_stats.by_method["get"]["avg_response_time"] == 0.25
    assert get_stats.by_method["post"]["avg_response_time"] == 0.8


def test_get_list_filters_by_request_method(proxy_db_service):
    get_proxy = _create_proxy(proxy_db_service, "http://10.0.1.1:8080")
    post_proxy = _create_proxy(proxy_db_service, "http://10.0.1.2:8080")

    proxy_db_service.add_check_history(
        ProxyCheckHistoryCreate(
            proxy_id=get_proxy.id,
            is_valid=True,
            response_time=0.2,
            request_method="get",
        )
    )
    proxy_db_service.add_check_history(
        ProxyCheckHistoryCreate(
            proxy_id=post_proxy.id,
            is_valid=True,
            response_time=0.9,
            request_method="post",
        )
    )

    get_list = proxy_db_service.get_list(ProxyListParams(status="active", request_method="get"))
    post_list = proxy_db_service.get_list(ProxyListParams(status="active", request_method="post"))

    assert get_list.total == 1
    assert post_list.total == 1
    assert {item.id for item in get_list.items} == {get_proxy.id}
    assert {item.id for item in post_list.items} == {post_proxy.id}
    assert get_list.items[0].request_method == "get"
    assert post_list.items[0].request_method == "post"


def test_get_detail_filters_history_by_request_method(proxy_db_service):
    proxy = _create_proxy(proxy_db_service, "http://10.0.2.1:8080")

    proxy_db_service.add_check_history(
        ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.3,
            request_method="get",
        )
    )
    proxy_db_service.add_check_history(
        ProxyCheckHistoryCreate(
            proxy_id=proxy.id,
            is_valid=True,
            response_time=0.7,
            request_method="post",
        )
    )

    get_detail = proxy_db_service.get_detail(proxy.id, request_method="get")
    post_detail = proxy_db_service.get_detail(proxy.id, request_method="post")

    assert get_detail is not None
    assert post_detail is not None
    assert get_detail.request_method == "get"
    assert post_detail.request_method == "post"
    assert get_detail.total_checks == 1
    assert post_detail.total_checks == 1
    assert [history.request_method for history in get_detail.check_history] == ["get"]
    assert [history.request_method for history in post_detail.check_history] == ["post"]
