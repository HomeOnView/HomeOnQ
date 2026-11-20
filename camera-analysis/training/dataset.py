"""33관절 데이터셋: `.npz` 클립 + `manifest.json` 로더와 학습용 창(window) 생성.

클립 1개 = 영상 1개에서 뽑은 33관절 시계열.

    npz: frames (n, 33, 4) float32, fps, label, clip_id, source

`manifest.json`::

    {"format": "HOMEONQ-joint-dataset/1", "fps": 15.0,
     "classes": ["normal","fall","inactivity","wandering"],
     "clips": [{"clip_id": "...", "npz": "xxx.npz", "label": "fall", "fps": 15.0,
                "frames": 135, "segments": [{"start": 0.0, "end": 2.3, "label": "normal"}],
                "source_video": "...", "pose_coverage": 0.98}],
     "unmatched": [...], "skipped": [...]}

구간(`segments`)이 있으면 창과 겹치는 비율이 가장 큰 구간의 라벨을 쓰고, 50% 미만이면
`normal`(배경)로 둔다. 구간 정보가 없는 클립은 클립 라벨을 그대로 쓴다 — AI 허브처럼
클립 단위 라벨만 있는 데이터의 기본 동작이며, 문서에 한계로 적어 두었다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from onview.features import FEATURE_VERSION, LANDMARK_COUNT, iter_windows, pad_window

from .labels import CLASSES, Segment

DATASET_FORMAT = "HOMEONQ-joint-dataset/1"


@dataclass
class Clip:
    clip_id: str
    frames: np.ndarray  # (n, 33, 4) float32
    fps: float
    label: str
    segments: list[Segment] = field(default_factory=list)
    source: str = ""
    pose_coverage: float = 1.0
    path: Path | None = None
    # 증강 사본은 clip_id가 달라도 같은 원본 클립과 같은 교차검증 폴드에 묶어야 한다.
    group_id: str = ""

    @property
    def group_key(self) -> str:
        return self.group_id or self.clip_id

    @property
    def duration_s(self) -> float:
        return len(self.frames) / max(0.1, self.fps)


@dataclass
class Dataset:
    clips: list[Clip]
    meta: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @property
    def classes(self) -> tuple[str, ...]:
        return tuple(CLASSES)

    def class_counts(self) -> dict[str, int]:
        counts = {cls: 0 for cls in CLASSES}
        for clip in self.clips:
            counts[clip.label] = counts.get(clip.label, 0) + 1
        return counts

    def summary(self) -> dict[str, Any]:
        return {
            "clips": len(self.clips),
            "frames": int(sum(len(c.frames) for c in self.clips)),
            "duration_s": round(sum(c.duration_s for c in self.clips), 1),
            "class_counts": self.class_counts(),
            "fps": sorted({round(c.fps, 2) for c in self.clips}),
        }


# --------------------------------------------------------------------------- #
# 저장/로드
# --------------------------------------------------------------------------- #
def save_clip(
    out_dir: str | Path,
    clip_id: str,
    frames: Sequence[Sequence[Sequence[float]]] | np.ndarray,
    fps: float,
    label: str,
    segments: list[Segment] | None = None,
    source: str = "",
    pose_coverage: float = 1.0,
) -> dict[str, Any]:
    """클립 하나를 `.npz`로 저장하고 매니페스트 항목(dict)을 돌려준다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    arr = frames if isinstance(frames, np.ndarray) else np.asarray(frames, dtype=np.float32)
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[1:] != (LANDMARK_COUNT, 4):
        raise ValueError(f"frames 형식은 (n, 33, 4)여야 합니다: {arr.shape}")
    safe_id = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in clip_id) or "clip"
    rel = f"{safe_id}.npz"
    np.savez_compressed(
        out_dir / rel,
        frames=arr,
        fps=np.float32(fps),
        label=np.array(label),
        clip_id=np.array(safe_id),
        source=np.array(str(source)),
    )
    return {
        "clip_id": safe_id,
        "npz": rel,
        "label": label,
        "fps": round(float(fps), 3),
        "frames": int(arr.shape[0]),
        "duration_s": round(arr.shape[0] / max(0.1, fps), 2),
        "segments": [s.as_dict() for s in (segments or [])],
        "source_video": str(source),
        "pose_coverage": round(float(pose_coverage), 3),
    }


def write_manifest(out_dir: str | Path, entries: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> Path:
    out_dir = Path(out_dir)
    payload: dict[str, Any] = {
        "format": DATASET_FORMAT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "coordinate_system": "mediapipe_pose_33_normalized_image",
        "feature_version": FEATURE_VERSION,
        "classes": list(CLASSES),
        "clips": entries,
        **{k: v for k, v in (extra or {}).items() if k not in {"clips", "format", "created_at"}},
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_dataset(path: str | Path) -> Dataset:
    """매니페스트 폴더 또는 `.npz` 단일 파일을 읽는다."""
    path = Path(path)
    if path.is_dir():
        manifest_path = path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json 이 없습니다: {path}")
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        clips: list[Clip] = []
        for entry in meta.get("clips", []):
            npz_path = path / entry.get("npz", f"{entry.get('clip_id', 'clip')}.npz")
            clip = _load_npz(npz_path)
            clip.segments = [Segment(float(s["start"]), float(s["end"]), str(s["label"])) for s in entry.get("segments", [])]
            clip.label = str(entry.get("label", clip.label))
            clip.clip_id = str(entry.get("clip_id", clip.clip_id))
            clip.source = str(entry.get("source_video", clip.source))
            clip.pose_coverage = float(entry.get("pose_coverage", 1.0))
            clip.path = npz_path
            clips.append(clip)
        return Dataset(clips=clips, meta=meta, path=path)

    clip = _load_npz(path)
    clip.path = path
    return Dataset(clips=[clip], meta={}, path=path)


def _load_npz(path: Path) -> Clip:
    if not path.exists():
        raise FileNotFoundError(f"npz 파일이 없습니다: {path}")
    with np.load(path) as data:
        frames = np.asarray(data["frames"], dtype=np.float32)
        fps = float(data["fps"]) if "fps" in data else 15.0
        label = str(data["label"]) if "label" in data else "normal"
        clip_id = str(data["clip_id"]) if "clip_id" in data else path.stem
        source = str(data["source"]) if "source" in data else ""
    if frames.ndim != 3 or frames.shape[1:] != (LANDMARK_COUNT, 4):
        raise ValueError(f"npz frames 형식이 (n, 33, 4)가 아닙니다: {path} {frames.shape}")
    return Clip(clip_id=clip_id, frames=frames, fps=fps, label=label, source=source)


# --------------------------------------------------------------------------- #
# 창(window) 생성
# --------------------------------------------------------------------------- #
def window_label(clip: Clip, start: int, end: int, default: str = "normal") -> str:
    """창과 가장 많이 겹치는 구간의 라벨(50% 이상). 없으면 클립 라벨."""
    if not clip.segments:
        return clip.label
    span = max(1, end - start)
    best_label, best_overlap = default, 0
    for seg in clip.segments:
        s = int(round(seg.start_s * clip.fps))
        e = int(round(seg.end_s * clip.fps))
        overlap = max(0, min(end, e) - max(start, s))
        if overlap > best_overlap:
            best_label, best_overlap = seg.label, overlap
    if best_overlap / span >= 0.5:
        return best_label
    return default


@dataclass
class WindowSet:
    frames: list[np.ndarray]  # 창별 (window, 33, 4)
    labels: list[str]
    groups: list[str]
    spans: list[tuple[int, int]]
    fps: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.labels)

    def label_counts(self) -> dict[str, int]:
        counts = {cls: 0 for cls in CLASSES}
        for label in self.labels:
            counts[label] = counts.get(label, 0) + 1
        return counts


def build_windows(
    dataset: Dataset,
    window: int = 30,
    stride: int | None = None,
    min_coverage: float = 0.3,
    allow_pad: bool = True,
    default_label: str = "normal",
) -> WindowSet:
    """클립들을 고정 길이 창으로 자른다.

    - `allow_pad`: 창보다 짧은 클립(샘플 4종)은 마지막 프레임을 반복해 채운다(추론과 동일 규칙).
    - `min_coverage`: 창 안 주요 관절 평균 가시성이 이보다 낮으면 버린다.
    """
    window = max(2, int(window))
    stride = max(1, int(stride or window // 2))
    frames_out: list[np.ndarray] = []
    labels: list[str] = []
    groups: list[str] = []
    spans: list[tuple[int, int]] = []
    fps_out: list[float] = []

    for clip in dataset.clips:
        n = len(clip.frames)
        if n == 0:
            continue
        for start, end in iter_windows(n, window, stride):
            chunk = clip.frames[start:end]
            if len(chunk) < window:
                if not allow_pad and n >= window:
                    continue
                chunk = pad_window(chunk, window)
            coverage = float(chunk[:, :, 3].mean()) if chunk.size else 0.0
            if coverage < min_coverage:
                continue
            frames_out.append(chunk)
            labels.append(window_label(clip, start, end, default=default_label))
            groups.append(clip.group_key)
            spans.append((start, end))
            fps_out.append(clip.fps)
    return WindowSet(frames_out, labels, groups, spans, fps_out)


def window_to_input(window_frames: np.ndarray, input_kind: str, fps: float):
    """창 배열 → 모델 입력(특징 벡터 또는 시계열)."""
    from onview.features import window_sequence, window_vector

    if input_kind == "sequence":
        return window_sequence(window_frames, fps=fps)
    return window_vector(window_frames, fps=fps)


def build_xy(
    dataset: Dataset,
    window: int = 30,
    stride: int | None = None,
    input_kind: str = "vector",
    fps: float = 15.0,
    allow_pad: bool = True,
    min_coverage: float = 0.3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, WindowSet]:
    """창 집합 → (X, y, groups, WindowSet). X는 vector면 (N,D), sequence면 (N,W,C)."""
    ws = build_windows(
        dataset, window=window, stride=stride, allow_pad=allow_pad, min_coverage=min_coverage
    )
    if not ws:
        raise ValueError("학습할 창이 없습니다. 데이터 경로·라벨을 확인하세요.")
    index = {cls: i for i, cls in enumerate(CLASSES)}
    x = np.stack(
        [
            window_to_input(w, input_kind, ws.fps[i] if i < len(ws.fps) else fps)
            for i, w in enumerate(ws.frames)
        ]
    ).astype(np.float32)
    y = np.asarray([index[label] for label in ws.labels], dtype=np.int64)
    groups = np.asarray(ws.groups)
    return x, y, groups, ws
