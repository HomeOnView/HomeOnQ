"""일일 리포트 저장·조회 공용 로직 (기기 API와 데모 시뮬레이션이 함께 사용)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import iso_utc
from app.models import DailyReport, Senior
from app.schemas.guardian import DailyReportIn


def upsert_daily_report(db: Session, senior: Senior, payload: DailyReportIn) -> tuple[DailyReport, str]:
    """(senior_id, report_date) 기준 upsert. 반환값은 (행, 'stored'|'updated')."""
    row = db.scalar(
        select(DailyReport).where(
            DailyReport.senior_id == senior.id,
            DailyReport.report_date == payload.report_date,
        )
    )
    status = "updated" if row else "stored"
    generated_at = payload.generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    if row is None:
        row = DailyReport(id=str(uuid.uuid4()), senior_id=senior.id, report_date=payload.report_date)
        db.add(row)
    row.score = payload.score
    row.risk_level = payload.risk_level
    row.risk_label = payload.risk_label
    row.ui_color = payload.ui_color
    row.headline = payload.headline
    row.narrative = payload.narrative
    row.summary = payload.summary
    row.factors = payload.factors
    row.data_status = payload.data_status
    row.source = payload.source
    row.model_name = payload.model_name
    row.event_count = payload.event_count
    row.generated_at = generated_at
    db.commit()
    db.refresh(row)
    return row, status


def report_detail(row: DailyReport) -> dict:
    return {
        "report_date": row.report_date.isoformat(),
        "score": row.score,
        "risk_level": row.risk_level,
        "risk_label": row.risk_label,
        "ui_color": row.ui_color,
        "headline": row.headline,
        "narrative": row.narrative,
        "summary": row.summary,
        "factors": row.factors,
        "data_status": row.data_status,
        "source": row.source,
        "model_name": row.model_name,
        "event_count": row.event_count,
        "generated_at": iso_utc(row.generated_at),
    }


def empty_report(report_date: date | None = None) -> dict:
    target = report_date or date.today()
    return {
        "report_date": target.isoformat(),
        "score": None,
        "risk_level": "UNKNOWN",
        "risk_label": "데이터 수집 중",
        "ui_color": "#566079",
        "headline": "아직 오늘의 리포트가 도착하지 않았습니다",
        "narrative": "카메라 분석이 시작되면 오늘의 활동과 안심 점수가 이곳에 표시됩니다.",
        "summary": {},
        "factors": {"policy_version": None, "items": []},
        "data_status": "DATA_INSUFFICIENT",
        "source": None,
        "model_name": None,
        "event_count": 0,
        "generated_at": None,
    }
