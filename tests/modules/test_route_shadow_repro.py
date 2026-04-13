"""
라우트 순서 섀도잉 재현 및 수정 검증 테스트
"""
import pytest
from fastapi import FastAPI, APIRouter, Query
from fastapi.testclient import TestClient

def test_route_shadow_regression():
    """정적 경로가 파라미터 경로 뒤에 있을 때 422가 발생하는지 재현"""
    app = FastAPI()
    router = APIRouter()

    @router.get("/{item_id}")
    def get_item(item_id: int):
        return {"item_id": item_id}

    @router.get("/static-path")
    def get_static():
        return {"message": "static"}

    app.include_router(router)
    client = TestClient(app)

    # shadowing 발생: "/static-path" 문자열을 /{item_id} (int) 로 파싱 시도
    resp = client.get("/static-path")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["path", "item_id"]

def test_route_order_fixed_logic():
    """정적 경로가 파라미터 경로 앞에 있을 때 정상 동작하는지 확인"""
    app = FastAPI()
    router = APIRouter()

    @router.get("/static-path")
    def get_static():
        return {"message": "static"}

    @router.get("/{item_id}")
    def get_item(item_id: int):
        return {"item_id": item_id}

    app.include_router(router)
    client = TestClient(app)

    # shadowing 안 됨: 정적 경로가 먼저 매칭됨
    resp = client.get("/static-path")
    assert resp.status_code == 200
    assert resp.json() == {"message": "static"}

    # 파라미터 경로도 정상 동작
    resp = client.get("/123")
    assert resp.status_code == 200
    assert resp.json() == {"item_id": 123}

