"""파이프라인 상태 감시(HEALTHY/DEGRADED/CAMERA_OFFLINE/ANALYSIS_FAILED/REPORTING_FAILED)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .config import CONFIG, Config
from .local_queue import LocalEventQueue
from .reporter import EventReporter
from .schemas import HealthMetrics, HealthState

logger = logging.getLogger(__name__)


class HealthMonitor(threading.Thread):
    def __init__(
        self,
        metrics: HealthMetrics,
        reporter: EventReporter,
        local_queue: LocalEventQueue | None = None,
        config: Config | None = None,
        check_interval: float | None = None,
        on_state_change: Callable[[HealthState, dict], None] | None = None,
    ):
        super().__init__(daemon=True)
        self.config = config or CONFIG
        self.metrics = metrics
        self.reporter = reporter
        self.local_queue = local_queue or reporter.local_queue
        self.check_interval = check_interval or self.config.HEALTH_INTERVAL
        self.on_state_change = on_state_change
        self.running = threading.Event()
        self.running.set()
        self.current_state = HealthState.CAMERA_OFFLINE

    def evaluate_state(self, now: float | None = None) -> HealthState:
        now = time.monotonic() if now is None else now
        m = self.metrics
        if m.last_frame_time == 0.0 and m.last_inference_time == 0.0:
            return HealthState.CAMERA_OFFLINE
        if now - m.last_frame_time > self.config.FRAME_TIMEOUT:
            return HealthState.CAMERA_OFFLINE
        if now - m.last_inference_time > self.config.INFERENCE_TIMEOUT:
            return HealthState.ANALYSIS_FAILED
        if m.last_server_ack_time and now - m.last_server_ack_time > self.config.REPORTING_TIMEOUT:
            return HealthState.REPORTING_FAILED
        if 0.0 < m.recent_fps < 5.0:
            return HealthState.DEGRADED
        return HealthState.HEALTHY

    def snapshot(self) -> dict:
        return {
            "device_id": self.config.DEVICE_ID,
            "status": self.current_state.value,
            "recent_fps": round(self.metrics.recent_fps, 2),
            "frame_count": self.metrics.frame_count,
            "inference_count": self.metrics.inference_count,
            "reconnect_count": self.metrics.reconnect_count,
            "offline_queue_count": self.local_queue.count(),
        }

    def run(self) -> None:  # pragma: no cover - 스레드 루프
        logger.info("🩺 [HealthMonitor] 시작 (주기 %.0f초)", self.check_interval)
        last_report = 0.0
        while self.running.is_set():
            now = time.monotonic()
            state = self.evaluate_state(now)
            changed = state != self.current_state
            self.current_state = state
            self.reporter.flush_offline_queue()
            if changed or now - last_report >= self.check_interval:
                snapshot = self.snapshot()
                logger.info("📊 [HealthMonitor] %s %s", state.value, snapshot)
                self.reporter.report_health(state.value, snapshot)
                if changed and self.on_state_change:
                    self.on_state_change(state, snapshot)
                last_report = now
            time.sleep(1.0)

    def stop(self) -> None:
        self.running.clear()
        logger.info("🛑 [HealthMonitor] 중지 요청")
