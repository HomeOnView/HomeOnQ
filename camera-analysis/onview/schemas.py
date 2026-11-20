"""파이프라인 공용 데이터 구조 (안정성 명세서의 schemas.py 확장판)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class HealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CAMERA_OFFLINE = "CAMERA_OFFLINE"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    REPORTING_FAILED = "REPORTING_FAILED"


# MediaPipe Pose 33 landmark indices
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_KNEE, RIGHT_KNEE = 25, 26
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
LEFT_WRIST, RIGHT_WRIST = 15, 16
KEY_JOINTS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP,
              LEFT_WRIST, RIGHT_WRIST, LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE)


@dataclass
class HealthMetrics:
    last_frame_time: float = 0.0
    last_inference_time: float = 0.0
    last_server_ack_time: float = 0.0
    recent_fps: float = 0.0
    frame_count: int = 0
    inference_count: int = 0
    reconnect_count: int = 0

    def snapshot(self, device_id: str = "DEMO-EDGE-01") -> dict[str, Any]:
        return {
            "device_id": device_id,
            "recent_fps": round(self.recent_fps, 2),
            "frame_count": self.frame_count,
            "inference_count": self.inference_count,
            "reconnect_count": self.reconnect_count,
            "last_inference_age_s": None,
        }


@dataclass
class SkeletonPoint:
    x: float
    y: float
    z: float
    visibility: float


@dataclass
class FrameData:
    timestamp: float
    frame_number: int
    frame: Any
    success: bool = True
    landmarks: list[list[float]] | None = None


@dataclass
class BehaviorEvent:
    event_type: str
    timestamp: float
    details: dict[str, Any] = field(default_factory=dict)
    device_id: str = "DEMO-EDGE-01"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class DetectedEvent:
    """분석기가 찾아낸 사건(낙상/무활동/배회 등)."""

    kind: str  # fall | inactivity | wandering | behavior
    event_type: str
    confidence: float
    reasoning: str
    occurred_at: datetime
    duration_s: float = 0.0
    frame_index: int = 0
    features: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "event_type": self.event_type,
            "confidence": round(self.confidence, 3),
            "reasoning": self.reasoning,
            "occurred_at": self.occurred_at.isoformat(),
            "duration_s": round(self.duration_s, 2),
            "frame_index": self.frame_index,
            "features": self.features,
        }


@dataclass
class SequenceAnalysis:
    frames: list
    fps: float
    time_scale: float
    events: list[DetectedEvent]
    metrics: dict[str, Any]
    torso_angle_max: float
    drop_speed_max: float

    @property
    def duration_s(self) -> float:
        return len(self.frames) / self.fps * self.time_scale if self.fps else 0.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
