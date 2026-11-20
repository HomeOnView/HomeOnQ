"""RTSP/동영상/웹캠 입력 스레드 (지수형 백오프 재연결).

OpenCV(cv2)가 없는 환경에서도 모듈 import는 실패하지 않는다.
"""
from __future__ import annotations

import logging
import threading
import time
from queue import Empty, Queue
from typing import Union

from .schemas import FrameData, HealthMetrics

logger = logging.getLogger(__name__)


class CameraStream(threading.Thread):
    def __init__(self, source: Union[str, int], metrics: HealthMetrics, max_queue: int = 30):
        super().__init__(daemon=True)
        self.source = source
        self.metrics = metrics
        self.frame_queue: Queue[FrameData] = Queue(maxsize=max_queue)
        self.running = threading.Event()
        self.running.set()
        self.error: str | None = None

    def run(self) -> None:  # pragma: no cover - 카메라 필요
        try:
            import cv2
        except Exception as exc:
            self.error = f"OpenCV 없음: {exc}"
            logger.error("❌ [CameraStream] %s", self.error)
            return

        attempts = 0
        base_delay, max_delay = 1.0, 30.0
        while self.running.is_set():
            logger.info("📹 [CameraStream] 연결 시도: %s", self.source)
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                attempts += 1
                self.metrics.reconnect_count = attempts
                delay = min(base_delay * (2 ** (attempts - 1)), max_delay)
                logger.warning("⚠️ [CameraStream] 연결 실패. %.0f초 후 재시도(%d회)", delay, attempts)
                time.sleep(delay)
                continue
            logger.info("✅ [CameraStream] 연결 성공")
            attempts = 0
            frame_num = 0
            fps_timer, fps_counter = time.monotonic(), 0
            while self.running.is_set():
                ok, frame = cap.read()
                if not ok:
                    logger.warning("⚠️ [CameraStream] 프레임 수신 중단 → 재연결")
                    break
                now = time.monotonic()
                self.metrics.last_frame_time = now
                self.metrics.frame_count += 1
                frame_num += 1
                fps_counter += 1
                if now - fps_timer >= 1.0:
                    self.metrics.recent_fps = fps_counter / (now - fps_timer)
                    fps_counter, fps_timer = 0, now
                data = FrameData(timestamp=now, frame_number=frame_num, frame=frame)
                if self.frame_queue.full():
                    try:
                        self.frame_queue.get_nowait()
                    except Empty:
                        pass
                self.frame_queue.put(data)
            cap.release()
            time.sleep(1.0)

    def get_latest_frame(self, timeout: float = 1.0) -> FrameData | None:
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            return None

    def stop(self) -> None:
        self.running.clear()
        logger.info("🛑 [CameraStream] 중지 요청")
