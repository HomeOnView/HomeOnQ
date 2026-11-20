"""이벤트 리포터: MOCK / HTTP 모드 + 오프라인 큐 재전송.

명세서의 `EventReporter`를 홈온큐 실제 API(`/api/v1/device/...`)에 맞춰 확장했다.
- POST /api/v1/device/behavior-events  (행동 지표)
- POST /api/v1/device/fall-events      (낙상 의심)
- POST /api/v1/device/daily-reports    (안심 리포트)
- POST /api/v1/device/heartbeat        (파이프라인 상태)
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import CONFIG, Config
from .local_queue import LocalEventQueue
from .schemas import BehaviorEvent, DetectedEvent, HealthMetrics

logger = logging.getLogger(__name__)

ENDPOINTS = {
    "behavior": "/api/v1/device/behavior-events",
    "fall": "/api/v1/device/fall-events",
    "report": "/api/v1/device/daily-reports",
    "heartbeat": "/api/v1/device/heartbeat",
}


class EventReporter:
    def __init__(
        self,
        mode: str | None = None,
        server_url: str | None = None,
        device_token: str | None = None,
        metrics: HealthMetrics | None = None,
        local_queue: LocalEventQueue | None = None,
        config: Config | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ):
        self.config = config or CONFIG
        self.mode = (mode or self.config.SERVER_MODE).upper()
        self.server_url = (server_url or self.config.SERVER_URL).rstrip("/")
        self.device_token = device_token or self.config.DEVICE_TOKEN
        self.metrics = metrics or HealthMetrics()
        self.local_queue = local_queue or LocalEventQueue(self.config.DB_PATH)
        self.timeout = timeout
        self.client = client
        self._owns_client = client is None and self.mode == "HTTP"
        self.last_results: list[dict[str, Any]] = []

    # --- 내부 ---
    def _client(self) -> httpx.Client:
        if self.client is None:
            self.client = httpx.Client(
                base_url=self.server_url,
                headers={"X-Device-Token": self.device_token, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        return self.client

    def _send(self, endpoint: str, payload: dict[str, Any]) -> bool:
        if self.mode == "MOCK":
            time.sleep(0.01)
            logger.info("📡 [MOCK Server] ACK (endpoint=%s, keys=%s)", endpoint, list(payload)[:4])
            self.last_results.append({"endpoint": endpoint, "status": "mock", "ok": True})
            return True
        try:
            response = self._client().post(endpoint, json=payload)
            ok = response.status_code in (200, 201, 202, 204)
            self.last_results.append({
                "endpoint": endpoint,
                "status": response.status_code,
                "ok": ok,
                "body": response.text[:300],
            })
            if ok:
                self.metrics.last_server_ack_time = time.monotonic()
            else:
                logger.warning("⚠️ [HTTP] %s → %s %s", endpoint, response.status_code, response.text[:200])
            return ok
        except Exception as exc:  # 네트워크/직렬화 등 어떤 실패도 파이프라인을 멈추지 않는다.
            logger.warning("⚠️ [HTTP] 통신 실패(%s): %s", endpoint, exc)
            self.last_results.append({"endpoint": endpoint, "status": "error", "ok": False, "body": str(exc)[:300]})
            return False

    def _send_or_queue(self, kind: str, payload: dict[str, Any], queue_id: str) -> bool:
        endpoint = ENDPOINTS[kind]
        if self._send(endpoint, payload):
            return True
        event = BehaviorEvent(event_type=kind.upper(), timestamp=time.time(), details=payload)
        self.local_queue.enqueue(event, endpoint, payload)
        self.metrics.last_server_ack_time = self.metrics.last_server_ack_time  # 변화 없음
        return False

    # --- 공개 API ---
    def report_behavior(self, payload: dict[str, Any]) -> bool:
        return self._send_or_queue("behavior", payload, payload.get("event_id", ""))

    def report_fall(self, payload: dict[str, Any]) -> bool:
        return self._send_or_queue("fall", payload, payload.get("event_id", ""))

    def report_daily_report(self, payload: dict[str, Any]) -> bool:
        return self._send_or_queue("report", payload, payload.get("report_date", ""))

    def report_event(self, event: DetectedEvent, payload: dict[str, Any]) -> bool:
        if event.kind == "fall":
            return self.report_fall(payload)
        return self.report_behavior(payload)

    def report_health(self, status: str, metrics_snapshot: dict[str, Any]) -> bool:
        return self._send(ENDPOINTS["heartbeat"], {"status": status, "metrics": metrics_snapshot})

    def flush_offline_queue(self, limit: int = 10) -> int:
        pending = self.local_queue.get_pending_events(limit=limit)
        if not pending:
            return 0
        logger.info("🔄 [EventReporter] 오프라인 큐 동기화 시도 (%d건)", len(pending))
        sent = 0
        for item in pending:
            if self._send(item["endpoint"], item["payload"]):
                self.local_queue.remove_event(item["event_id"])
                sent += 1
            else:
                self.local_queue.mark_retry(item["event_id"], "send failed")
                break
        return sent

    def check_health(self) -> bool:
        if self.mode == "MOCK":
            return True
        try:
            response = self._client().get("/api/v1/health")
            return response.status_code == 200
        except Exception:
            return False

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()
            self.client = None
