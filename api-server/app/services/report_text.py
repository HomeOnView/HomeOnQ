"""시연용 한국어 안심 리포트 문장 생성 (서버 측).

엣지 파이프라인의 규칙 기반 생성기(`camera-analysis/onview/report_generator.py`)와
같은 어조를 유지하되, 서버에서 시드/샘플 데이터를 만들 때 쓴다.
"""
from __future__ import annotations

from datetime import date
from typing import Any


def _num(value: Any, unit: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.0f}{unit}" if value.is_integer() else f"{value:,.1f}{unit}"
    return f"{value:,}{unit}"


def compose_narrative(
    senior_name: str,
    report_date: date,
    metrics: dict[str, Any],
    factors: dict[str, Any],
    fall_count: int = 0,
) -> tuple[str, str]:
    """(headline, narrative)를 돌려준다."""
    name = senior_name.replace(" 어르신", "")
    items = (factors or {}).get("items", [])
    scored = [f for f in items if f.get("delta", 0) < 0]

    if fall_count:
        headline = f"{name} 어르신 댁에서 낙상 의심 신호가 감지되었습니다"
    elif scored:
        headline = f"{name} 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다"
    else:
        headline = f"{name} 어르신, 오늘도 평안한 하루를 보내셨습니다"

    lines: list[str] = []
    lines.append(f"{report_date.month}월 {report_date.day}일 {name} 어르신의 하루를 정리했습니다.")

    parts: list[str] = []
    if metrics.get("steps") is not None:
        parts.append(f"걸음 수 {_num(metrics['steps'], '걸음')}")
    if metrics.get("night_activity_minutes") is not None:
        parts.append(f"야간 활동 {_num(metrics['night_activity_minutes'], '분')}")
    if metrics.get("toilet_visits") is not None:
        parts.append(f"화장실 이용 {_num(metrics['toilet_visits'], '회')}")
    if metrics.get("bedroom_minutes") is not None:
        parts.append(f"침실 체류 {_num(metrics['bedroom_minutes'], '분')}")
    if parts:
        lines.append("오늘은 " + ", ".join(parts) + "이 확인되었습니다.")

    if fall_count:
        lines.append(
            f"낙상 의심 이벤트가 {fall_count}건 감지되어 알림을 보냈습니다. "
            "어르신의 상태를 직접 확인해 주시고, 괜찮으시면 알림을 '확인'으로 바꿔 주세요."
        )
    elif scored:
        detail = ", ".join(f["detail"] for f in scored[:3])
        lines.append(f"평소와 비교해 주의할 점이 있습니다. {detail}.")
        lines.append("식사와 수분 섭취를 권하고, 다음 날 활동이 이어지는지 함께 살펴봐 주세요.")
    else:
        lines.append("평소와 크게 다르지 않은 하루였습니다. 특별히 걱정하실 부분은 없습니다.")

    lines.append("이 리포트는 카메라 관절 좌표 분석을 바탕으로 만든 참고 자료이며, 진단을 대신하지 않습니다.")
    return headline, "\n\n".join(lines)


def compose_summary(
    metrics: dict[str, Any], baseline: dict[str, Any] | None = None
) -> dict[str, Any]:
    """앱 카드에 표시할 요약 수치(라벨/값/단위/증감)."""
    baseline = baseline or {}
    rows = []
    steps = metrics.get("steps")
    base_steps = baseline.get("steps")
    if steps is not None:
        delta = None
        if base_steps:
            delta = round((steps - base_steps) / base_steps * 100)
        rows.append({"key": "steps", "label": "보행", "value": steps, "unit": "걸음", "delta_percent": delta})
    if metrics.get("night_activity_minutes") is not None:
        rows.append({
            "key": "night_activity", "label": "야간 활동",
            "value": metrics["night_activity_minutes"], "unit": "분",
            "delta_percent": None, "detail": "야간 시간대 감지",
        })
    if metrics.get("toilet_visits") is not None:
        rows.append({"key": "toilet", "label": "화장실 이용", "value": metrics["toilet_visits"], "unit": "회"})
    if metrics.get("bedroom_minutes") is not None:
        rows.append({"key": "bedroom", "label": "침실 체류", "value": metrics["bedroom_minutes"], "unit": "분"})
    if metrics.get("inactivity_minutes") is not None:
        rows.append({"key": "inactivity", "label": "최장 무활동", "value": metrics["inactivity_minutes"], "unit": "분"})
    return {
        "metrics": metrics,
        "baseline": baseline,
        "rows": rows,
        "fall_count": metrics.get("fall_count", 0),
    }
