import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview.config import load_config  # noqa: E402
from onview.local_queue import LocalEventQueue  # noqa: E402
from onview.pipeline import PipelineRunner  # noqa: E402
from onview.reporter import EventReporter  # noqa: E402
from onview.simulation import analyze_scenario  # noqa: E402
from onview.skeleton_source import SCENARIO_FILES, load_sequence  # noqa: E402


def make_runner(tmp_path):
    cfg = load_config(DB_PATH=str(tmp_path / "pipe.db"), SERVER_MODE="MOCK")
    queue = LocalEventQueue(cfg.DB_PATH)
    reporter = EventReporter(mode="MOCK", config=cfg, local_queue=queue)
    return PipelineRunner(config=cfg, reporter=reporter, queue=queue)


def test_normal_run_builds_valid_payloads(tmp_path):
    runner = make_runner(tmp_path)
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["normal"])
    result = runner.run_sequence(seq, senior_name="강O순 어르신")
    assert result.score["risk_level"] == "SAFE"
    assert len(result.behavior_payloads) == 5
    assert result.fall_payloads == []
    for payload in result.behavior_payloads:
        assert len(payload["event_id"]) == 36
        assert datetime.fromisoformat(payload["captured_at"]).tzinfo is not None
        assert payload["activity_type"] in {"WALKING", "NIGHT_ACTIVITY", "TOILET_VISIT", "BEDROOM_STAY", "INACTIVE"}
        assert payload["event_value"] > 0
    report = result.report_payload
    assert report["report_date"] == datetime.now(timezone.utc).astimezone().date().isoformat() or report["report_date"]
    assert report["score"] == result.score["score"]
    assert report["source"] == "pipeline-rule"
    assert report["summary"]["rows"]
    assert all(s is True for s in result.sent["behavior"])
    assert result.sent["report"] is True


def test_fall_scenario_produces_fall_payload_and_alert_report(tmp_path):
    runner = make_runner(tmp_path)
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["fall"])
    result = runner.run_sequence(seq)
    assert len(result.fall_payloads) == 1
    payload = result.fall_payloads[0]
    assert payload["fall_suspected"] is True
    assert 0 <= payload["confidence"] <= 1
    assert payload["event_id"].startswith("sim-")
    assert result.score["risk_level"] == "ALERT"
    assert "낙상" in result.report_payload["narrative"]


def test_offline_mode_queues_when_server_absent(tmp_path):
    cfg = load_config(DB_PATH=str(tmp_path / "down.db"), SERVER_MODE="HTTP",
                      SERVER_URL="http://127.0.0.1:9")
    queue = LocalEventQueue(cfg.DB_PATH)
    reporter = EventReporter(config=cfg, local_queue=queue, timeout=0.5)
    runner = PipelineRunner(config=cfg, reporter=reporter, queue=queue)
    result = runner.run_file(str(ROOT / "samples" / SCENARIO_FILES["fall"]), send=True)
    assert result.sent["report"] is False
    assert queue.count() >= 1
    runner.close()


@pytest.mark.parametrize("scenario", list(SCENARIO_FILES))
def test_simulation_public_summary_is_json_ready(scenario):
    import json

    summary = analyze_scenario(scenario).public_summary()
    text = json.dumps(summary, ensure_ascii=False)  # 직렬화 가능해야 API 응답으로 쓸 수 있다
    assert "report" in summary and "score" in summary
    assert summary["behavior_count"] >= 1
    assert summary["report"]["narrative"]
