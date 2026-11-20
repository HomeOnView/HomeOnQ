"""파이프라인 점수 규칙이 서버 구현과 동일한지 확인한다.

두 폴더는 독립 배포 단위이므로 규칙이 갈라질 수 있다. 여기서 같은 입력을
넣어 결과(점수·등급·색상·요인)를 비교한다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PROJECT / "api-server"))

from onview.scoring import compute_daily_score as client_score  # noqa: E402

server_scoring = pytest.importorskip(
    "app.services.scoring", reason="api-server 의존성이 없는 환경에서는 건너뜀"
)

CASES = [
    ({"steps": 3380, "night_activity_minutes": 18, "toilet_visits": 6, "inactivity_minutes": 90}, {"steps": 4100}, 0),
    ({"steps": 2980, "night_activity_minutes": 75, "toilet_visits": 9, "inactivity_minutes": 265}, {"steps": 4100}, 1),
    ({"steps": 640, "night_activity_minutes": 25}, {"steps": 4100}, 0),
    ({"steps": 1500, "night_activity_minutes": 65, "wandering_minutes": 12, "toilet_visits": 9}, {"steps": 4100}, 2),
    ({}, {}, 0),
]


@pytest.mark.parametrize("metrics,baseline,falls", CASES)
def test_scores_match_server(metrics, baseline, falls):
    client = client_score(metrics, baseline, fall_count=falls)
    server = server_scoring.compute_daily_score(metrics, baseline, fall_count=falls)
    assert client["score"] == server["score"]
    assert client["risk_level"] == server["risk_level"]
    assert client["risk_label"] == server["risk_label"]
    assert client["ui_color"] == server["ui_color"]
    assert client["factors"]["items"] == server["factors"]["items"]
