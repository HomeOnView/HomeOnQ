"""기기(카메라 엣지) 전용 엔드포인트: 안심 리포트 수신."""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CameraDevice, Senior
from app.schemas.guardian import DailyReportIn
from app.services.auth import get_current_device
from app.services.reports import report_detail, upsert_daily_report

router = APIRouter(tags=["telemetry-reports"])


def current_device(
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    db: Session = Depends(get_db),
) -> CameraDevice:
    return get_current_device(x_device_token, db)


@router.post("/device/daily-reports", status_code=201)
def ingest_daily_report(
    payload: DailyReportIn,
    db: Session = Depends(get_db),
    device: CameraDevice = Depends(current_device),
):
    senior = db.get(Senior, device.senior_id)
    row, status = upsert_daily_report(db, senior, payload)
    return {"status": status, "report": report_detail(row)}
