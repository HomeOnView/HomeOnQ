import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview import report_generator  # noqa: E402
from onview.scoring import compute_daily_score  # noqa: E402

METRICS = {"steps": 2980, "night_activity_minutes": 75, "toilet_visits": 9,
           "bedroom_minutes": 420, "inactivity_minutes": 265}
BASELINE = {"steps": 4100}
EVENTS = [{"kind": "fall", "event_type": "FALL", "confidence": 0.85, "reasoning": "급격한 자세 변화"}]


def _score(fall=0):
    return compute_daily_score(METRICS, BASELINE, fall_count=fall)


def test_rule_fallback_without_api_key():
    report = report_generator.generate_daily_report(
        "강O순 어르신", date(2026, 11, 21), METRICS, _score(1)["factors"], EVENTS, _score(1), api_key=""
    )
    assert report["source"] == "pipeline-rule"
    assert "GEMINI_API_KEY" in report["fallback_reason"]
    assert "낙상" in report["narrative"]
    assert "참고 자료" in report["narrative"]
    assert "강O순" in report["headline"]


def test_gemini_success_uses_model_text(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "제미나이가 만든 안심 리포트 문장입니다. 오늘도 평안한 하루를 보내셨고 특별한 위험 신호는 없었습니다."}]}}]}

    monkeypatch.setattr(report_generator.httpx, "post", lambda *a, **k: Resp())
    report = report_generator.generate_daily_report(
        "강O순 어르신", date(2026, 11, 21), METRICS, _score(0)["factors"], [], _score(0), api_key="test-key"
    )
    assert report["source"] == "pipeline-gemini"
    assert report["model_name"]
    assert "제미나이" in report["narrative"]


def test_gemini_failure_falls_back(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(report_generator.httpx, "post", boom)
    report = report_generator.generate_daily_report(
        "강O순 어르신", date(2026, 11, 21), METRICS, _score(1)["factors"], EVENTS, _score(1), api_key="test-key"
    )
    assert report["source"] == "pipeline-rule"
    assert "Gemini" in report["fallback_reason"]


def test_gemini_short_answer_falls_back(monkeypatch):
    class Resp:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "짧음"}]}}]}

    monkeypatch.setattr(report_generator.httpx, "post", lambda *a, **k: Resp())
    report = report_generator.generate_daily_report(
        "강O순 어르신", date(2026, 11, 21), METRICS, _score(0)["factors"], [], _score(0), api_key="test-key"
    )
    assert report["source"] == "pipeline-rule"


def test_prompt_contains_key_facts():
    prompt = report_generator.build_prompt(
        "강O순 어르신", date(2026, 11, 21), METRICS, _score(1)["factors"], EVENTS, _score(1)
    )
    assert "2,980" in prompt or "2980" in prompt
    assert "낙상" in prompt
    assert "참고 자료" in prompt
    assert "이모지" in prompt
