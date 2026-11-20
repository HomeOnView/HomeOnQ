"""데모 API(/demo/*) 동작 조건 테스트.

Render 시연 배포는 `APP_ENV=demo` 로 뜬다. 이 환경에서 '분석 테스트' 탭이 쓰는
`/demo/config`·`/demo/simulate`·`/demo/reset` 이 열려 있고, `APP_ENV=production`
에서는 404로 닫히는지 확인한다.
"""
import pytest
from fastapi import HTTPException

from app.api.routes import demo as demo_routes


def test_demo_config_enabled_outside_production(client):
    client, _ = client
    res = client.get("/api/v1/demo/config")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert set(body["scenarios"]) == {"normal", "fall", "inactive", "wandering"}
    assert body["credentials"]["email"] == "demo@homeonq.kr"


def test_demo_simulate_requires_guardian_login(client):
    client, _ = client
    res = client.post("/api/v1/demo/simulate", json={"scenario": "fall"})
    assert res.status_code == 401


def test_demo_routes_are_404_in_production(monkeypatch):
    class ProductionSettings:
        is_production = True

    monkeypatch.setattr(demo_routes, "settings", ProductionSettings())
    for call in (demo_routes._guard_demo_enabled,):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404
