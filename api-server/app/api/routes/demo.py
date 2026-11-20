"""웹앱 시연용 엔드포인트.

브라우저에서 '정상 보행 / 낙상 발생 / 장시간 무활동 / 배회' 버튼을 누르면
`camera-analysis/onview`의 실제 분석 코드로 샘플 관절좌표를 분석하고,
그 결과를 **실제 기기용 API(/api/v1/device/...)** 로 다시 호출해 DB에 저장한다.
(ASGI 전송 계층을 그대로 통과하므로 라우터·검증·트랜잭션이 실제와 동일하다.)

운영 환경(APP_ENV=production)에서는 비활성화된다.
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import CameraDevice, Guardian, GuardianSenior, Senior
from app.schemas.guardian import DemoSimulationRequest
from app.services.auth import get_current_guardian, require_senior_access
from app.services.demo_seed import DEMO_EDGE_DEVICE_ID, DEMO_EDGE_TOKEN, seed_demo

router = APIRouter(tags=["demo"])

PIPELINE_DIR = Path(__file__).resolve().parents[4] / "camera-analysis"
SAMPLE_BY_SCENARIO = {
    "normal": "normal_walk.json",
    "fall": "fall_event.json",
    "inactive": "long_inactive.json",
    "wandering": "wandering.json",
}


def _guard_demo_enabled() -> None:
    if settings.is_production:
        raise HTTPException(404, "Not found")


def _ensure_edge_device(db: Session, senior: Senior) -> CameraDevice:
    device = db.scalar(select(CameraDevice).where(CameraDevice.device_id == DEMO_EDGE_DEVICE_ID))
    if device is None:
        device = CameraDevice(
            id=str(uuid.uuid4()),
            device_id=DEMO_EDGE_DEVICE_ID,
            senior_id=senior.id,
            token_hash=hashlib.sha256(DEMO_EDGE_TOKEN.encode()).hexdigest(),
            status="active",
        )
        db.add(device)
        db.commit()
        db.refresh(device)
    return device


def _load_pipeline():
    if str(PIPELINE_DIR) not in sys.path:
        sys.path.insert(0, str(PIPELINE_DIR))
    try:
        from onview import simulation  # noqa: WPS433 (지연 import)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            500, f"자세분석 파이프라인을 불러오지 못했습니다: {exc}"
        ) from exc
    return simulation


@router.post("/demo/simulate")
async def simulate(
    payload: DemoSimulationRequest,
    request: Request,
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    _guard_demo_enabled()
    if payload.senior_id:
        senior = require_senior_access(payload.senior_id, guardian, db)
    else:
        seniors = db.scalars(
            select(Senior)
            .join(GuardianSenior)
            .where(
                GuardianSenior.guardian_id == guardian.id,
                GuardianSenior.status == "active",
                Senior.is_active.is_(True),
            )
        ).all()
        if not seniors:
            raise HTTPException(404, "연결된 어르신이 없습니다. 먼저 데모 데이터를 생성하세요.")
        senior = seniors[0]

    device = _ensure_edge_device(db, senior)
    simulation = _load_pipeline()
    sample_path = PIPELINE_DIR / "samples" / SAMPLE_BY_SCENARIO[payload.scenario]
    if not sample_path.exists():
        raise HTTPException(500, f"샘플 시퀀스가 없습니다: {sample_path.name}")

    result = simulation.analyze_scenario(payload.scenario, sample_path, senior_name=senior.display_name)

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    sent = {"behavior": 0, "fall": 0, "report": 0, "errors": []}
    async with httpx.AsyncClient(transport=transport, base_url="http://demo.local") as client:
        headers = {"X-Device-Token": DEMO_EDGE_TOKEN}
        for body in result.behavior_payloads:
            resp = await client.post("/api/v1/device/behavior-events", json=body, headers=headers)
            if resp.status_code in (200, 201):
                sent["behavior"] += 1
            else:
                sent["errors"].append(f"behavior {resp.status_code}: {resp.text[:200]}")
        for body in result.fall_payloads:
            resp = await client.post("/api/v1/device/fall-events", json=body, headers=headers)
            if resp.status_code in (200, 201):
                sent["fall"] += 1
            else:
                sent["errors"].append(f"fall {resp.status_code}: {resp.text[:200]}")
        report_body = result.report_payload
        resp = await client.post("/api/v1/device/daily-reports", json=report_body, headers=headers)
        if resp.status_code in (200, 201):
            sent["report"] = 1
        else:
            sent["errors"].append(f"report {resp.status_code}: {resp.text[:200]}")
        await client.post(
            "/api/v1/device/heartbeat",
            json={"status": "HEALTHY", "metrics": {"scenario": payload.scenario, "source": "webapp-demo"}},
            headers=headers,
        )

    return {
        "scenario": payload.scenario,
        "senior_id": senior.id,
        "device_id": device.device_id,
        "analysis": result.public_summary(),
        "sent": sent,
        "report": result.report_payload,
    }


@router.post("/demo/reset")
def reset(
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    _guard_demo_enabled()
    result = seed_demo(db, reset=True)
    if result["guardian"]["id"] != guardian.id:
        raise HTTPException(409, "데모 계정으로 로그인했을 때만 초기화할 수 있습니다.")
    return {"status": "reset", **result}


@router.get("/demo/config")
def demo_config():
    from app.services.demo_seed import demo_credentials

    return {
        "enabled": not settings.is_production,
        "credentials": demo_credentials(),
        "scenarios": list(SAMPLE_BY_SCENARIO.keys()),
    }
