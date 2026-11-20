"""안심 일일 리포트 문장 생성.

GEMINI_API_KEY가 있으면 Gemini REST API로 문장을 만들고, 없거나 실패하면
한국어 규칙 기반 생성기로 자동 폴백한다(키 없이도 100% 동작).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from .config import CONFIG, Config

logger = logging.getLogger(__name__)
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _fmt(value: Any, unit: str = "") -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.0f}{unit}" if value.is_integer() else f"{value:,.1f}{unit}"
    return f"{value:,}{unit}"


def rule_headline(
    senior_name: str, metrics: dict, factors: dict, fall_count: int, risk_level: str | None = None
) -> str:
    name = senior_name.replace(" 어르신", "")
    items = (factors or {}).get("items", [])
    scored = [f for f in items if f.get("delta", 0) < 0]
    if fall_count:
        return f"{name} 어르신 댁에서 낙상 의심 신호가 감지되었습니다"
    if any(f.get("code") == "LONG_INACTIVITY" for f in scored):
        return f"{name} 어르신, 오랜 시간 움직임이 적었습니다"
    if any(f.get("code") == "WANDERING" for f in scored):
        return f"{name} 어르신, 야간 배회가 조금 있었습니다"
    if risk_level == "SAFE":
        return f"{name} 어르신, 오늘도 평안한 하루를 보내셨습니다"
    if scored:
        return f"{name} 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다"
    return f"{name} 어르신, 오늘도 평안한 하루를 보내셨습니다"


def rule_narrative(
    senior_name: str,
    report_date: date,
    metrics: dict,
    factors: dict,
    events: list[dict] | None = None,
    fall_count: int = 0,
) -> str:
    name = senior_name.replace(" 어르신", "")
    events = events or []
    lines = [f"{report_date.month}월 {report_date.day}일 {name} 어르신의 하루를 정리했습니다."]

    parts = []
    if metrics.get("steps") is not None:
        parts.append(f"걸음 수 {_fmt(metrics['steps'], '걸음')}")
    if metrics.get("night_activity_minutes") is not None:
        parts.append(f"야간 활동 {_fmt(metrics['night_activity_minutes'], '분')}")
    if metrics.get("toilet_visits") is not None:
        parts.append(f"화장실 이용 {_fmt(metrics['toilet_visits'], '회')}")
    if metrics.get("bedroom_minutes") is not None:
        parts.append(f"침실 체류 {_fmt(metrics['bedroom_minutes'], '분')}")
    if parts:
        lines.append("오늘은 " + ", ".join(parts) + "이 확인되었습니다.")

    fall_events = [e for e in events if e.get("kind") == "fall"]
    if fall_events or fall_count:
        detail = fall_events[0].get("reasoning", "") if fall_events else ""
        lines.append(
            "낙상 의심 이벤트가 감지되어 보호자 알림을 보냈습니다. "
            + (detail + " " if detail else "")
            + "어르신의 상태를 직접 확인해 주시고, 괜찮으시면 알림을 '확인'으로 바꿔 주세요."
        )
    if any(e.get("kind") == "inactivity" for e in events):
        minutes = metrics.get("inactivity_minutes") or 0
        lines.append(f"오랜 시간 움직임이 적었습니다(약 {minutes / 60:.1f}시간). 식사와 수분 섭취를 권해 주세요.")
    if any(e.get("kind") == "wandering" for e in events):
        lines.append("밤 시간대 좌우로 오가는 이동이 반복되었습니다. 수면 환경과 화장실 동선을 살펴봐 주세요.")

    scored = [f for f in (factors or {}).get("items", []) if f.get("delta", 0) < 0]
    if scored and not fall_events:
        lines.append("평소와 비교해 주의할 점이 있습니다. " + ", ".join(f["detail"] for f in scored[:3]) + ".")
        lines.append("다음 날 활동이 이어지는지 함께 살펴봐 주세요.")
    elif not scored and not fall_events:
        lines.append("평소와 크게 다르지 않은 하루였습니다. 특별히 걱정하실 부분은 없습니다.")

    lines.append("이 리포트는 카메라 관절 좌표 분석을 바탕으로 만든 참고 자료이며, 진단을 대신하지 않습니다.")
    return "\n\n".join(lines)


def build_prompt(senior_name: str, report_date: date, metrics: dict, factors: dict, events: list[dict], score: dict) -> str:
    event_lines = "\n".join(f"- {e.get('event_type')}: {e.get('reasoning')} (신뢰도 {e.get('confidence')})" for e in events) or "- 특이 이벤트 없음"
    factor_lines = "\n".join(f"- {f.get('label')}: {f.get('detail')} ({f.get('delta')}점)" for f in (factors or {}).get("items", [])) or "- 없음"
    return f"""당신은 시니어 홈케어 안전관리 AI '온뷰(OnView)'입니다.
아래는 {senior_name} 댁의 {report_date.isoformat()} 행동 분석 요약입니다.

[지표] 걸음 수: {metrics.get('steps')} / 야간 활동: {metrics.get('night_activity_minutes')}분 /
화장실 이용: {metrics.get('toilet_visits')}회 / 침실 체류: {metrics.get('bedroom_minutes')}분 /
최장 무활동: {metrics.get('inactivity_minutes')}분

[감지 이벤트]
{event_lines}

[점수] {score['score']}점 ({score['risk_label']})
[평소 대비 요인]
{factor_lines}

요청:
1) 보호자(자녀)가 안심할 수 있도록 따뜻하고 차분한 한국어 존댓말로 3문단, 500자 이내로 작성하세요.
2) 첫 문단은 오늘의 전반적인 상태, 둘째 문단은 관찰된 점과 생활 조언, 셋째 문단은 다음 확인 사항을 담으세요.
3) 의학적 진단이나 단정은 하지 말고 '참고 자료'임을 밝히세요.
4) 이모지, 마크다운 기호, 제목 없이 본문 문장만 출력하세요."""


def generate_with_gemini(prompt: str, api_key: str, model: str, timeout: float = 30.0) -> str | None:
    url = GEMINI_ENDPOINT.format(model=model)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1024},
    }
    try:
        response = httpx.post(url, params={"key": api_key}, json=body, timeout=timeout)
        if response.status_code != 200:
            logger.warning("⚠️ [Gemini] HTTP %s: %s", response.status_code, response.text[:200])
            return None
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except Exception as exc:  # pragma: no cover - 네트워크 오류
        logger.warning("⚠️ [Gemini] 호출 실패: %s", exc)
        return None


def generate_daily_report(
    senior_name: str,
    report_date: date,
    metrics: dict[str, Any],
    factors: dict[str, Any],
    events: list[dict] | None = None,
    score: dict[str, Any] | None = None,
    config: Config | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """(headline, narrative, source, model_name, fallback_reason)을 담은 dict."""
    cfg = config or CONFIG
    key = api_key if api_key is not None else cfg.GEMINI_API_KEY
    events = events or []
    score = score or {}
    fall_count = score.get("fall_count") or sum(1 for e in events if e.get("kind") == "fall")
    headline = rule_headline(senior_name, metrics, factors, fall_count, (score or {}).get("risk_level"))
    narrative = rule_narrative(senior_name, report_date, metrics, factors, events, fall_count)
    result = {
        "headline": headline,
        "narrative": narrative,
        "source": "pipeline-rule",
        "model_name": None,
        "fallback_reason": None,
    }
    if not key:
        result["fallback_reason"] = "GEMINI_API_KEY 없음 → 규칙 기반 생성"
        return result

    prompt = build_prompt(senior_name, report_date, metrics, factors, events, score or {"score": None, "risk_label": "확인 필요"})
    text = generate_with_gemini(prompt, key, cfg.GEMINI_MODEL)
    if not text or len(text) < 40:
        result["fallback_reason"] = "Gemini 응답 없음/짧음 → 규칙 기반 생성"
        return result
    result.update({"narrative": text, "source": "pipeline-gemini", "model_name": cfg.GEMINI_MODEL})
    return result
