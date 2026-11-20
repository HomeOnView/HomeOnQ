"""환경 설정. `.env`가 있으면 읽고, 없으면 안전한 기본값으로 동작한다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv는 선택 의존성
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass

PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent
DEFAULT_SAMPLE_DIR = PROJECT_DIR / "samples"


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    # --- 입력 ---
    CAMERA_SOURCE: str = os.getenv("CAMERA_SOURCE", "mock")  # mock | 0 | rtsp://... | 파일경로
    SAMPLE_DIR: Path = field(default_factory=lambda: Path(os.getenv("SAMPLE_DIR", str(DEFAULT_SAMPLE_DIR))))
    TIME_SCALE: float = _float("TIME_SCALE", 1.0)  # 시연용 시간 배속(긴 무활동 시나리오)

    # --- 서버 ---
    SERVER_MODE: str = os.getenv("SERVER_MODE", "MOCK").upper()  # MOCK | HTTP
    SERVER_URL: str = os.getenv("SERVER_URL", "http://localhost:8000").rstrip("/")
    DEVICE_TOKEN: str = os.getenv("DEVICE_TOKEN", "demo-edge-token-homeonq-0001")
    DEVICE_ID: str = os.getenv("DEVICE_ID", "DEMO-EDGE-01")
    SENIOR_NAME: str = os.getenv("SENIOR_NAME", "강O순 어르신")

    # --- 안정성 ---
    FRAME_TIMEOUT: float = _float("FRAME_TIMEOUT", 30.0)
    INFERENCE_TIMEOUT: float = _float("INFERENCE_TIMEOUT", 60.0)
    REPORTING_TIMEOUT: float = _float("REPORTING_TIMEOUT", 180.0)
    HEALTH_INTERVAL: float = _float("HEALTH_INTERVAL", 60.0)
    DB_PATH: str = os.getenv("DB_PATH", "local_events.db")

    # --- 분석 규칙 ---
    FALL_CONFIDENCE_THRESHOLD: float = _float("FALL_CONFIDENCE_THRESHOLD", 0.55)
    INACTIVITY_MINUTES: float = _float("INACTIVITY_MINUTES", 240.0)  # 장시간 무활동 기준(분)
    WANDERING_MINUTES: float = _float("WANDERING_MINUTES", 5.0)
    WANDERING_MIN_CROSSINGS: int = _int("WANDERING_MIN_CROSSINGS", 6)
    MOTION_THRESHOLD: float = _float("MOTION_THRESHOLD", 0.004)

    # --- 리포트 ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    REPORT_LANGUAGE: str = os.getenv("REPORT_LANGUAGE", "ko")

    # --- MediaPipe ---
    POSE_MODEL_PATH: str = os.getenv(
        "POSE_MODEL_PATH", str(PROJECT_DIR / "models" / "pose_landmarker_lite.task")
    )
    USE_MEDIAPIPE: bool = os.getenv("USE_MEDIAPIPE", "auto").lower() != "false"

    # --- AI 행동 분류 모델(선택) ---
    # .onnx + 같은 이름의 .json 메타데이터가 있으면 규칙 대신/함께 AI 판정을 사용한다.
    # 파일이 없거나 onnxruntime 미설치, 버전 불일치 등이면 조용히 규칙 기반으로 폴백한다.
    ACTION_MODEL_PATH: str = os.getenv(
        "ACTION_MODEL_PATH", str(PROJECT_DIR / "models" / "action_classifier.onnx")
    )
    USE_ACTION_MODEL: str = os.getenv("USE_ACTION_MODEL", "auto")  # auto | on | off
    MODEL_THREADS: int = _int("MODEL_THREADS", 1)
    MODEL_FALL_THRESHOLD: float = _float("MODEL_FALL_THRESHOLD", 0.60)
    MODEL_INACTIVITY_THRESHOLD: float = _float("MODEL_INACTIVITY_THRESHOLD", 0.60)
    MODEL_WANDERING_THRESHOLD: float = _float("MODEL_WANDERING_THRESHOLD", 0.60)
    MODEL_INACTIVITY_MIN_WINDOWS: int = _int("MODEL_INACTIVITY_MIN_WINDOWS", 3)
    MODEL_WANDERING_MIN_WINDOWS: int = _int("MODEL_WANDERING_MIN_WINDOWS", 2)
    MODEL_WANDERING_MIN_SECONDS: float = _float("MODEL_WANDERING_MIN_SECONDS", 5.0)


CONFIG = Config()


def load_config(**overrides) -> Config:
    """테스트/CLI에서 일부 값만 바꾼 설정 복사본."""
    from dataclasses import replace

    return replace(CONFIG, **overrides)
