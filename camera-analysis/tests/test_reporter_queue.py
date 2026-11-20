import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview.local_queue import LocalEventQueue  # noqa: E402
from onview.reporter import EventReporter  # noqa: E402
from onview.schemas import BehaviorEvent, HealthMetrics  # noqa: E402


class FakeResponse:
    def __init__(self, status_code=201, text="ok"):
        self.status_code = status_code
        self.text = text


class FakeClient:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []

    def post(self, endpoint, json=None):
        self.calls.append((endpoint, json))
        status = self.statuses.pop(0) if self.statuses else 201
        if isinstance(status, Exception):
            raise status
        return FakeResponse(status)

    def get(self, endpoint):
        return FakeResponse(200)

    def close(self):
        pass


def test_local_queue_roundtrip(tmp_path):
    path = tmp_path / "q.db"
    q = LocalEventQueue(path)
    event = BehaviorEvent(event_type="FALL", timestamp=1.0, details={"a": 1})
    q.enqueue(event, "/api/v1/device/fall-events", {"a": 1})
    assert q.count() == 1
    pending = q.get_pending_events()
    assert pending[0]["endpoint"] == "/api/v1/device/fall-events"
    assert pending[0]["payload"] == {"a": 1}
    q.mark_retry(pending[0]["event_id"], "timeout")
    assert q.get_pending_events()[0]["retry_count"] == 1
    q.remove_event(pending[0]["event_id"])
    assert q.count() == 0
    # 다른 인스턴스에서도 같은 DB를 본다(영구 보존)
    assert LocalEventQueue(path).count() == 0


def test_mock_mode_never_queues(tmp_path):
    q = LocalEventQueue(tmp_path / "mock.db")
    reporter = EventReporter(mode="MOCK", local_queue=q, device_token="t")
    assert reporter.report_fall({"event_id": "x"}) is True
    assert reporter.report_health("HEALTHY", {}) is True
    assert q.count() == 0
    assert reporter.last_results[0]["status"] == "mock"


def test_http_failure_queues_then_flush_succeeds(tmp_path):
    q = LocalEventQueue(tmp_path / "http.db")
    failing = FakeClient([RuntimeError("down")])
    reporter = EventReporter(mode="HTTP", local_queue=q, device_token="t", client=failing)
    assert reporter.report_behavior({"event_id": "evt-1", "activity_type": "WALKING"}) is False
    assert q.count() == 1

    ok = FakeClient([201])
    reporter.client = ok
    assert reporter.flush_offline_queue() == 1
    assert q.count() == 0
    assert ok.calls[0][0] == "/api/v1/device/behavior-events"
    assert ok.calls[0][1]["event_id"] == "evt-1"


def test_http_error_status_queues(tmp_path):
    q = LocalEventQueue(tmp_path / "http2.db")
    reporter = EventReporter(mode="HTTP", local_queue=q, device_token="t", client=FakeClient([422]))
    assert reporter.report_daily_report({"report_date": "2026-11-21"}) is False
    assert q.count() == 1
    assert reporter.last_results[-1]["status"] == 422


def test_health_snapshot_after_success(tmp_path):
    q = LocalEventQueue(tmp_path / "h.db")
    metrics = HealthMetrics()
    reporter = EventReporter(mode="HTTP", local_queue=q, device_token="t", metrics=metrics, client=FakeClient([200]))
    assert reporter.report_health("HEALTHY", {"fps": 15}) is True
    assert metrics.last_server_ack_time > 0
    assert reporter.check_health() is True
