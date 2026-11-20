import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.timeutil import iso_utc
from app.db.session import get_db
from app.models import CameraDevice, Guardian, Senior, GuardianSenior
from app.schemas.auth import DeviceCreate, DeviceResponse, DeviceIssuedResponse
from app.services.auth import get_current_guardian, require_senior_access, generate_device_token, hash_token, get_current_device

router = APIRouter(tags=['devices'])

def _device_out(d):
    return {'id': d.id, 'device_id': d.device_id, 'senior_id': d.senior_id, 'status': d.status, 'last_seen_at': iso_utc(d.last_seen_at)}

@router.post('/guardians/me/devices', response_model=DeviceIssuedResponse, status_code=201)
def register_device(payload: DeviceCreate, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(payload.senior_id, guardian, db)
    if db.scalar(select(CameraDevice).where(CameraDevice.device_id == payload.device_id)):
        raise HTTPException(409, 'Device ID already registered')
    token = generate_device_token()
    d = CameraDevice(id=str(uuid.uuid4()), device_id=payload.device_id, senior_id=payload.senior_id, token_hash=hash_token(token), status='active')
    db.add(d); db.commit(); db.refresh(d)
    return {**_device_out(d), 'device_token': token}

@router.get('/guardians/me/devices', response_model=list[DeviceResponse])
def list_devices(db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    rows = db.execute(select(CameraDevice).join(GuardianSenior, GuardianSenior.senior_id == CameraDevice.senior_id).where(GuardianSenior.guardian_id == guardian.id, GuardianSenior.status == 'active')).scalars().all()
    return [_device_out(x) for x in rows]

@router.post('/guardians/me/devices/{device_id}/rotate-key')
def rotate_key(device_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    d = db.scalar(select(CameraDevice).join(GuardianSenior, GuardianSenior.senior_id == CameraDevice.senior_id).where(CameraDevice.device_id == device_id, GuardianSenior.guardian_id == guardian.id, GuardianSenior.status == 'active'))
    if not d: raise HTTPException(404, 'Device not found')
    token = generate_device_token(); d.token_hash = hash_token(token); d.token_rotated_at = datetime.now(timezone.utc)
    db.commit()
    return {'device_id': d.device_id, 'device_token': token}

@router.post('/guardians/me/devices/{device_id}/revoke', status_code=204)
def revoke_device(device_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    d = db.scalar(select(CameraDevice).join(GuardianSenior, GuardianSenior.senior_id == CameraDevice.senior_id).where(CameraDevice.device_id == device_id, GuardianSenior.guardian_id == guardian.id, GuardianSenior.status == 'active'))
    if not d: raise HTTPException(404, 'Device not found')
    d.status = 'revoked'; db.commit()

def current_device(x_device_token: str | None = Header(default=None, alias='X-Device-Token'), db: Session = Depends(get_db)):
    return get_current_device(x_device_token, db)

@router.get('/device/me')
def device_me(d: CameraDevice = Depends(current_device)):
    return _device_out(d)

class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: str | None = Field(default=None, max_length=30)
    metrics: dict[str, Any] = Field(default_factory=dict)


@router.post('/device/heartbeat')
def heartbeat(payload: HeartbeatIn | None = None, d: CameraDevice = Depends(current_device), db: Session = Depends(get_db)):
    d.last_seen_at = datetime.now(timezone.utc)
    if payload and payload.status:
        # 엣지 HealthMonitor 상태(HEALTHY/CAMERA_OFFLINE/...)를 마지막 값으로 보관한다.
        d.health_status = payload.status
        d.health_metrics = payload.metrics or {}
        d.last_health_at = datetime.now(timezone.utc)
    db.commit()
    return {'status': 'ok', 'device_id': d.device_id, 'last_seen_at': iso_utc(d.last_seen_at),
            'health_status': d.health_status}
