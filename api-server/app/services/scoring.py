"""홈온큐 안심 점수(rule-based v1, PoC).

점수 산식은 임상 검증된 것이 아니라 시연용 규칙이다. 정책 버전을 함께 남겨
나중에 교체할 수 있게 하고, 앱에는 '참고용' 문구를 노출한다.
"""
from __future__ import annotations

from typing import Any

POLICY_VERSION = "homeonq-score-poc-v1"

RISK_STYLES = {
    "SAFE": {"label": "안심", "color": "#1E7B4C"},
    "WATCH": {"label": "주의", "color": "#A84D08"},
    "ALERT": {"label": "경계", "color": "#B42318"},
    "UNKNOWN": {"label": "확인 필요", "color": "#566079"},
}


def risk_style(risk_level: str) -> dict[str, str]:
    return RISK_STYLES.get(risk_level, RISK_STYLES["UNKNOWN"])


def compute_daily_score(
    metrics: dict[str, Any],
    baseline: dict[str, Any] | None = None,
    fall_count: int = 0,
) -> dict[str, Any]:
    """활동 지표와 낙상 건수로 0~100 안심 점수를 계산한다.

    metrics keys (없으면 계산에서 제외):
      steps, night_activity_minutes, toilet_visits, bedroom_minutes,
      inactivity_minutes, wandering_minutes, walking_minutes
    """
    score = 100
    factors: list[dict[str, Any]] = []

    def apply(code: str, label: str, delta: int, detail: str) -> None:
        nonlocal score
        if delta:
            score += delta
            factors.append({"code": code, "label": label, "delta": delta, "detail": detail})

    baseline = baseline or {}
    steps = metrics.get("steps")
    baseline_steps = baseline.get("steps")
    if steps is not None and baseline_steps:
        change = (steps - baseline_steps) / baseline_steps * 100
        if change <= -30:
            apply("STEPS_DROP", "보행량 감소", -15, f"평소보다 {abs(change):.0f}% 적게 걸었습니다")
        elif change <= -15:
            apply("STEPS_DROP", "보행량 감소", -8, f"평소보다 {abs(change):.0f}% 적게 걸었습니다")
        elif change >= 40:
            apply("STEPS_RISE", "보행량 증가", 2, f"평소보다 {change:.0f}% 많이 걸었습니다")

    night = metrics.get("night_activity_minutes")
    if night is not None:
        if night >= 60:
            apply("NIGHT_ACTIVITY", "야간 활동 증가", -10, f"야간 활동이 {night:.0f}분 감지되었습니다")
        elif night >= 30:
            apply("NIGHT_ACTIVITY", "야간 활동 증가", -5, f"야간 활동이 {night:.0f}분 감지되었습니다")

    inactivity = metrics.get("inactivity_minutes")
    if inactivity is not None and inactivity >= 240:
        apply("LONG_INACTIVITY", "장시간 무활동", -12, f"{inactivity / 60:.1f}시간 동안 움직임이 적었습니다")

    wandering = metrics.get("wandering_minutes")
    if wandering is not None and wandering >= 10:
        apply("WANDERING", "배회 패턴", -8, f"배회로 보이는 이동이 {wandering:.0f}분 있었습니다")

    if fall_count >= 2:
        apply("FALL_RECENT", "낙상 의심 반복", -35, f"낙상 의심 이벤트가 {fall_count}건 있습니다")
    elif fall_count == 1:
        apply("FALL_RECENT", "낙상 의심", -20, "낙상 의심 이벤트가 1건 있습니다")

    toilet = metrics.get("toilet_visits")
    if toilet is not None and toilet >= 8:
        apply("TOILET_FREQUENT", "화장실 이용 증가", -5, f"화장실 이용이 {toilet}회 감지되었습니다")

    score = max(0, min(100, round(score)))
    if score >= 80:
        risk_level = "SAFE"
    elif score >= 60:
        risk_level = "WATCH"
    else:
        risk_level = "ALERT"
    style = risk_style(risk_level)
    return {
        "score": score,
        "risk_level": risk_level,
        "risk_label": style["label"],
        "ui_color": style["color"],
        "factors": {"policy_version": POLICY_VERSION, "items": factors},
    }
