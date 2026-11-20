import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview.config import load_config  # noqa: E402
from onview.local_queue import LocalEventQueue  # noqa: E402
from onview.health_monitor import HealthMonitor  # noqa: E402
from onview.reporter import EventReporter  # noqa: E402
from onview.schemas import HealthMetrics, HealthState  # noqa: E402


def build(tmp_path, **cfg):
    base = dict(DB_PATH=str(tmp_path / "h.db"), FRAME_TIMEOUT=5.0, INFERENCE_TIMEOUT=10.0,
                REPORTING_TIMEOUT=20.0, HEALTH_INTERVAL=1.0)
    base.update(cfg)
    config = load_config(**base)
    queue = LocalEventQueue(config.DB_PATH)
    reporter = EventReporter(mode="MOCK", config=config, local_queue=queue)
    return HealthMonitor(HealthMetrics(), reporter, queue, config=config, check_interval=1.0)


def test_camera_offline_when_no_frames(tmp_path):
    monitor = build(tmp_path)
    assert monitor.evaluate_state(now=100.0) == HealthState.CAMERA_OFFLINE


def test_states_follow_timeouts(tmp_path):
    monitor = build(tmp_path)
    now = time.monotonic()
    monitor.metrics.last_frame_time = now - 1
    monitor.metrics.last_inference_time = now - 1
    monitor.metrics.last_server_ack_time = now - 1
    monitor.metrics.recent_fps = 15
    assert monitor.evaluate_state(now=now) == HealthState.HEALTHY

    monitor.metrics.last_frame_time = now - 30
    assert monitor.evaluate_state(now=now) == HealthState.CAMERA_OFFLINE

    monitor.metrics.last_frame_time = now - 1
    monitor.metrics.last_inference_time = now - 30
    assert monitor.evaluate_state(now=now) == HealthState.ANALYSIS_FAILED

    monitor.metrics.last_inference_time = now - 1
    monitor.metrics.last_server_ack_time = now - 40
    assert monitor.evaluate_state(now=now) == HealthState.REPORTING_FAILED

    monitor.metrics.last_server_ack_time = now - 1
    monitor.metrics.recent_fps = 2
    assert monitor.evaluate_state(now=now) == HealthState.DEGRADED


def test_snapshot_contains_queue_count(tmp_path):
    monitor = build(tmp_path)
    monitor.current_state = HealthState.HEALTHY
    snapshot = monitor.snapshot()
    assert snapshot["status"] == "HEALTHY"
    assert snapshot["offline_queue_count"] == 0
    assert snapshot["device_id"]
