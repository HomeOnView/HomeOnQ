"""낙상 이벤트 생성 공용 로직.

기기(카메라) API, 보호자 앱의 '낙상 테스트', 웹 데모 시뮬레이션이 같은
트랜잭션 규칙(세션 + 이벤트 + 알림 + Outbox)을 쓰도록 한 곳에 모은다.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CameraDevice, FallEvent, FallSession, GuardianSenior, Notification, OutboxMessage,
    Senior,
)


def payload_hash(data: dict) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def get_active_device(db: Session, senior_id: str) -> CameraDevice | None:
    return db.scalar(
        select(CameraDevice)
        .where(CameraDevice.senior_id == senior_id, CameraDevice.status == "active")
        .order_by(CameraDevice.created_at)
    )


def create_suspected_fall(
    db: Session,
    *,
    senior: Senior,
    device: CameraDevice,
    event_id: str,
    detected_at: datetime,
    confidence: float,
    risk_level: str,
    reasoning: str,
    feature_summary: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    digest: str | None = None,
    is_test: bool = False,
    commit: bool = True,
) -> tuple[FallEvent, int]:
    """낙상 의심 이벤트를 저장하고 보호자 알림을 만든다."""
    session = FallSession(
        id=str(uuid.uuid4()),
        senior_id=senior.id,
        device_id=device.id,
        started_at=detected_at,
        status="SUSPECTED",
        metadata_json={"is_test": is_test, "source": "guardian-test" if is_test else "pipeline"},
    )
    db.add(session)
    db.flush()
    rationale = {
        "reasoning": reasoning,
        "feature_summary": feature_summary or {},
        "metadata": metadata or {},
        "payload_hash": digest or payload_hash({"event_id": event_id, "detected_at": detected_at.isoformat()}),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "is_test": is_test,
    }
    event = FallEvent(
        id=str(uuid.uuid4()),
        event_id=event_id,
        session_id=session.id,
        event_status="SUSPECTED",
        severity=risk_level,
        confidence=confidence,
        occurred_at=detected_at,
        rationale=rationale,
    )
    db.add(event)
    db.flush()
    relations = db.scalars(
        select(GuardianSenior).where(
            GuardianSenior.senior_id == senior.id, GuardianSenior.status == "active"
        )
    ).all()
    for rel in relations:
        note = Notification(
            id=str(uuid.uuid4()),
            fall_event_id=event.id,
            recipient_id=rel.guardian_id,
            alert_type="FALL_TEST" if is_test else "FALL_SUSPECTED",
            status="PENDING",
        )
        db.add(note)
        db.flush()
        db.add(
            OutboxMessage(
                id=str(uuid.uuid4()),
                topic="fall.notification",
                aggregate_id=note.id,
                payload={
                    "notification_id": note.id,
                    "event_id": event.event_id,
                    "guardian_id": rel.guardian_id,
                    "is_test": is_test,
                },
                status="PENDING",
            )
        )
    device.last_seen_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
    return event, len(relations)


ACTIVITY_LABELS = {
    "WALKING": ("보행", "걸음"),
    "STEPS": ("보행", "걸음"),
    "NIGHT_ACTIVITY": ("야간 활동", "분"),
    "TOILET_VISIT": ("화장실 이용", "회"),
    "BEDROOM_STAY": ("침실 체류", "분"),
    "INACTIVE": ("장시간 무활동", "분"),
    "WANDERING": ("배회", "분"),
    "POSTURE": ("자세", ""),
    "ACTIVITY": ("활동", "분"),
}


def activity_label(event_type: str) -> str:
    return ACTIVITY_LABELS.get(event_type, (event_type, ""))[0]
