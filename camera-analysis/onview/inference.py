"""플러그인형 ONNX 행동 분류기 (낙상·무활동·배회·정상).

- `models/action_classifier.onnx` + 같은 이름의 `.json` 메타데이터가 있으면 onnxruntime으로
  관절 시계열 창(window)을 분류해 확률을 낸다.
- 모델 파일이 없거나 `onnxruntime` 미설치, 메타데이터 버전 불일치, 추론 예외 등
  **어떤 경우에도 예외를 밖으로 던지지 않고** `(None, 사유)` 를 돌려주어 기존 규칙 기반
  감지기가 그대로 동작하게 한다(`detector.analyze_sequence`의 `classifier` 인자).
- 모델은 영상 1단계(MediaPipe 33관절) 결과만 입력으로 받는다. 카메라·서버 코드는 바뀌지 않는다.

메타데이터(`*.json`) 예시::

    {
      "format": "HOMEONQ-action-model/1",
      "model_name": "HOMEONQ-ActionNet-v1",
      "input_kind": "vector",            # vector | sequence
      "window": 30,
      "fps": 15.0,
      "feature_version": "HOMEONQ-FEAT-v1",
      "classes": ["normal", "fall", "inactivity", "wandering"],
      "thresholds": {"fall": 0.6, "inactivity": 0.6, "wandering": 0.6}
    }
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CONFIG, Config
from .schemas import DetectedEvent

# numpy/특징 모듈은 추론할 때만 필요하다. 학습 전용 환경(예: API 서버 venv)에서도
# 이 모듈을 import할 수 있어야 "모델 없음 → 규칙 기반 폴백"이 항상 성립한다.
try:
    import numpy as np

    from .features import (
        FEATURE_VERSION, VECTOR_FEATURES, frames_to_array, iter_windows, pad_window,
        window_sequence, window_vector,
    )
    _FEATURE_IMPORT_ERROR: str | None = None
except Exception as _exc:  # pragma: no cover - numpy/특징 모듈 미설치 환경
    np = None  # type: ignore[assignment]
    FEATURE_VERSION = ""
    VECTOR_FEATURES = ()
    _FEATURE_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

    def frames_to_array(frames):  # type: ignore[misc]
        raise RuntimeError(_FEATURE_IMPORT_ERROR or "특징 모듈을 사용할 수 없습니다")

    def iter_windows(n_frames, window, stride=None):  # type: ignore[misc]
        raise RuntimeError(_FEATURE_IMPORT_ERROR or "특징 모듈을 사용할 수 없습니다")

    def pad_window(arr, window):  # type: ignore[misc]
        raise RuntimeError(_FEATURE_IMPORT_ERROR or "특징 모듈을 사용할 수 없습니다")

    def window_sequence(frames, fps=15.0):  # type: ignore[misc]
        raise RuntimeError(_FEATURE_IMPORT_ERROR or "특징 모듈을 사용할 수 없습니다")

    def window_vector(frames, fps=15.0):  # type: ignore[misc]
        raise RuntimeError(_FEATURE_IMPORT_ERROR or "특징 모듈을 사용할 수 없습니다")

logger = logging.getLogger(__name__)

MODEL_FORMAT = "HOMEONQ-action-model/1"
CLASSES: tuple[str, ...] = ("normal", "fall", "inactivity", "wandering")
CLASS_LABELS_KO = {
    "normal": "정상",
    "fall": "낙상",
    "inactivity": "장시간 무활동",
    "wandering": "배회",
}
ABNORMAL_CLASSES = ("fall", "inactivity", "wandering")


@dataclass(frozen=True)
class ModelMetadata:
    classes: tuple[str, ...]
    input_kind: str
    window: int
    fps: float
    feature_version: str
    model_name: str = "HOMEONQ-ActionNet"
    version: str = "v1"
    thresholds: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    trained_at: str = ""
    backend: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelMetadata":
        classes = tuple(str(c) for c in data.get("classes") or CLASSES)
        if not classes:
            raise ValueError("메타데이터에 classes 가 없습니다")
        input_kind = str(data.get("input_kind", "vector"))
        if input_kind not in {"vector", "sequence"}:
            raise ValueError(f"지원하지 않는 input_kind: {input_kind}")
        return cls(
            classes=classes,
            input_kind=input_kind,
            window=int(data.get("window", 30)),
            fps=float(data.get("fps", 15.0)),
            feature_version=str(data.get("feature_version", "")),
            model_name=str(data.get("model_name", "HOMEONQ-ActionNet")),
            version=str(data.get("version", "v1")),
            thresholds={k: float(v) for k, v in (data.get("thresholds") or {}).items()},
            metrics=dict(data.get("metrics") or {}),
            trained_at=str(data.get("trained_at", "")),
            backend=str(data.get("backend", "")),
            raw=dict(data),
        )

    @classmethod
    def load(cls, path: str | Path) -> "ModelMetadata":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"메타데이터 형식이 올바르지 않습니다: {path}")
        fmt = str(data.get("format", MODEL_FORMAT))
        if fmt != MODEL_FORMAT:
            logger.warning("⚠️ [AI모델] 알 수 없는 메타데이터 형식(%s) — 계속 시도합니다", fmt)
        return cls.from_dict(data)

    def threshold(self, cls: str, default: float) -> float:
        return float(self.thresholds.get(cls, default))


@dataclass
class WindowPrediction:
    start_frame: int
    end_frame: int
    probabilities: dict[str, float]

    @property
    def top_class(self) -> str:
        return max(self.probabilities, key=self.probabilities.get)

    @property
    def top_probability(self) -> float:
        return float(self.probabilities[self.top_class])


@dataclass
class ModelAssessment:
    """모델이 시퀀스 전체에 대해 내린 판단(이벤트 + 요약 지표)."""

    events: list[DetectedEvent]
    metrics: dict[str, Any]
    windows: list[WindowPrediction] = field(default_factory=list)


class ActionModelClassifier:
    """ONNX 세션을 감싼 추론기. 생성은 `build_classifier()` 를 통해서만 한다."""

    name = "onnx"

    def __init__(self, model_path: str | Path, metadata: ModelMetadata, session: Any,
                 input_name: str | None = None):
        self.model_path = Path(model_path)
        self.metadata = metadata
        self.session = session
        self.input_name = input_name or session.get_inputs()[0].name
        self.output_name = session.get_outputs()[0].name

    # --- 상태 ---
    @property
    def available(self) -> bool:
        return self.session is not None

    @property
    def classes(self) -> tuple[str, ...]:
        return self.metadata.classes

    def status(self) -> dict[str, Any]:
        return {
            "source": "onnx",
            "model_path": str(self.model_path),
            "model_name": self.metadata.model_name,
            "model_version": self.metadata.version,
            "backend": self.metadata.backend,
            "input_kind": self.metadata.input_kind,
            "window": self.metadata.window,
            "fps": self.metadata.fps,
            "classes": list(self.metadata.classes),
            "feature_version": self.metadata.feature_version,
            "trained_at": self.metadata.trained_at,
            "val_metrics": self.metadata.metrics,
        }

    # --- 단일 창 ---
    def _build_input(self, window_arr: np.ndarray, fps: float | None = None) -> np.ndarray:
        use_fps = float(fps or self.metadata.fps)
        if self.metadata.input_kind == "sequence":
            seq = window_sequence(window_arr, fps=use_fps)
            x = seq[None, :, :]
        else:
            x = window_vector(window_arr, fps=use_fps)[None, :]
        return np.ascontiguousarray(x.astype(np.float32))

    def predict_array(self, window_arr: np.ndarray, fps: float | None = None) -> dict[str, float]:
        x = self._build_input(window_arr, fps=fps)
        probs = self.session.run([self.output_name], {self.input_name: x})[0]
        probs = np.asarray(probs, dtype=np.float32).reshape(-1)
        if probs.size != len(self.classes):
            raise ValueError(
                f"모델 출력 차원({probs.size})이 classes({len(self.classes)})와 다릅니다"
            )
        total = float(probs.sum())
        if total > 0:
            probs = probs / total
        return {cls: float(p) for cls, p in zip(self.classes, probs)}

    def predict_window(self, frames, fps: float, start: int = 0, end: int | None = None) -> WindowPrediction:
        arr = frames_to_array(frames) if not isinstance(frames, np.ndarray) else frames
        end = arr.shape[0] if end is None else end
        window = pad_window(arr[start:end], self.metadata.window)
        if window.shape[0] > self.metadata.window:
            window = window[: self.metadata.window]
        return WindowPrediction(start, end, self.predict_array(window, fps=fps))

    # --- 시퀀스 전체 ---
    def predict_windows(self, frames, fps: float | None = None) -> list[WindowPrediction]:
        arr = frames_to_array(frames) if not isinstance(frames, np.ndarray) else frames
        if arr.shape[0] == 0:
            return []
        use_fps = max(0.1, float(fps or self.metadata.fps))
        window = int(self.metadata.window)
        preds: list[WindowPrediction] = []
        for start, end in iter_windows(arr.shape[0], window):
            win = pad_window(arr[start:end], window)
            preds.append(WindowPrediction(start, end, self.predict_array(win, fps=use_fps)))
        return preds

    def analyze(
        self,
        frames,
        fps: float = 15.0,
        time_scale: float = 1.0,
        started_at: datetime | None = None,
        config: Config | None = None,
    ) -> ModelAssessment:
        cfg = config or CONFIG
        arr = frames_to_array(frames) if not isinstance(frames, np.ndarray) else frames
        if arr.shape[0] == 0:
            return ModelAssessment([], self._summary_metrics([], 0, fps, time_scale, cfg))
        started_at = started_at or datetime.now(timezone.utc)
        fps = max(0.1, float(fps))
        preds = self.predict_windows(arr, fps=fps)
        events = _events_from_predictions(preds, fps=fps, time_scale=time_scale,
                                         started_at=started_at, cfg=cfg, meta=self.metadata)
        return ModelAssessment(events, self._summary_metrics(preds, arr.shape[0], fps, time_scale, cfg), preds)

    def _summary_metrics(self, preds: list[WindowPrediction], n_frames: int, fps: float,
                         time_scale: float, cfg: Config) -> dict[str, Any]:
        mean_probs = {cls: 0.0 for cls in self.classes}
        peak = {cls: 0.0 for cls in self.classes}
        for p in preds:
            for cls in self.classes:
                mean_probs[cls] += p.probabilities.get(cls, 0.0)
                peak[cls] = max(peak[cls], p.probabilities.get(cls, 0.0))
        if preds:
            mean_probs = {k: v / len(preds) for k, v in mean_probs.items()}
        top = max(mean_probs, key=mean_probs.get) if preds else "unknown"
        return {
            "source": "onnx",
            "model_name": self.metadata.model_name,
            "model_version": self.metadata.version,
            "feature_version": self.metadata.feature_version,
            "window": self.metadata.window,
            "window_count": len(preds),
            "probabilities": {k: round(v, 4) for k, v in mean_probs.items()},
            "peak_probabilities": {k: round(v, 4) for k, v in peak.items()},
            "top_class": top,
            "clip_seconds": round(n_frames / max(0.1, fps), 2),
            "clip_seconds_scaled": round(n_frames / max(0.1, fps) * time_scale, 2),
            "time_scale": time_scale,
            "thresholds": {
                "fall": self.metadata.threshold("fall", cfg.MODEL_FALL_THRESHOLD),
                "inactivity": self.metadata.threshold("inactivity", cfg.MODEL_INACTIVITY_THRESHOLD),
                "wandering": self.metadata.threshold("wandering", cfg.MODEL_WANDERING_THRESHOLD),
            },
        }


def _contiguous_runs(preds: list[WindowPrediction], cls: str, threshold: float) -> list[list[WindowPrediction]]:
    runs: list[list[WindowPrediction]] = []
    current: list[WindowPrediction] = []
    for p in preds:
        if p.probabilities.get(cls, 0.0) >= threshold:
            current.append(p)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _events_from_predictions(
    preds: list[WindowPrediction],
    fps: float,
    time_scale: float,
    started_at: datetime,
    cfg: Config,
    meta: ModelMetadata,
) -> list[DetectedEvent]:
    if not preds:
        return []
    events: list[DetectedEvent] = []

    def at(frame_index: int) -> datetime:
        return datetime.fromtimestamp(started_at.timestamp() + frame_index / fps, tz=timezone.utc)

    # --- 낙상: 한 창이라도 임계 이상이면 즉시 ---
    fall_thr = meta.threshold("fall", cfg.MODEL_FALL_THRESHOLD)
    fall_runs = _contiguous_runs(preds, "fall", fall_thr)
    if fall_runs:
        run = fall_runs[0]
        peak_prob = max(p.probabilities["fall"] for p in run)
        start_frame = run[0].start_frame
        end_frame = run[-1].end_frame
        events.append(
            DetectedEvent(
                kind="fall",
                event_type="FALL",
                confidence=round(min(0.99, float(peak_prob)), 3),
                reasoning=(
                    f"AI 동작 모델이 {start_frame / fps:.1f}초 부근 {meta.window}프레임 구간을 "
                    f"낙상으로 판정했습니다(확률 {peak_prob:.2f})."
                ),
                occurred_at=at(end_frame),
                duration_s=round((end_frame - start_frame) / fps * time_scale, 2),
                frame_index=end_frame,
                features={
                    "source": "onnx",
                    "model": meta.model_name,
                    "probability": round(float(peak_prob), 4),
                    "window_start_frame": start_frame,
                    "window_end_frame": end_frame,
                    "window_probabilities": run[0].probabilities,
                },
            )
        )

    # --- 장시간 무활동: 연속 창이 충분히 이어질 때 ---
    inact_thr = meta.threshold("inactivity", cfg.MODEL_INACTIVITY_THRESHOLD)
    for run in _contiguous_runs(preds, "inactivity", inact_thr):
        span_frames = run[-1].end_frame - run[0].start_frame
        if len(run) < max(1, int(cfg.MODEL_INACTIVITY_MIN_WINDOWS)):
            continue
        peak_prob = max(p.probabilities["inactivity"] for p in run)
        events.append(
            DetectedEvent(
                kind="inactivity",
                event_type="INACTIVE",
                confidence=round(min(0.97, float(peak_prob)), 3),
                reasoning=(
                    f"AI 동작 모델이 {len(run)}개 연속 구간(약 {span_frames / fps * time_scale / 60:.0f}분)을 "
                    f"장시간 무활동으로 판정했습니다(확률 {peak_prob:.2f})."
                ),
                occurred_at=at(run[0].end_frame),
                duration_s=round(span_frames / fps * time_scale, 2),
                frame_index=run[0].end_frame,
                features={
                    "source": "onnx",
                    "model": meta.model_name,
                    "probability": round(float(peak_prob), 4),
                    "windows": len(run),
                },
            )
        )
        break

    # --- 배회: 임계 이상 창이 여러 개 이어지고 실제로 좌우 이동이 있어야 ---
    wander_thr = meta.threshold("wandering", cfg.MODEL_WANDERING_THRESHOLD)
    wander_runs = _contiguous_runs(preds, "wandering", wander_thr)
    if wander_runs:
        run = max(wander_runs, key=len)
        span_frames = run[-1].end_frame - run[0].start_frame
        min_windows = max(1, int(cfg.MODEL_WANDERING_MIN_WINDOWS))
        if len(run) >= min_windows and span_frames / fps >= cfg.MODEL_WANDERING_MIN_SECONDS:
            peak_prob = max(p.probabilities["wandering"] for p in run)
            events.append(
                DetectedEvent(
                    kind="wandering",
                    event_type="WANDERING",
                    confidence=round(min(0.95, float(peak_prob)), 3),
                    reasoning=(
                        f"AI 동작 모델이 {len(run)}개 구간의 반복 이동을 배회로 판정했습니다"
                        f"(확률 {peak_prob:.2f})."
                    ),
                    occurred_at=at(run[-1].end_frame),
                    duration_s=round(span_frames / fps * time_scale, 2),
                    frame_index=run[-1].end_frame,
                    features={
                        "source": "onnx",
                        "model": meta.model_name,
                        "probability": round(float(peak_prob), 4),
                        "windows": len(run),
                    },
                )
            )
    return events


def resolve_model_paths(model_path: str | Path | None, metadata_path: str | Path | None = None) -> tuple[Path, Path]:
    model = Path(model_path) if model_path else Path(CONFIG.ACTION_MODEL_PATH)
    if metadata_path:
        meta = Path(metadata_path)
    else:
        meta = model.with_suffix(".json")
    return model, meta


def build_classifier(
    config: Config | None = None,
    model_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    session_factory: Any = None,
) -> tuple[ActionModelClassifier | None, str]:
    """설정에 따라 ONNX 분류기를 만든다. 실패하면 (None, 사유) — 예외를 던지지 않는다."""
    cfg = config or CONFIG
    mode = str(getattr(cfg, "USE_ACTION_MODEL", "auto")).lower()
    if mode in {"off", "false", "0", "none"}:
        return None, "USE_ACTION_MODEL=off (규칙 기반 사용)"

    model, meta_path = resolve_model_paths(model_path or getattr(cfg, "ACTION_MODEL_PATH", None), metadata_path)
    if not model.exists():
        return None, f"모델 파일 없음({model}) → 규칙 기반 사용"
    if not meta_path.exists():
        return None, f"모델 메타데이터 없음({meta_path}) → 규칙 기반 사용"
    if np is None:
        return None, f"numpy/특징 모듈을 불러올 수 없습니다({_FEATURE_IMPORT_ERROR}) → 규칙 기반 사용"

    try:
        metadata = ModelMetadata.load(meta_path)
    except Exception as exc:
        return None, f"메타데이터를 읽을 수 없습니다({exc}) → 규칙 기반 사용"
    if metadata.feature_version != FEATURE_VERSION:
        return None, (
            f"특징 버전 불일치(모델 {metadata.feature_version or '미지정'} ≠ 코드 {FEATURE_VERSION}) "
            "→ 규칙 기반 사용"
        )

    try:
        import onnxruntime  # noqa: F401  (설치 여부 확인용)
    except Exception as exc:
        return None, f"onnxruntime 미설치({exc}) → 규칙 기반 사용"

    try:
        if session_factory is None:
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = max(1, int(getattr(cfg, "MODEL_THREADS", 1)))
            options.log_severity_level = 3
            session_factory = lambda path: onnxruntime.InferenceSession(  # noqa: E731
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        session = session_factory(str(model))
        classifier = ActionModelClassifier(model, metadata, session)
        # 입출력 차원이 특징 명세와 맞는지 한 번 확인한다.
        expected = len(VECTOR_FEATURES) if metadata.input_kind == "vector" else None
        shape = session.get_inputs()[0].shape
        if expected is not None and isinstance(shape[-1], int) and shape[-1] != expected:
            raise ValueError(f"모델 입력 차원({shape[-1]}) ≠ 특징 차원({expected})")
        logger.info("🧠 [AI모델] ONNX 분류기 로드 완료: %s (%s, %s)",
                    model.name, metadata.model_name, metadata.input_kind)
        return classifier, "onnx"
    except Exception as exc:
        return None, f"ONNX 모델 로드 실패({exc}) → 규칙 기반 사용"


def model_status(config: Config | None = None, model_path: str | Path | None = None) -> dict[str, Any]:
    """CLI/디버깅용 상태 요약."""
    cfg = config or CONFIG
    classifier, reason = build_classifier(cfg, model_path=model_path)
    status: dict[str, Any] = {
        "available": classifier is not None,
        "reason": reason,
        "configured_path": str(model_path or getattr(cfg, "ACTION_MODEL_PATH", "")),
        "use_action_model": str(getattr(cfg, "USE_ACTION_MODEL", "auto")),
    }
    if classifier is not None:
        status.update(classifier.status())
    try:
        import onnxruntime

        status["onnxruntime"] = onnxruntime.__version__
    except Exception:
        status["onnxruntime"] = None
    return status
