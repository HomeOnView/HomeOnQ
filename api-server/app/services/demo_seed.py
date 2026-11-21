"""시연용 데모 데이터(보호자 1명 · 어르신 1명 · 카메라 2대 · 기준선 · 오늘 리포트).

`scripts/seed.py`와 웹앱의 '데모 초기화'가 같은 함수를 쓴다.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    BehaviorEvent, CameraDevice, DailyReport, FallEvent, FallSession, Guardian,
    GuardianSenior, Notification, OutboxMessage, Senior, SeniorBaseline, VideoClip,
)
from app.services.auth import hash_password, hash_token
from app.services.report_text import compose_narrative, compose_summary
from app.services.scoring import compute_daily_score

try:  # 한국 시간 기준으로 데모 날짜를 만든다.
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover - tz database 없는 극단 환경
    KST = timezone(timedelta(hours=9))

DEMO_GUARDIAN_EMAIL = "demo@homeonq.kr"
DEMO_GUARDIAN_PASSWORD = "homeonq-demo-2026"
DEMO_SENIOR_NAME = "강O순 어르신"
DEMO_SENIOR_BIRTH = "1951-03-12"
DEMO_DEVICE_ID = "TAPO-C225-LIVING"
DEMO_DEVICE_TOKEN = "dev-device-token-homeonq-0001"
DEMO_EDGE_DEVICE_ID = "DEMO-EDGE-01"
DEMO_EDGE_TOKEN = "demo-edge-token-homeonq-0001"

DEMO_BASELINE = {"steps": 4100, "walking_minutes": 62, "night_activity_minutes": 18}
DEMO_METRICS = {
    "steps": 3215,
    "night_activity_minutes": 55,
    "toilet_visits": 8,
    "bedroom_minutes": 480,
    "inactivity_minutes": 300,
    "walking_minutes": 48,
}


def _now_kst() -> datetime:
    return datetime.now(KST)


def _today_start_utc() -> datetime:
    now = _now_kst()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


def ensure_guardian(db: Session) -> Guardian:
    guardian = db.scalar(select(Guardian).where(Guardian.email == DEMO_GUARDIAN_EMAIL))
    if guardian:
        return guardian
    guardian = Guardian(
        id=str(uuid.uuid4()),
        email=DEMO_GUARDIAN_EMAIL,
        password_hash=hash_password(DEMO_GUARDIAN_PASSWORD),
        is_active=True,
    )
    db.add(guardian)
    db.commit()
    db.refresh(guardian)
    return guardian


def ensure_senior(db: Session, guardian: Guardian) -> Senior:
    senior = db.scalar(select(Senior).where(Senior.display_name == DEMO_SENIOR_NAME))
    if not senior:
        senior = Senior(
            id=str(uuid.uuid4()),
            display_name=DEMO_SENIOR_NAME,
            birth_date=datetime.strptime(DEMO_SENIOR_BIRTH, "%Y-%m-%d").date(),
            gender="여성",
            height_cm=160.0,
            weight_kg=52.0,
            medical_conditions=["당뇨", "고혈압", "척추측만증"],
            # 프로필 사진은 웹앱에 포함된 픽셀화 이미지(webapp/assets/senior-profile.jpg)를 쓴다.
            photo_url=None,
            emergency_contact="010-0000-0000",
            memo="분당 자택 거실 카메라(Tapo C225)로 관찰 중",
            is_active=True,
        )
        db.add(senior)
        db.commit()
        db.refresh(senior)
    relation = db.scalar(
        select(GuardianSenior).where(
            GuardianSenior.guardian_id == guardian.id, GuardianSenior.senior_id == senior.id
        )
    )
    if not relation:
        db.add(
            GuardianSenior(
                id=str(uuid.uuid4()),
                guardian_id=guardian.id,
                senior_id=senior.id,
                permission_role="owner",
                status="active",
            )
        )
        db.commit()
    return senior


def _upsert_device(db: Session, senior: Senior, device_id: str, token: str, status: str = "active") -> CameraDevice:
    device = db.scalar(select(CameraDevice).where(CameraDevice.device_id == device_id))
    if not device:
        device = CameraDevice(
            id=str(uuid.uuid4()),
            device_id=device_id,
            senior_id=senior.id,
            token_hash=hash_token(token),
            status=status,
            health_status="HEALTHY",
            health_metrics={"fps": 15.0, "source": "demo"},
            last_health_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(device)
    else:
        # 데모 계정은 토큰을 고정값으로 다시 맞춰 시연 스크립트가 항상 동작하게 한다.
        device.token_hash = hash_token(token)
        device.senior_id = senior.id
        device.status = status
    db.commit()
    db.refresh(device)
    return device


def ensure_devices(db: Session, senior: Senior) -> tuple[CameraDevice, CameraDevice]:
    return (
        _upsert_device(db, senior, DEMO_DEVICE_ID, DEMO_DEVICE_TOKEN),
        _upsert_device(db, senior, DEMO_EDGE_DEVICE_ID, DEMO_EDGE_TOKEN),
    )


def reset_demo_activity(db: Session, senior: Senior) -> None:
    """행동/낙상/리포트 데이터만 지운다(프로필·기기·기준선 유지)."""
    session_ids = [r.id for r in db.scalars(
        select(FallSession).where(FallSession.senior_id == senior.id)
    ).all()]
    fall_ids = [r.id for r in db.scalars(
        select(FallEvent).where(FallEvent.session_id.in_(session_ids))
    ).all()] if session_ids else []
    note_ids = [r.id for r in db.scalars(
        select(Notification).where(Notification.fall_event_id.in_(fall_ids))
    ).all()] if fall_ids else []
    if fall_ids:
        db.execute(delete(VideoClip).where(VideoClip.fall_event_id.in_(fall_ids)))
    if note_ids:
        db.execute(delete(OutboxMessage).where(OutboxMessage.aggregate_id.in_(note_ids)))
        db.execute(delete(Notification).where(Notification.id.in_(note_ids)))
    if fall_ids:
        db.execute(delete(FallEvent).where(FallEvent.id.in_(fall_ids)))
    if session_ids:
        db.execute(delete(FallSession).where(FallSession.id.in_(session_ids)))
    db.execute(delete(BehaviorEvent).where(BehaviorEvent.senior_id == senior.id))
    db.execute(delete(DailyReport).where(DailyReport.senior_id == senior.id))
    db.commit()


def ensure_baseline(db: Session, senior: Senior) -> SeniorBaseline:
    baseline = db.scalar(
        select(SeniorBaseline)
        .where(SeniorBaseline.senior_id == senior.id)
        .order_by(SeniorBaseline.baseline_version.desc())
    )
    if baseline:
        return baseline
    baseline = SeniorBaseline(
        id=str(uuid.uuid4()),
        senior_id=senior.id,
        baseline_version=1,
        learning_status="READY",
        observed_days=7,
        data_quality=0.93,
        baseline_data={
            "averages": DEMO_BASELINE,
            "valid_days": [(_today_start_utc() - timedelta(days=7 - i)).date().isoformat() for i in range(7)],
            "samples": [],
            "source": "demo-seed",
        },
        started_at=_today_start_utc() - timedelta(days=7),
        completed_at=_today_start_utc() - timedelta(hours=1),
    )
    db.add(baseline)
    db.commit()
    db.refresh(baseline)
    return baseline


def _behavior(db: Session, senior: Senior, event_type: str, value: float, occurred_at: datetime, note: str) -> None:
    existing = db.scalar(
        select(BehaviorEvent).where(
            BehaviorEvent.senior_id == senior.id,
            BehaviorEvent.event_type == event_type,
            BehaviorEvent.occurred_at == occurred_at,
        )
    )
    if existing:
        return
    db.add(
        BehaviorEvent(
            id=str(uuid.uuid4()),
            senior_id=senior.id,
            event_type=event_type,
            event_value=float(value),
            baseline_value=float(DEMO_BASELINE.get("steps", 0)) if event_type == "WALKING" else None,
            deviation_percent=(
                round((value - DEMO_BASELINE["steps"]) / DEMO_BASELINE["steps"] * 100, 1)
                if event_type == "WALKING" else None
            ),
            occurred_at=occurred_at,
            data_quality=0.92,
            analysis_status="ANALYZED",
            details={"note": note, "source": "demo-seed"},
        )
    )


def seed_daily_events(db: Session, senior: Senior) -> None:
    """오늘 하루 이벤트를 '지금' 기준 과거 시각으로 배치한다.

    시드 시각이 미래가 되면 앱 이벤트 목록이 이상해지므로, 하루 시작과 현재 사이로
    각 시각을 제한한다.
    """
    start = _today_start_utc()
    now = datetime.now(timezone.utc)
    earliest = start + timedelta(minutes=30)

    def at(delta: timedelta) -> datetime:
        return max(earliest, min(now - timedelta(minutes=5), now - delta))

    _behavior(db, senior, "NIGHT_ACTIVITY", 55, at(timedelta(minutes=7 * 60 + 30)), "새벽 화장실 이동 포함")
    _behavior(db, senior, "WALKING", 3215, at(timedelta(hours=3)), "오전 산책과 집안 이동")
    _behavior(db, senior, "INACTIVE", 300, at(timedelta(hours=2)), "오후 소파에서 5시간 무활동")
    _behavior(db, senior, "TOILET_VISIT", 8, at(timedelta(hours=1)), "하루 화장실 이용 8회")
    _behavior(db, senior, "BEDROOM_STAY", 480, at(timedelta(minutes=40)), "침실 체류 8시간")
    db.commit()


def seed_past_fall(db: Session, senior: Senior, device: CameraDevice) -> None:
    """이틀 전 '확인 완료'된 낙상 이벤트(이벤트 목록 시연용)."""
    existing = db.scalar(
        select(FallEvent).where(FallEvent.event_id == "demo-past-fall-001")
    )
    if existing:
        return
    occurred = _today_start_utc() - timedelta(days=2, hours=-3)
    session = FallSession(
        id=str(uuid.uuid4()),
        senior_id=senior.id,
        device_id=device.id,
        started_at=occurred,
        status="CLOSED",
        metadata_json={"is_test": False, "source": "demo-seed"},
    )
    db.add(session)
    db.flush()
    event = FallEvent(
        id=str(uuid.uuid4()),
        event_id="demo-past-fall-001",
        session_id=session.id,
        event_status="CONFIRMED",
        severity="MEDIUM",
        confidence=0.81,
        occurred_at=occurred,
        rationale={
            "reasoning": "거실에서 앉은 자세로 낮아진 뒤 20초간 움직임이 없었습니다.",
            "feature_summary": {"torso_tilt_deg": 71, "drop_speed": 0.34},
            "is_test": False,
        },
    )
    db.add(event)
    db.flush()
    guardians = db.scalars(
        select(GuardianSenior).where(GuardianSenior.senior_id == senior.id, GuardianSenior.status == "active")
    ).all()
    for rel in guardians:
        db.add(
            Notification(
                id=str(uuid.uuid4()),
                fall_event_id=event.id,
                recipient_id=rel.guardian_id,
                alert_type="FALL_SUSPECTED",
                status="SENT",
                sent_at=occurred,
                acknowledged_at=occurred + timedelta(minutes=6),
            )
        )
    db.commit()


def seed_today_report(db: Session, senior: Senior) -> DailyReport:
    score = compute_daily_score(DEMO_METRICS, DEMO_BASELINE, fall_count=0)
    summary = compose_summary(DEMO_METRICS, DEMO_BASELINE)
    today_kst = _now_kst().date()
    headline, narrative = compose_narrative(senior.display_name, today_kst, DEMO_METRICS, score["factors"], 0)
    report = db.scalar(
        select(DailyReport).where(DailyReport.senior_id == senior.id, DailyReport.report_date == today_kst)
    )
    if not report:
        report = DailyReport(id=str(uuid.uuid4()), senior_id=senior.id, report_date=today_kst)
        db.add(report)
    report.score = score["score"]
    report.risk_level = score["risk_level"]
    report.risk_label = score["risk_label"]
    report.ui_color = score["ui_color"]
    report.headline = headline
    report.narrative = narrative
    report.summary = summary
    report.factors = score["factors"]
    report.data_status = "FINAL"
    report.source = "demo-seed"
    report.model_name = None
    report.event_count = 5
    report.generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(report)
    return report


def seed_demo(db: Session, reset: bool = False) -> dict[str, Any]:
    guardian = ensure_guardian(db)
    senior = ensure_senior(db, guardian)
    if reset:
        reset_demo_activity(db, senior)
    living, edge = ensure_devices(db, senior)
    ensure_baseline(db, senior)
    seed_daily_events(db, senior)
    seed_past_fall(db, senior, living)
    report = seed_today_report(db, senior)
    return {
        "guardian": {"email": guardian.email, "id": guardian.id},
        "senior": {"id": senior.id, "display_name": senior.display_name},
        "devices": [
            {"device_id": living.device_id, "token": DEMO_DEVICE_TOKEN},
            {"device_id": edge.device_id, "token": DEMO_EDGE_TOKEN},
        ],
        "report": {
            "report_date": report.report_date.isoformat(),
            "score": report.score,
            "risk_level": report.risk_level,
            "risk_label": report.risk_label,
        },
        "reset": reset,
    }


def demo_credentials() -> dict[str, str]:
    return {
        "email": DEMO_GUARDIAN_EMAIL,
        "password": DEMO_GUARDIAN_PASSWORD,
        "senior_name": DEMO_SENIOR_NAME,
    }
