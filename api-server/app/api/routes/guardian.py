from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.db.session import get_db
from app.models import (
    BehaviorEvent, CameraDevice, DailyReport, FallEvent, FallSession, Guardian,
    GuardianSenior, Notification, Senior,
)
from app.schemas.guardian import DemoSimulationRequest, SeniorProfileUpdate
from app.services.auth import get_current_guardian, require_senior_access
from app.services.events import activity_label, create_suspected_fall, get_active_device
from app.services.reports import empty_report, report_detail
from app.services.scoring import POLICY_VERSION, compute_daily_score, risk_style

router = APIRouter(tags=["guardian"])


def _age(birth: date | None) -> int | None:
    if not birth:
        return None
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def _device_out(d: CameraDevice) -> dict:
    return {
        "device_id": d.device_id,
        "status": d.status,
        "last_seen_at": iso_utc(d.last_seen_at),
        "health_status": d.health_status,
        "health_metrics": d.health_metrics or {},
        "last_health_at": iso_utc(d.last_health_at),
    }


def _profile(db: Session, senior: Senior) -> dict:
    devices = db.scalars(
        select(CameraDevice).where(CameraDevice.senior_id == senior.id).order_by(CameraDevice.created_at)
    ).all()
    return {
        "id": senior.id,
        "display_name": senior.display_name,
        "birth_date": senior.birth_date,
        "age": _age(senior.birth_date),
        "gender": senior.gender,
        "height_cm": senior.height_cm,
        "weight_kg": senior.weight_kg,
        "medical_conditions": senior.medical_conditions or [],
        "photo_url": senior.photo_url,
        "emergency_contact": senior.emergency_contact,
        "memo": senior.memo,
        "is_active": senior.is_active,
        "devices": [_device_out(d) for d in devices],
    }


@router.get("/guardians/me/seniors")
def my_seniors(db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    rows = db.scalars(
        select(Senior)
        .join(GuardianSenior)
        .where(
            GuardianSenior.guardian_id == guardian.id,
            GuardianSenior.status == "active",
            Senior.is_active.is_(True),
        )
        .order_by(Senior.created_at)
    ).all()
    return {"items": [_profile(db, s) for s in rows]}


@router.get("/seniors/{senior_id}")
def senior_detail(senior_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    senior = require_senior_access(senior_id, guardian, db)
    return _profile(db, senior)


@router.patch("/seniors/{senior_id}")
def update_senior(
    senior_id: str,
    payload: SeniorProfileUpdate,
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    senior = require_senior_access(senior_id, guardian, db)
    changes = payload.model_dump(exclude_unset=True)
    if "display_name" in changes and not (changes["display_name"] or "").strip():
        raise HTTPException(422, "display_name cannot be empty")
    for field, value in changes.items():
        if field == "medical_conditions" and value is None:
            value = []
        setattr(senior, field, value)
    db.commit()
    db.refresh(senior)
    return _profile(db, senior)


@router.get("/seniors/{senior_id}/access")
def senior_access(senior_id: str, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    require_senior_access(senior_id, guardian, db)
    return {"senior_id": senior_id, "has_access": True}


@router.get("/seniors/{senior_id}/daily-reports/latest")
def latest_daily_report(
    senior_id: str,
    report_date: date | None = None,
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    require_senior_access(senior_id, guardian, db)
    if report_date:
        row = db.scalar(
            select(DailyReport).where(
                DailyReport.senior_id == senior_id, DailyReport.report_date == report_date
            )
        )
    else:
        row = db.scalar(
            select(DailyReport)
            .where(DailyReport.senior_id == senior_id)
            .order_by(desc(DailyReport.report_date))
        )
    if not row:
        return {"senior_id": senior_id, **empty_report(report_date), "policy_version": POLICY_VERSION}
    return {"senior_id": senior_id, **report_detail(row), "policy_version": POLICY_VERSION}


@router.get("/seniors/{senior_id}/daily-reports")
def daily_report_history(
    senior_id: str,
    start: date | None = None,
    end: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    require_senior_access(senior_id, guardian, db)
    stmt = select(DailyReport).where(DailyReport.senior_id == senior_id)
    if start:
        stmt = stmt.where(DailyReport.report_date >= start)
    if end:
        stmt = stmt.where(DailyReport.report_date <= end)
    rows = db.scalars(
        stmt.order_by(desc(DailyReport.report_date)).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [
            {
                "report_date": r.report_date.isoformat(),
                "score": r.score,
                "risk_level": r.risk_level,
                "risk_label": r.risk_label,
                "headline": r.headline,
                "source": r.source,
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
    }


def _fall_out(row: FallEvent, session: FallSession | None = None) -> dict:
    return {
        "kind": "fall",
        "id": row.id,
        "event_id": row.event_id,
        "title": "낙상 의심",
        "detail": (row.rationale or {}).get("reasoning", ""),
        "occurred_at": iso_utc(row.occurred_at),
        "status": row.event_status,
        "risk_level": row.severity,
        "confidence": row.confidence,
        "is_test": bool((row.rationale or {}).get("is_test") or ((session.metadata_json or {}).get("is_test") if session else False)),
    }


def _behavior_out(row: BehaviorEvent) -> dict:
    unit = (row.details or {}).get("unit") or {"WALKING": "걸음", "STEPS": "걸음", "TOILET_VISIT": "회",
            "NIGHT_ACTIVITY": "분", "BEDROOM_STAY": "분", "INACTIVE": "분", "WANDERING": "분",
            "ACTIVITY": "분"}.get(row.event_type, "")
    return {
        "kind": "behavior",
        "id": row.id,
        "event_id": row.id,
        "title": activity_label(row.event_type),
        "detail": (row.details or {}).get("note") or (row.details or {}).get("summary") or "",
        "occurred_at": iso_utc(row.occurred_at),
        "status": row.analysis_status,
        "risk_level": None,
        "confidence": row.data_quality,
        "value": row.event_value,
        "unit": unit,
        "activity_type": row.event_type,
    }


@router.get("/seniors/{senior_id}/events")
def event_timeline(
    senior_id: str,
    days: int = Query(7, ge=1, le=90),
    kind: str | None = Query(None, pattern="^(behavior|fall)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    require_senior_access(senior_id, guardian, db)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[dict] = []
    if kind in (None, "behavior"):
        rows = db.scalars(
            select(BehaviorEvent)
            .where(BehaviorEvent.senior_id == senior_id, BehaviorEvent.occurred_at >= since)
            .order_by(desc(BehaviorEvent.occurred_at))
            .limit(limit)
        ).all()
        items.extend(_behavior_out(r) for r in rows)
    if kind in (None, "fall"):
        rows = db.execute(
            select(FallEvent, FallSession)
            .join(FallSession, FallEvent.session_id == FallSession.id)
            .where(FallSession.senior_id == senior_id, FallEvent.occurred_at >= since)
            .order_by(desc(FallEvent.occurred_at))
            .limit(limit)
        ).all()
        items.extend(_fall_out(r, s) for r, s in rows)
    items.sort(key=lambda x: x["occurred_at"] or "", reverse=True)
    return {"items": items[:limit], "count": len(items[:limit]), "days": days}


@router.get("/seniors/{senior_id}/summary")
def senior_summary(
    senior_id: str,
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    """대시보드용 요약: 최근 리포트, 낙상 건수, 마지막 이벤트 시각."""
    require_senior_access(senior_id, guardian, db)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    fall_count = len(
        db.execute(
            select(FallEvent)
            .join(FallSession)
            .where(FallSession.senior_id == senior_id, FallEvent.occurred_at >= since)
        ).all()
    )
    last_behavior = db.scalar(
        select(BehaviorEvent)
        .where(BehaviorEvent.senior_id == senior_id)
        .order_by(desc(BehaviorEvent.occurred_at))
    )
    latest_report = db.scalar(
        select(DailyReport).where(DailyReport.senior_id == senior_id).order_by(desc(DailyReport.report_date))
    )
    pending = db.execute(
        select(Notification)
        .join(FallEvent, Notification.fall_event_id == FallEvent.id)
        .join(FallSession, FallEvent.session_id == FallSession.id)
        .where(
            Notification.recipient_id == guardian.id,
            Notification.acknowledged_at.is_(None),
            FallSession.senior_id == senior_id,
        )
    ).all()
    return {
        "senior_id": senior_id,
        "days": days,
        "fall_count": fall_count,
        "unacknowledged_alerts": len(pending),
        "last_behavior_at": iso_utc(last_behavior.occurred_at) if last_behavior else None,
        "latest_report": report_detail(latest_report) if latest_report else None,
    }


@router.post("/seniors/{senior_id}/test-fall", status_code=201)
def trigger_test_fall(
    senior_id: str,
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    """보호자 앱의 '낙상 테스트' 버튼. 실제 기기 없이 알림 흐름을 확인한다."""
    senior = require_senior_access(senior_id, guardian, db)
    device = get_active_device(db, senior.id)
    if not device:
        raise HTTPException(409, "등록된 카메라가 없어 테스트 낙상을 만들 수 없습니다.")
    now = datetime.now(timezone.utc)
    event, notified = create_suspected_fall(
        db,
        senior=senior,
        device=device,
        event_id=f"guardian-test-{uuid.uuid4()}",
        detected_at=now,
        confidence=0.99,
        risk_level="HIGH",
        reasoning="보호자 앱에서 실행한 낙상 알림 테스트입니다.",
        feature_summary={"source": "guardian-test-button"},
        metadata={"initiated_by": guardian.id},
        is_test=True,
    )
    return {
        "status": "stored",
        "event_id": event.event_id,
        "event_status": event.event_status,
        "notification_count": notified,
        "is_test": True,
    }


@router.get("/guardians/me/alerts")
def my_alerts(
    include_acknowledged: bool = False,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    stmt = (
        select(Notification, FallEvent, FallSession, Senior)
        .join(FallEvent, Notification.fall_event_id == FallEvent.id)
        .join(FallSession, FallEvent.session_id == FallSession.id)
        .join(Senior, FallSession.senior_id == Senior.id)
        .where(Notification.recipient_id == guardian.id)
        .order_by(desc(FallEvent.occurred_at))
        .limit(limit)
    )
    if not include_acknowledged:
        stmt = stmt.where(Notification.acknowledged_at.is_(None))
    rows = db.execute(stmt).all()
    return {
        "items": [
            {
                "notification_id": n.id,
                "alert_type": n.alert_type,
                "event_id": e.event_id,
                "senior_id": s.id,
                "senior_name": s.display_name,
                "occurred_at": iso_utc(e.occurred_at),
                "confidence": e.confidence,
                "risk_level": e.severity,
                "status": e.event_status,
                "is_test": bool((e.rationale or {}).get("is_test")),
                "reasoning": (e.rationale or {}).get("reasoning", ""),
                "acknowledged_at": iso_utc(n.acknowledged_at),
            }
            for n, e, se, s in rows
        ]
    }


@router.post("/seniors/{senior_id}/score-preview")
def score_preview(
    senior_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    guardian: Guardian = Depends(get_current_guardian),
):
    """산식 확인용(시연): 지표를 넣으면 점수 계산 결과를 돌려준다."""
    require_senior_access(senior_id, guardian, db)
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    baseline = payload.get("baseline", {}) if isinstance(payload, dict) else {}
    return compute_daily_score(metrics, baseline, int(payload.get("fall_count", 0)))
