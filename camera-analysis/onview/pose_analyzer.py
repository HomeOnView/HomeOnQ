"""MediaPipe Pose 관절좌표 추출기.

- MediaPipe 0.10.x: `mp.solutions.pose`(legacy) 사용
- MediaPipe 1.x: Tasks API(`PoseLandmarker`) + `.task` 모델 파일 사용
- 설치/모델이 없으면 경량 추정기(MockPoseEstimator)로 자동 대체한다.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from .config import CONFIG, Config
from .schemas import FrameData, HealthMetrics

logger = logging.getLogger(__name__)

POSE_LANDMARK_COUNT = 33


class MockPoseEstimator:
    """MediaPipe 없이도 파이프라인 전체 흐름을 검증하기 위한 경량 추정기."""

    name = "mock"

    def __init__(self, config: Config | None = None):
        self.config = config or CONFIG
        self._frame = 0

    def estimate(self, image: Any = None) -> list[list[float]] | None:
        # 실제 영상이 없으면 호출 측이 합성 시퀀스를 사용한다.
        self._frame += 1
        return None

    def close(self) -> None:
        pass


class MediaPipePoseEstimator:
    """MediaPipe PoseLandmarker(Tasks API) 또는 legacy solutions 래퍼."""

    name = "mediapipe"

    def __init__(self, config: Config | None = None):
        self.config = config or CONFIG
        self._landmarker = None
        self._legacy_pose = None
        self._backend = None
        self._init_backend()

    def _init_backend(self) -> None:
        # 컨테이너 등 일부 리눅스 환경에는 /sys/devices/system/cpu 가 없어
        # MediaPipe 내부 tcmalloc이 프로세스를 중단시킨다. 미리 감지해 우회한다.
        import sys

        if sys.platform.startswith("linux") and not Path("/sys/devices/system/cpu").exists():
            raise RuntimeError("이 환경에는 /sys/devices/system/cpu 가 없어 MediaPipe 네이티브 런타임을 쓸 수 없습니다.")
        model_path = Path(self.config.POSE_MODEL_PATH)
        try:
            import mediapipe as mp
        except Exception as exc:
            raise RuntimeError(f"mediapipe를 import할 수 없습니다: {exc}") from exc

        solutions = getattr(mp, "solutions", None)
        if solutions is not None:
            self._legacy_pose = solutions.pose.Pose(
                static_image_mode=False, model_complexity=1, enable_segmentation=False,
                min_detection_confidence=0.5, min_tracking_confidence=0.5,
            )
            self._backend = "solutions"
            logger.info("🤖 [PoseAnalyzer] MediaPipe legacy solutions 초기화")
            return

        if not model_path.exists():
            raise RuntimeError(
                f"MediaPipe 1.x Tasks 모델 파일이 없습니다: {model_path} "
                "(POSE_MODEL_PATH로 지정하거나 scripts/download_models.py 실행)"
            )
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        options = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.5,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._backend = "tasks"
        logger.info("🤖 [PoseAnalyzer] MediaPipe Tasks PoseLandmarker 초기화 (%s)", model_path.name)

    @property
    def backend(self) -> str:
        return self._backend or "none"

    def estimate(self, image: Any = None) -> list[list[float]] | None:
        """BGR numpy 배열(OpenCV) 또는 파일 경로에서 33개 관절 좌표를 반환."""
        if image is None:
            return None
        import numpy as np

        if isinstance(image, (str, Path)):
            import cv2

            frame = cv2.imread(str(image))
            if frame is None:
                raise RuntimeError(f"이미지를 읽을 수 없습니다: {image}")
        else:
            frame = image

        if self._legacy_pose is not None:
            rgb = frame[:, :, ::-1]  # BGR → RGB
            result = self._legacy_pose.process(rgb)
            if not result.pose_landmarks:
                return None
            return [[lm.x, lm.y, lm.z, lm.visibility] for lm in result.pose_landmarks.landmark]

        import mediapipe as mp

        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_image)
        if not result.pose_landmarks:
            return None
        return [[lm.x, lm.y, lm.z, getattr(lm, "visibility", 1.0)] for lm in result.pose_landmarks[0]]

    def close(self) -> None:
        if self._legacy_pose is not None:
            self._legacy_pose.close()


class PoseAnalyzer:
    """PoseAnalyzer 계층: 초기화 실패 시 Mock으로 자동 전환(명세서 3.1)."""

    def __init__(self, metrics: HealthMetrics | None = None, config: Config | None = None, use_mock: bool = False):
        self.metrics = metrics or HealthMetrics()
        self.config = config or CONFIG
        self.use_mock = use_mock or not self.config.USE_MEDIAPIPE
        self.estimator: MockPoseEstimator | MediaPipePoseEstimator
        self.fallback_reason: str | None = None
        if self.use_mock:
            self.fallback_reason = "USE_MEDIAPIPE=false"
            self.estimator = MockPoseEstimator(self.config)
        else:
            try:
                self.estimator = MediaPipePoseEstimator(self.config)
            except Exception as exc:
                logger.warning("⚠️ [PoseAnalyzer] MediaPipe 초기화 실패 (%s) → Mock 모드", exc)
                self.fallback_reason = str(exc)
                self.estimator = MockPoseEstimator(self.config)
                self.use_mock = True

    @property
    def backend(self) -> str:
        return self.estimator.name

    def process_frame(self, frame_data: FrameData) -> bool:
        now = time.monotonic()
        try:
            landmarks = self.estimator.estimate(frame_data.frame)
            frame_data.landmarks = landmarks
            success = landmarks is not None or self.use_mock
            if success:
                self.metrics.last_inference_time = now
                self.metrics.inference_count += 1
            return success
        except Exception as exc:
            logger.error("❌ [PoseAnalyzer] 추론 오류: %s", exc)
            return False

    def estimate_image(self, image: Any) -> list[list[float]] | None:
        return self.estimator.estimate(image)

    def close(self) -> None:
        self.estimator.close()
