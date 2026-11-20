"""영상 → 33관절 시계열 전처리 (MediaPipe Pose).

    # 1) 이미 있는 샘플 4종으로 즉시 뼈대 검증(영상·MediaPipe 없이 동작)
    python -m training.extract_landmarks --samples --out data/samples

    # 2) 라벨 CSV/JSON + 영상 폴더
    python -m training.extract_landmarks --labels labels.csv \
        --video-root ./videos --out data/dataset

    # 3) AI 허브 라벨 폴더(JSON) — 먼저 인식률만 확인
    python -m training.extract_landmarks --aihub-root ./AIHub/라벨링데이터 \
        --video-root ./AIHub/원천데이터 --out data/aihub --limit 20 --dry-run

출력: `<out>/<clip_id>.npz` (frames (n,33,4) float32 + fps/label) + `<out>/manifest.json`.
MediaPipe가 없거나 네이티브 런타임을 쓸 수 없는 환경에서는 `--samples` 모드만 동작하며,
영상 모드는 명확한 안내 메시지와 함께 종료한다.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from onview.features import LANDMARK_COUNT
from onview.skeleton_source import SCENARIO_FILES, load_sequence

from .dataset import save_clip, write_manifest
from .labels import (
    CLASSES, ClipSpec, LabelLoadResult, Segment, collect_aihub_labels, load_label_file,
    load_label_map, normalize_label,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_DIR = ROOT / "samples"

# 샘플 4종의 구간 라벨(합성 생성기와 동일한 시나리오). 낙상은 2.5초에 시작한다.
SAMPLE_SEGMENTS: dict[str, list[Segment]] = {
    "normal": [Segment(0.0, 1e6, "normal")],
    "fall": [Segment(0.0, 2.3, "normal"), Segment(2.3, 1e6, "fall")],
    "inactive": [Segment(0.0, 1e6, "inactivity")],
    "wandering": [Segment(0.0, 1e6, "wandering")],
}


@dataclass
class ExtractStats:
    entries: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)

    def as_extra(self) -> dict[str, Any]:
        return {
            "unmatched": self.unmatched,
            "skipped": self.skipped,
            "class_counts": _class_counts(self.entries),
        }


def _class_counts(entries: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {cls: 0 for cls in CLASSES}
    for entry in entries:
        counts[entry["label"]] = counts.get(entry["label"], 0) + 1
    return counts


# --------------------------------------------------------------------------- #
# 영상 읽기 / 자세 추출
# --------------------------------------------------------------------------- #
def sample_video_frames(
    path: str | Path,
    target_fps: float = 15.0,
    max_seconds: float | None = None,
    start_s: float | None = None,
    end_s: float | None = None,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    """OpenCV로 영상을 읽어 목표 fps로 솎아낸 BGR 프레임 목록을 만든다."""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - cv2 미설치
        raise RuntimeError(f"영상 전처리에는 opencv가 필요합니다(pip install opencv-python-headless): {exc}") from exc

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없습니다: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if not src_fps or src_fps <= 0 or src_fps > 240:
        src_fps = 30.0
    step = max(1, int(round(src_fps / max(0.1, target_fps))))
    effective_fps = src_fps / step

    frames: list[np.ndarray] = []
    idx = 0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / src_fps
            idx += 1
            if start_s is not None and t < start_s:
                continue
            if end_s is not None and t > end_s:
                break
            if max_seconds is not None and (idx / src_fps) - (start_s or 0.0) > max_seconds:
                break
            if (idx - 1) % step == 0:
                frames.append(frame)
    finally:
        cap.release()
    stats = {
        "source_fps": round(float(src_fps), 2),
        "effective_fps": round(float(effective_fps), 2),
        "sampled_frames": len(frames),
        "total_frames": total,
    }
    return frames, stats


def _interpolate_missing(poses: list[np.ndarray | None]) -> tuple[np.ndarray, float]:
    """검출 실패 프레임을 선형 보간한다. 시간축(fps)은 유지된다."""
    n = len(poses)
    if n == 0:
        return np.zeros((0, LANDMARK_COUNT, 4), dtype=np.float32), 0.0
    valid = np.array([p is not None for p in poses])
    coverage = float(valid.mean()) if n else 0.0
    if not valid.any():
        return np.zeros((0, LANDMARK_COUNT, 4), dtype=np.float32), 0.0
    out = np.zeros((n, LANDMARK_COUNT, 4), dtype=np.float32)
    idx_valid = np.flatnonzero(valid)
    for i in range(n):
        if poses[i] is not None:
            out[i] = poses[i]
    if idx_valid.size == 1:
        out[:] = out[idx_valid[0]]
        return out, coverage
    grid = np.arange(n)
    for j in range(LANDMARK_COUNT):
        for k in range(4):
            values = out[idx_valid, j, k]
            out[:, j, k] = np.interp(grid, idx_valid, values)
    return out, coverage


def extract_poses_from_video(
    path: str | Path,
    estimator: Any,
    target_fps: float = 15.0,
    max_seconds: float | None = None,
    start_s: float | None = None,
    end_s: float | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """영상 → (frames (n,33,4), fps, 통계). `estimator.estimate(BGR)` 를 주입할 수 있다."""
    frames, stats = sample_video_frames(path, target_fps, max_seconds, start_s, end_s)
    poses: list[np.ndarray | None] = []
    for frame in frames:
        result = estimator.estimate(frame)
        poses.append(None if result is None else np.asarray(result, dtype=np.float32))
    arr, coverage = _interpolate_missing(poses)
    stats.update({"pose_coverage": round(coverage, 3), "frames": int(arr.shape[0])})
    return arr, stats


def mediapipe_estimator():
    """MediaPipe Pose 추정기. 사용할 수 없으면 명확한 예외를 던진다."""
    from onview.pose_analyzer import PoseAnalyzer

    analyzer = PoseAnalyzer(use_mock=False)
    if analyzer.backend == "mock":
        raise RuntimeError(
            "MediaPipe Pose를 사용할 수 없습니다: "
            f"{analyzer.fallback_reason or '알 수 없는 이유'}\n"
            "  → pip install mediapipe opencv-python-headless && python scripts/download_models.py"
        )
    return analyzer


# --------------------------------------------------------------------------- #
# 데이터셋 구축
# --------------------------------------------------------------------------- #
def build_from_samples(
    out_dir: str | Path,
    sample_dir: str | Path | None = None,
    write_json: bool = False,
) -> ExtractStats:
    """이미 있는 샘플 33관절 시퀀스 4종을 데이터셋(.npz)으로 변환한다."""
    sample_dir = Path(sample_dir or DEFAULT_SAMPLE_DIR)
    stats = ExtractStats()
    for scenario, filename in SCENARIO_FILES.items():
        path = sample_dir / filename
        if not path.exists():
            stats.skipped.append({"clip_id": scenario, "reason": f"샘플 없음: {path}"})
            continue
        seq = load_sequence(path)
        label = normalize_label(seq.label) or ("normal" if scenario == "normal" else None)
        label = label or normalize_label(scenario)
        if label is None:
            stats.unmatched.append({"clip_id": scenario, "reason": f"라벨 미인식: {seq.label}"})
            continue
        segments = SAMPLE_SEGMENTS.get(scenario, [])
        entry = save_clip(
            out_dir, clip_id=scenario, frames=np.asarray(seq.frames, dtype=np.float32),
            fps=seq.fps, label=label, segments=segments, source=path.name, pose_coverage=1.0,
        )
        stats.entries.append(entry)
        if write_json:
            import shutil

            shutil.copyfile(path, Path(out_dir) / filename)
    return stats


def build_from_specs(
    specs: Sequence[ClipSpec],
    out_dir: str | Path,
    estimator: Any | None = None,
    target_fps: float = 15.0,
    max_seconds: float | None = None,
    min_coverage: float = 0.5,
    write_json: bool = False,
) -> ExtractStats:
    """클립 목록을 실제 영상에서 33관절로 추출한다."""
    out_dir = Path(out_dir)
    stats = ExtractStats()
    estimator = estimator or mediapipe_estimator()
    for spec in specs:
        if not spec.video_path:
            stats.skipped.append({"clip_id": spec.clip_id, "reason": "영상 경로 없음"})
            continue
        video = Path(spec.video_path)
        if not video.exists():
            stats.skipped.append({"clip_id": spec.clip_id, "reason": f"영상 없음: {video}"})
            continue
        try:
            arr, info = extract_poses_from_video(
                video, estimator, target_fps=target_fps, max_seconds=max_seconds,
                start_s=spec.start_s, end_s=spec.end_s,
            )
        except Exception as exc:
            stats.skipped.append({"clip_id": spec.clip_id, "reason": f"추출 실패: {exc}"})
            continue
        if arr.shape[0] < 5:
            stats.skipped.append({"clip_id": spec.clip_id, "reason": "관절 검출 프레임 부족"})
            continue
        if info["pose_coverage"] < min_coverage:
            stats.skipped.append({
                "clip_id": spec.clip_id,
                "reason": f"포즈 검출률 낮음({info['pose_coverage']:.2f} < {min_coverage})",
            })
            continue
        entry = save_clip(
            out_dir, clip_id=spec.clip_id, frames=arr, fps=info.get("effective_fps", target_fps), label=spec.label,
            segments=spec.segments, source=str(video), pose_coverage=info["pose_coverage"],
        )
        entry.update({
            "start": spec.start_s, "end": spec.end_s,
            "source_fps": info.get("source_fps"), "note": spec.note,
        })
        stats.entries.append(entry)
        if write_json:
            from onview.skeleton_source import save_sequence

            save_sequence(
                out_dir / f"{entry['clip_id']}.json",
                {
                    "scenario": spec.label, "label": spec.label, "fps": info.get("effective_fps", target_fps),
                    "description": f"{video.name} ({spec.label})", "frames": arr.tolist(),
                },
            )
    return stats


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="training.extract_landmarks",
        description="영상/샘플 → 33관절 시계열(.npz) 전처리",
    )
    parser.add_argument("--out", required=True, help="출력 폴더(데이터셋)")
    src = parser.add_argument_group("입력(하나 이상)")
    src.add_argument("--samples", action="store_true", help="저장소 샘플 4종을 변환(영상 불필요)")
    src.add_argument("--labels", help="라벨 CSV/JSON 경로")
    src.add_argument("--aihub-root", help="AI 허브 라벨 JSON 폴더")
    src.add_argument("--video-root", help="영상 폴더(라벨 파일의 상대 경로 해석)")
    src.add_argument("--label-map", help='라벨 매핑 JSON: {"원본 라벨": "fall"}')
    parser.add_argument("--fps", type=float, default=15.0, help="추출 목표 fps(기본 15)")
    parser.add_argument("--max-seconds", type=float, default=None, help="클립당 최대 길이(초)")
    parser.add_argument("--min-coverage", type=float, default=0.5, help="포즈 검출률 하한")
    parser.add_argument("--limit", type=int, default=None, help="AI 허브 라벨 파일 개수 제한")
    parser.add_argument("--dry-run", action="store_true", help="추출 없이 인식 결과만 확인")
    parser.add_argument("--json", action="store_true", help="샘플 호환 .json 시퀀스도 함께 저장")
    parser.add_argument("--append", action="store_true", help="기존 manifest.json 뒤에 추가")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.out)
    label_map = load_label_map(args.label_map)

    if not (args.samples or args.labels or args.aihub_root):
        print("❌ --samples / --labels / --aihub-root 중 하나가 필요합니다.", file=sys.stderr)
        return 2

    stats = ExtractStats()
    specs: list[ClipSpec] = []

    if args.samples:
        stats_s = build_from_samples(out_dir, write_json=args.json)
        stats.entries.extend(stats_s.entries)
        stats.skipped.extend(stats_s.skipped)
        stats.unmatched.extend(stats_s.unmatched)
        print(f"✅ 샘플 변환: {len(stats_s.entries)}개 클립")

    if args.labels:
        loaded: LabelLoadResult = load_label_file(args.labels, label_map)
        specs.extend(loaded.clips)
        stats.skipped.extend(loaded.skipped)
        stats.unmatched.extend(loaded.unmatched)
        print(f"· 라벨 파일: {len(loaded.clips)}개 클립 인식, 미인식 {len(loaded.unmatched)}건")

    if args.aihub_root:
        loaded = collect_aihub_labels(
            args.aihub_root, video_root=args.video_root, label_map=label_map, limit=args.limit
        )
        specs.extend(loaded.clips)
        stats.skipped.extend(loaded.skipped)
        stats.unmatched.extend(loaded.unmatched)
        print(f"· AI 허브 라벨: {len(loaded.clips)}개 클립 인식, 미인식 {len(loaded.unmatched)}건")

    if specs and args.dry_run:
        for spec in specs[:20]:
            print(f"   {spec.clip_id:40s} {spec.label:10s} {spec.video_path}")
        print(f"(dry-run) 추출 대상 {len(specs)}개 — 실제 추출은 --dry-run 없이 다시 실행하세요.")
        _print_issues(stats)
        return 0

    if specs:
        extracted = build_from_specs(
            specs, out_dir, target_fps=args.fps, max_seconds=args.max_seconds,
            min_coverage=args.min_coverage, write_json=args.json,
        )
        stats.entries.extend(extracted.entries)
        stats.skipped.extend(extracted.skipped)
        stats.unmatched.extend(extracted.unmatched)
        print(f"✅ 영상 추출: {len(extracted.entries)}개 클립 성공, {len(extracted.skipped)}개 건너뜀")

    if not stats.entries:
        print("❌ 저장된 클립이 없습니다.", file=sys.stderr)
        _print_issues(stats)
        return 1

    entries = stats.entries
    if args.append:
        manifest = out_dir / "manifest.json"
        if manifest.exists():
            import json

            existing = json.loads(manifest.read_text(encoding="utf-8"))
            known = {e["clip_id"] for e in entries}
            entries = [e for e in existing.get("clips", []) if e.get("clip_id") not in known] + entries
    write_manifest(out_dir, entries, extra=stats.as_extra())
    print(f"📄 매니페스트: {(out_dir / 'manifest.json')}")
    print(f"   클래스 분포: {_class_counts(entries)}")
    _print_issues(stats)
    return 0


def _print_issues(stats: ExtractStats) -> None:
    if stats.unmatched:
        print(f"⚠️ 라벨/영상 미인식 {len(stats.unmatched)}건 (앞 5건)")
        for item in stats.unmatched[:5]:
            print(f"   - {item}")
    if stats.skipped:
        print(f"⚠️ 건너뜀 {len(stats.skipped)}건 (앞 5건)")
        for item in stats.skipped[:5]:
            print(f"   - {item}")


if __name__ == "__main__":
    sys.exit(main())
