import hashlib, json, math, uuid
from datetime import datetime, date, timezone, timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, desc
from sqlalchemy.orm import Session
from app.core.timeutil import iso_utc
from app.db.session import get_db
from app.models import (BehaviorEvent, SeniorBaseline, DailyScore, FallSession, FallEvent,
                        VideoClip, Notification, OutboxMessage, GuardianSenior)
from app.api.routes.devices import current_device
from app.models import CameraDevice, Guardian
from app.services.auth import get_current_guardian, require_senior_access

router = APIRouter(tags=["telemetry"])

class BehaviorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=36)
    captured_at: datetime
    activity_type: str = Field(min_length=1, max_length=50)
    # 범용 측정값/단위(예: 화장실 이용 8회, 무활동 300분). 없으면 기존 규칙으로 환산한다.
    event_value: float | None = None
    unit: str | None = Field(default=None, max_length=10)
    activity_duration_seconds: float | None = Field(default=None, ge=0)
    movement_level: float | None = None
    walking_distance: float | None = Field(default=None, ge=0)
    walking_steps: int | None = Field(default=None, ge=0)
    posture_type: str | None = None
    body_center_x: float | None = None
    body_center_y: float | None = None
    torso_angle: float | None = None
    movement_speed: float | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    data_quality: float | None = Field(default=None, ge=0, le=1)
    feature_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class BaselineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    captured_at: datetime
    walking_steps: int = Field(ge=0)
    activity_duration_seconds: float = Field(ge=0)
    walking_duration_seconds: float = Field(default=0, ge=0)
    inactive_duration_seconds: float = Field(default=0, ge=0)
    sleep_duration_seconds: float | None = Field(default=None, ge=0)
    data_quality: float = Field(ge=0, le=1)
    source_event_id: str = Field(min_length=1, max_length=128)

class FallIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=1, max_length=128)
    detected_at: datetime
    fall_suspected: bool
    confidence: float = Field(ge=0, le=1)
    risk_level: str = Field(default="UNKNOWN", max_length=20)
    reasoning: str = ""
    feature_summary: dict[str, Any] = Field(default_factory=dict)
    video_clip_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class FallPatch(BaseModel):
    status: str

class ClipIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    captured_at: datetime
    duration_seconds: float = Field(ge=0)
    storage_provider: str = "gcs"
    object_key: str = Field(min_length=1, max_length=1024)
    content_type: str = "video/mp4"
    file_size: int | None = Field(default=None, ge=0)
    checksum: str | None = None


def _aware(dt: datetime):
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise HTTPException(422, "Timestamp must include timezone")
    return dt.astimezone(timezone.utc)

def _payload_hash(data: dict):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()

def _event_detail(row: BehaviorEvent):
    return {"event_id": row.id, "senior_id": row.senior_id, "activity_type": row.event_type,
            "value": row.event_value, "unit": (row.details or {}).get("unit"),
            "captured_at": iso_utc(row.occurred_at), "data_quality": row.data_quality,
            "analysis_status": row.analysis_status, "details": row.details}

@router.post('/device/behavior-events', status_code=201)
def ingest_behavior(payload: BehaviorIn, device: CameraDevice = Depends(current_device), db: Session = Depends(get_db)):
    captured = _aware(payload.captured_at)
    data = payload.model_dump(mode="json")
    digest = _payload_hash(data)
    existing = db.get(BehaviorEvent, payload.event_id)
    if existing:
        if existing.details.get("payload_hash") != digest:
            raise HTTPException(409, "event_id already exists with different payload")
        return JSONResponse(status_code=200, content=jsonable_encoder({"status": "duplicate", **_event_detail(existing)}))
    details = data.copy(); details["payload_hash"] = digest; details["received_at"] = datetime.now(timezone.utc).isoformat(); details["device_id"] = device.device_id
    if payload.event_value is not None:
        value = float(payload.event_value)
    else:
        value = float(payload.walking_steps if payload.walking_steps is not None else payload.movement_level or 0)
    row = BehaviorEvent(id=payload.event_id, senior_id=device.senior_id, event_type=payload.activity_type,
        event_value=value, occurred_at=captured, data_quality=payload.data_quality if payload.data_quality is not None else payload.confidence,
        analysis_status="RECEIVED", details=details)
    db.add(row); device.last_seen_at = datetime.now(timezone.utc)
    try: db.commit()
    except Exception:
        db.rollback(); raise HTTPException(409, "Unable to store event")
    db.refresh(row)
    return {"status": "stored", **_event_detail(row)}

@router.get('/seniors/{senior_id}/behavior-events')
def list_behavior(senior_id: str, start: datetime | None = None, end: datetime | None = None,
                  activity_type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                  db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    stmt = select(BehaviorEvent).where(BehaviorEvent.senior_id == senior_id)
    if start: stmt = stmt.where(BehaviorEvent.occurred_at >= _aware(start))
    if end: stmt = stmt.where(BehaviorEvent.occurred_at <= _aware(end))
    if activity_type: stmt = stmt.where(BehaviorEvent.event_type == activity_type)
    rows = db.scalars(stmt.order_by(desc(BehaviorEvent.occurred_at)).offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [_event_detail(x) for x in rows], "page": page, "page_size": page_size}

@router.post('/device/baseline-data', status_code=202)
def ingest_baseline(payload: BaselineIn, device: CameraDevice = Depends(current_device), db: Session = Depends(get_db)):
    captured = _aware(payload.captured_at)
    # Baseline observations are deduplicated by source event id in the JSON records.
    current = db.scalar(select(SeniorBaseline).where(SeniorBaseline.senior_id == device.senior_id).order_by(desc(SeniorBaseline.baseline_version)))
    samples = list((current.baseline_data if current else {}).get("samples", []))
    if any(x.get("source_event_id") == payload.source_event_id for x in samples):
        return {"status": "duplicate", "baseline_status": current.learning_status if current else "COLLECTING"}
    sample = payload.model_dump(mode="json"); sample["captured_at"] = captured.isoformat(); samples.append(sample)
    days = sorted({datetime.fromisoformat(x["captured_at"]).date().isoformat() for x in samples})
    valid_days = len(days); status = "READY" if valid_days >= 3 else "COLLECTING"
    totals = {}
    for key in ("walking_steps", "activity_duration_seconds", "walking_duration_seconds", "inactive_duration_seconds", "sleep_duration_seconds"):
        vals = [x[key] for x in samples if x.get(key) is not None]
        totals[key] = sum(vals)/len(vals) if vals else None
    version = current.baseline_version if current else 1
    if current:
        current.observed_days = valid_days; current.learning_status = status; current.baseline_data = {"samples": samples, "averages": totals, "valid_days": days}
        current.data_quality = sum(x["data_quality"] for x in samples)/len(samples)
        if status == "READY" and not current.completed_at: current.completed_at = datetime.now(timezone.utc)
        row = current
    else:
        row = SeniorBaseline(id=str(uuid.uuid4()), senior_id=device.senior_id, baseline_version=version, learning_status=status,
            observed_days=valid_days, data_quality=sum(x["data_quality"] for x in samples)/len(samples),
            baseline_data={"samples": samples, "averages": totals, "valid_days": days}, started_at=captured,
            completed_at=datetime.now(timezone.utc) if status == "READY" else None)
        db.add(row)
    db.commit()
    return {"status": "accepted", "baseline_status": status, "observed_days": valid_days, "baseline_version": version}

@router.get('/seniors/{senior_id}/baseline')
@router.get('/seniors/{senior_id}/baseline/status')
def get_baseline(senior_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    row = db.scalar(select(SeniorBaseline).where(SeniorBaseline.senior_id == senior_id).order_by(desc(SeniorBaseline.baseline_version)))
    if not row: return {"baseline_status": "INSUFFICIENT_DATA", "observed_days": 0, "baseline": None}
    return {"baseline_status": row.learning_status, "observed_days": row.observed_days, "baseline_version": row.baseline_version,
            "baseline": row.baseline_data.get("averages") if row.learning_status == "READY" else None,
            "started_at": iso_utc(row.started_at), "completed_at": iso_utc(row.completed_at)}

@router.get('/seniors/{senior_id}/daily-score')
def latest_score(senior_id: str, score_date: date | None = None, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    target = score_date or date.today()
    row = db.scalar(select(DailyScore).where(DailyScore.senior_id == senior_id, DailyScore.score_date == target))
    baseline = db.scalar(select(SeniorBaseline).where(SeniorBaseline.senior_id == senior_id).order_by(desc(SeniorBaseline.baseline_version)))
    if row:
        return {"score": row.score, "risk_level": row.risk_level, "status": row.data_status, "calculated_at": iso_utc(row.calculated_at),
                "baseline_status": baseline.learning_status if baseline else "INSUFFICIENT_DATA", "policy_version": row.policy_version,
                "warning_reasons": row.influencing_factors, "data_quality": baseline.data_quality if baseline else None}
    return {"score": None, "risk_level": "UNKNOWN", "status": "UNKNOWN" if baseline else "DATA_INSUFFICIENT",
            "calculated_at": None, "baseline_status": baseline.learning_status if baseline else "INSUFFICIENT_DATA",
            "policy_version": "UNCONFIRMED", "activity_change_percent": None, "warning_reasons": [], "data_quality": baseline.data_quality if baseline else None}

@router.get('/seniors/{senior_id}/daily-scores')
def score_history(senior_id: str, start: date | None = None, end: date | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(30, ge=1, le=100), db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    stmt = select(DailyScore).where(DailyScore.senior_id == senior_id)
    if start: stmt = stmt.where(DailyScore.score_date >= start)
    if end: stmt = stmt.where(DailyScore.score_date <= end)
    rows = db.scalars(stmt.order_by(desc(DailyScore.score_date)).offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [{"date": r.score_date, "score": r.score, "risk_level": r.risk_level, "status": r.data_status, "policy_version": r.policy_version} for r in rows], "page": page, "page_size": page_size}

@router.post('/device/fall-events', status_code=201)
def ingest_fall(payload: FallIn, device: CameraDevice = Depends(current_device), db: Session = Depends(get_db)):
    detected = _aware(payload.detected_at)
    if not payload.fall_suspected:
        raise HTTPException(422, "Only suspected fall events may be submitted to this endpoint")
    existing = db.scalar(select(FallEvent).where(FallEvent.event_id == payload.event_id))
    if existing:
        if existing.session_id and existing.rationale.get("payload_hash") != _payload_hash(payload.model_dump(mode="json")):
            raise HTTPException(409, "event_id already exists with different payload")
        return JSONResponse(status_code=200, content={"status": "duplicate", "event_id": existing.event_id, "event_status": existing.event_status})
    session = FallSession(id=str(uuid.uuid4()), senior_id=device.senior_id, device_id=device.id, started_at=detected, status="SUSPECTED")
    db.add(session); db.flush()
    rationale = {"reasoning": payload.reasoning, "feature_summary": payload.feature_summary, "metadata": payload.metadata,
                 "payload_hash": _payload_hash(payload.model_dump(mode="json")), "received_at": datetime.now(timezone.utc).isoformat()}
    event = FallEvent(id=str(uuid.uuid4()), event_id=payload.event_id, session_id=session.id, event_status="SUSPECTED",
                      severity=payload.risk_level, confidence=payload.confidence, occurred_at=detected, rationale=rationale)
    db.add(event); db.flush()
    guardians = db.scalars(select(GuardianSenior).where(GuardianSenior.senior_id == device.senior_id, GuardianSenior.status == "active")).all()
    for rel in guardians:
        note = Notification(id=str(uuid.uuid4()), fall_event_id=event.id, recipient_id=rel.guardian_id, alert_type="FALL_SUSPECTED", status="PENDING")
        db.add(note); db.flush()
        db.add(OutboxMessage(id=str(uuid.uuid4()), topic="fall.notification", aggregate_id=note.id,
            payload={"notification_id": note.id, "event_id": payload.event_id, "guardian_id": rel.guardian_id}, status="PENDING"))
    device.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "stored", "event_id": event.event_id, "event_status": event.event_status, "notification_count": len(guardians)}

@router.get('/seniors/{senior_id}/fall-events')
def list_falls(senior_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    rows = db.scalars(select(FallEvent).join(FallSession).where(FallSession.senior_id == senior_id).order_by(desc(FallEvent.occurred_at)).offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [{"event_id": r.event_id, "event_status": r.event_status, "confidence": r.confidence, "detected_at": iso_utc(r.occurred_at), "risk_level": r.severity, "rationale": r.rationale} for r in rows], "page": page, "page_size": page_size}

@router.get('/seniors/{senior_id}/fall-events/{event_id}')
def fall_detail(senior_id: str, event_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    row = db.scalar(select(FallEvent).join(FallSession).where(FallSession.senior_id == senior_id, FallEvent.event_id == event_id))
    if not row: raise HTTPException(404, "Fall event not found")
    return {"event_id": row.event_id, "event_status": row.event_status, "confidence": row.confidence, "detected_at": iso_utc(row.occurred_at), "risk_level": row.severity, "rationale": row.rationale}

@router.patch('/seniors/{senior_id}/fall-events/{event_id}')
def update_fall(senior_id: str, event_id: str, payload: FallPatch, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    if payload.status not in {"CONFIRMED", "DISMISSED", "SUSPECTED"}: raise HTTPException(422, "Invalid event status")
    row = db.scalar(select(FallEvent).join(FallSession).where(FallSession.senior_id == senior_id, FallEvent.event_id == event_id))
    if not row: raise HTTPException(404, "Fall event not found")
    row.event_status = payload.status; db.commit()
    return {"event_id": row.event_id, "event_status": row.event_status}

@router.post('/device/video-clips', status_code=202)
def register_clip(payload: ClipIn, device: CameraDevice = Depends(current_device), db: Session = Depends(get_db)):
    event = db.scalar(select(FallEvent).join(FallSession).where(FallEvent.event_id == payload.event_id, FallSession.device_id == device.id))
    if not event: raise HTTPException(404, "Related fall event not found for this device")
    if db.scalar(select(VideoClip).where(VideoClip.storage_path == payload.object_key)):
        raise HTTPException(409, "Object key already registered")
    row = VideoClip(id=str(uuid.uuid4()), fall_event_id=event.id, storage_path=payload.object_key, upload_status="PENDING",
                    file_size=payload.file_size, duration=payload.duration_seconds, checksum=payload.checksum)
    db.add(row); db.commit()
    return {"clip_id": row.id, "upload_status": "PENDING", "verification_required": True, "storage_provider": payload.storage_provider,
            "content_type": payload.content_type, "captured_at": _aware(payload.captured_at)}

@router.get('/seniors/{senior_id}/video-clips')
def list_clips(senior_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    rows = db.scalars(select(VideoClip).join(FallEvent).join(FallSession).where(FallSession.senior_id == senior_id).order_by(desc(VideoClip.created_at))).all()
    return {"items": [{"clip_id": r.id, "event_id": r.fall_event_id, "object_key": r.storage_path, "upload_status": r.upload_status, "file_size": r.file_size, "duration_seconds": r.duration, "checksum": r.checksum} for r in rows]}

@router.get('/guardians/me/notifications')
def notifications(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    rows = db.scalars(select(Notification).where(Notification.recipient_id == guardian.id).order_by(desc(Notification.created_at)).offset((page-1)*page_size).limit(page_size)).all()
    return {"items": [{"id": n.id, "fall_event_id": n.fall_event_id, "alert_type": n.alert_type, "status": n.status, "acknowledged_at": iso_utc(n.acknowledged_at)} for n in rows], "page": page, "page_size": page_size}

@router.post('/guardians/me/notifications/{notification_id}/acknowledge')
def acknowledge(notification_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    row = db.scalar(select(Notification).where(Notification.id == notification_id, Notification.recipient_id == guardian.id))
    if not row: raise HTTPException(404, "Notification not found")
    row.acknowledged_at = datetime.now(timezone.utc); db.commit()
    return {"id": row.id, "acknowledged_at": iso_utc(row.acknowledged_at)}

