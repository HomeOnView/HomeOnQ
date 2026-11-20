"""관절좌표 시퀀스 파일(.json) 로더/저장기."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .detector import analyze_sequence
from .schemas import SequenceAnalysis

SCENARIO_FILES = {
    "normal": "normal_walk.json",
    "fall": "fall_event.json",
    "inactive": "long_inactive.json",
    "wandering": "wandering.json",
}


@dataclass
class SampleSequence:
    scenario: str
    label: str
    description: str
    fps: float
    time_scale: float
    night: bool
    frames: list
    path: Path | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def load_sequence(path: str | Path) -> SampleSequence:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = data.get("frames") or []
    if not frames:
        raise ValueError(f"시퀀스에 frames가 없습니다: {path}")
    if len(frames[0]) != 33:
        raise ValueError(f"33개 관절 좌표가 필요합니다({len(frames[0])}개 발견): {path}")
    return SampleSequence(
        scenario=data.get("scenario", path.stem),
        label=data.get("label", path.stem),
        description=data.get("description", ""),
        fps=float(data.get("fps", 15.0)),
        time_scale=float(data.get("time_scale", 1.0)),
        night=bool(data.get("night", False)),
        frames=frames,
        path=path,
        meta={k: v for k, v in data.items() if k not in {"frames"}},
    )


def save_sequence(path: str | Path, data: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario": data["scenario"],
        "label": data.get("label", data["scenario"]),
        "description": data.get("description", ""),
        "coordinate_system": "mediapipe_pose_33_normalized_image",
        "fps": data.get("fps", 15.0),
        "time_scale": data.get("time_scale", 1.0),
        "night": data.get("night", False),
        # daily_context 등 시나리오별 메타데이터를 보존한다.
        **{k: v for k, v in data.items() if k not in {
            "scenario", "label", "description", "coordinate_system", "fps", "time_scale", "night", "frames"}},
        "frames": data["frames"],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def list_samples(sample_dir: str | Path) -> list[Path]:
    sample_dir = Path(sample_dir)
    if not sample_dir.exists():
        return []
    return sorted(p for p in sample_dir.glob("*.json"))


def analyze_sample(path: str | Path, config=None) -> SequenceAnalysis:
    seq = load_sequence(path)
    return analyze_sequence(
        seq.frames, fps=seq.fps, time_scale=seq.time_scale, config=config, label=seq.label
    )
