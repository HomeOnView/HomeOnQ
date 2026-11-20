"""라벨 표준화 + 라벨 파일 어댑터(범용 CSV/JSON, AI 허브 라벨 폴더).

표준 클래스는 추론기(`onview.inference.CLASSES`)와 같은 4개다.

    normal(정상) · fall(낙상) · inactivity(장시간 무활동) · wandering(배회)

AI 허브 라벨 JSON은 데이터셋·연도마다 키 이름이 조금씩 다르다. 그래서 특정 스키마를
가정하지 않고 **후보 키를 넓게 탐색**하고, 해석하지 못한 파일은 결과의 `unmatched`에
남겨 사용자가 `--label-map`(JSON)으로 보완할 수 있게 한다. 처음에는
`--limit 20 --dry-run`으로 인식률을 먼저 확인하는 것을 권장한다.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

CLASSES: tuple[str, ...] = ("normal", "fall", "inactivity", "wandering")
CLASS_LABELS_KO = {"normal": "정상", "fall": "낙상", "inactivity": "장시간 무활동", "wandering": "배회"}

LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "normal": (
        "normal", "정상", "정상행동", "일상", "일상행동", "일반", "보행", "걷기", "산책",
        "walk", "walking", "daily", "daily_life", "regular",
    ),
    "fall": (
        "fall", "falling", "fallen", "fall_down", "falldown", "낙상", "낙상사고", "쓰러짐",
        "넘어짐", "전도", "추락",
    ),
    "inactivity": (
        "inactivity", "inactive", "no_motion", "nomotion", "immobility", "still", "stillness",
        "무활동", "장시간무활동", "장시간 무활동", "미동작", "움직임없음", "움직임 없음", "부동",
    ),
    "wandering": (
        "wandering", "wander", "pacing", "loitering", "배회", "배회행동", "서성", "서성거림",
        "서성임", "돌아다님",
    ),
}

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv"}

_PATH_KEYS = ("path", "file", "video", "video_path", "video_name", "filename", "file_name",
              "source", "source_file", "src", "clip", "clip_path")
_LABEL_KEYS = ("label", "labels", "class", "class_name", "category", "behavior", "behavior_name",
               "action", "action_name", "type", "abnormal_type", "event", "event_type", "name")
_START_KEYS = ("start", "start_s", "start_time", "start_sec", "begin", "begin_time", "from")
_END_KEYS = ("end", "end_s", "end_time", "end_sec", "finish", "to")
_ID_KEYS = ("clip_id", "id", "uid", "name", "clip_name", "video_id")
_SEGMENT_KEYS = ("segments", "annotations", "instances", "actions", "spans", "events", "labels")


def _norm(text: Any) -> str:
    return re.sub(r"[\s_\-\.]+", "", str(text)).lower()


_ALIAS_INDEX = {_norm(alias): cls for cls, aliases in LABEL_ALIASES.items() for alias in aliases}


def normalize_label(value: Any) -> str | None:
    """라벨 문자열 → 표준 클래스. 모르면 None."""
    if value is None:
        return None
    text = _norm(value)
    if not text:
        return None
    if text in _ALIAS_INDEX:
        return _ALIAS_INDEX[text]
    # '정상_보행_01' 처럼 앞뒤에 수식이 붙은 경우: 긴 별칭부터 부분 일치
    for alias in sorted(_ALIAS_INDEX, key=len, reverse=True):
        if len(alias) >= 2 and alias in text:
            return _ALIAS_INDEX[alias]
    return None


@dataclass
class Segment:
    start_s: float
    end_s: float
    label: str

    def as_dict(self) -> dict[str, Any]:
        return {"start": round(self.start_s, 3), "end": round(self.end_s, 3), "label": self.label}


@dataclass
class ClipSpec:
    """영상 1개 + 라벨(및 선택적 구간)."""

    label: str
    video_path: str | None = None
    clip_id: str = ""
    fps: float | None = None
    start_s: float | None = None
    end_s: float | None = None
    segments: list[Segment] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "label": self.label,
            "video_path": self.video_path,
            "fps": self.fps,
            "start": self.start_s,
            "end": self.end_s,
            "segments": [s.as_dict() for s in self.segments],
            "note": self.note,
        }


@dataclass
class LabelLoadResult:
    clips: list[ClipSpec] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def extend(self, other: "LabelLoadResult") -> None:
        self.clips.extend(other.clips)
        self.unmatched.extend(other.unmatched)
        self.skipped.extend(other.skipped)


# --------------------------------------------------------------------------- #
# 범용 라벨 파일(CSV/JSON)
# --------------------------------------------------------------------------- #
def _pick(row: dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {_norm(k): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(_norm(key))
        if value not in (None, ""):
            return value
    return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _spec_from_row(row: dict[str, Any], label_map: dict[str, str], base_dir: Path) -> tuple[ClipSpec | None, str]:
    raw_label = _pick(row, _LABEL_KEYS)
    label = label_map.get(str(raw_label)) or normalize_label(raw_label)
    if label is None:
        return None, f"라벨을 해석하지 못했습니다: {raw_label!r}"
    video = _pick(row, _PATH_KEYS)
    video_path = str(video) if video else None
    if video_path and not Path(video_path).is_absolute():
        candidate = base_dir / video_path
        video_path = str(candidate if candidate.exists() else video_path)
    clip_id = _pick(row, _ID_KEYS)
    if not clip_id and video_path:
        clip_id = Path(str(video_path)).stem
    segments = _segments_from_row(row, label_map)
    return (
        ClipSpec(
            label=label,
            video_path=video_path,
            clip_id=str(clip_id or label),
            fps=_to_float(_pick(row, ("fps",))),
            # start/end 는 '라벨 구간'으로 해석하고 추출 범위는 영상 전체로 둔다(긴 영상은 --max-seconds).
            start_s=None,
            end_s=None,
            segments=segments,
        ),
        "",
    )


def _segments_from_row(row: dict[str, Any], label_map: dict[str, str]) -> list[Segment]:
    segments: list[Segment] = []
    for key in _SEGMENT_KEYS:
        value = row.get(key)
        if isinstance(value, list):
            segments.extend(_segments_from_list(value, label_map))
            if segments:
                return segments
    # CSV 처럼 start/end 열만 있는 경우: 그 구간을 라벨 구간으로 보고, 앞 구간은 정상으로 둔다.
    start = _to_float(_pick(row, _START_KEYS))
    end = _to_float(_pick(row, _END_KEYS))
    raw = _pick(row, _LABEL_KEYS)
    label = label_map.get(str(raw)) or normalize_label(raw)
    if start is not None and end is not None and label is not None and end > start:
        if start > 0:
            segments.append(Segment(0.0, start, "normal"))
        segments.append(Segment(start, end, label))
    return segments


def _segments_from_list(items: list[Any], label_map: dict[str, str]) -> list[Segment]:
    out: list[Segment] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = _to_float(_pick(item, _START_KEYS))
        end = _to_float(_pick(item, _END_KEYS))
        raw = _pick(item, _LABEL_KEYS)
        label = label_map.get(str(raw)) or normalize_label(raw)
        if start is None or end is None or label is None or end <= start:
            continue
        out.append(Segment(start, end, label))
    return out


def load_label_file(path: str | Path, label_map: dict[str, str] | None = None) -> LabelLoadResult:
    """CSV 또는 JSON 라벨 파일을 읽는다.

    - CSV: 첫 행이 헤더. (`path`,`label` 열 이름은 위 후보 목록에서 자동 인식)
    - JSON: `[{...}, ...]` 또는 `{"items": [...]}` / `{"clips": [...]}` / `{"data": [...]}`
    """
    path = Path(path)
    label_map = label_map or {}
    result = LabelLoadResult()
    if not path.exists():
        result.skipped.append({"file": str(path), "reason": "파일 없음"})
        return result

    if path.suffix.lower() in {".csv", ".tsv"}:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=delimiter):
                spec, reason = _spec_from_row(dict(row), label_map, path.parent)
                if spec is None:
                    result.unmatched.append({"file": path.name, "row": dict(row), "reason": reason})
                else:
                    result.clips.append(spec)
        return result

    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]]
    if isinstance(data, list):
        rows = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        rows = []
        for key in ("items", "clips", "data", "records", "list"):
            if isinstance(data.get(key), list):
                rows = [r for r in data[key] if isinstance(r, dict)]
                break
        if not rows:
            rows = [data]
    else:
        result.skipped.append({"file": str(path), "reason": "알 수 없는 JSON 구조"})
        return result

    for row in rows:
        spec, reason = _spec_from_row(row, label_map, path.parent)
        if spec is None:
            result.unmatched.append({"file": path.name, "row": row, "reason": reason})
        else:
            result.clips.append(spec)
    return result


# --------------------------------------------------------------------------- #
# AI 허브 라벨 폴더
# --------------------------------------------------------------------------- #
def _deep_strings(node: Any, depth: int = 0) -> Iterable[str]:
    if depth > 6:
        return
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _deep_strings(value, depth + 1)
    elif isinstance(node, list):
        for value in node[:200]:
            yield from _deep_strings(value, depth + 1)


def _find_label_text(node: Any, depth: int = 0) -> Any:
    """JSON 트리에서 라벨 후보 키를 먼저 찾고, 없으면 문자열 중 별칭 일치를 찾는다."""
    if depth > 6:
        return None
    if isinstance(node, dict):
        for key in _LABEL_KEYS:
            for actual, value in node.items():
                if _norm(actual) == _norm(key) and isinstance(value, (str, int)):
                    return value
        for value in node.values():
            found = _find_label_text(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node[:200]:
            found = _find_label_text(value, depth + 1)
            if found is not None:
                return found
    return None


def _find_video_hint(node: Any, depth: int = 0) -> str | None:
    if depth > 6:
        return None
    if isinstance(node, dict):
        for key in _PATH_KEYS:
            for actual, value in node.items():
                if _norm(actual) == _norm(key) and isinstance(value, str):
                    if Path(value).suffix.lower() in VIDEO_EXTS or "/" in value or "\\" in value:
                        return value
        for value in node.values():
            found = _find_video_hint(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for value in node[:200]:
            found = _find_video_hint(value, depth + 1)
            if found:
                return found
    return None


def collect_aihub_labels(
    label_root: str | Path,
    video_root: str | Path | None = None,
    label_map: dict[str, str] | None = None,
    limit: int | None = None,
) -> LabelLoadResult:
    """AI 허브 라벨 폴더(JSON)를 훑어 클립 목록을 만든다.

    JSON 키 이름이 데이터셋마다 달라서, 라벨은 후보 키→문자열 별칭 순으로,
    영상 경로는 후보 키→확장자→`video_root`의 같은 이름 파일 순으로 찾는다.
    해석 실패 항목은 `unmatched`에 남는다.
    """
    label_root = Path(label_root)
    video_root = Path(video_root) if video_root else None
    label_map = label_map or {}
    result = LabelLoadResult()
    if not label_root.exists():
        result.skipped.append({"file": str(label_root), "reason": "라벨 폴더 없음"})
        return result

    video_index: dict[str, Path] = {}
    if video_root and video_root.exists():
        for p in video_root.rglob("*"):
            if p.suffix.lower() in VIDEO_EXTS:
                video_index.setdefault(p.stem.lower(), p)

    files = sorted(label_root.rglob("*.json"))
    if limit:
        files = files[:limit]
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            result.skipped.append({"file": str(path), "reason": f"JSON 파싱 실패: {exc}"})
            continue

        raw_label = _find_label_text(data)
        label = label_map.get(str(raw_label)) or normalize_label(raw_label)
        if label is None:
            # 마지막 시도: 파일명/경로에 별칭이 들어있는지(예: .../낙상/xxx.json)
            label = normalize_label(path.parent.name) or normalize_label(path.stem)
        if label is None:
            result.unmatched.append({"file": str(path), "reason": f"라벨 미인식({raw_label!r})"})
            continue

        video_path = _find_video_hint(data)
        resolved: Path | None = None
        if video_path:
            candidate = Path(video_path)
            for base in (path.parent, video_root, label_root):
                if base and (Path(base) / candidate).exists():
                    resolved = Path(base) / candidate
                    break
            if resolved is None and candidate.exists():
                resolved = candidate
        if resolved is None:
            stem_match = video_index.get(path.stem.lower())
            if stem_match:
                resolved = stem_match
        if resolved is None:
            result.unmatched.append({"file": str(path), "label": label, "reason": "영상 경로 미확인"})
            continue

        segments: list[Segment] = []
        if isinstance(data, dict):
            for key in _SEGMENT_KEYS:
                value = data.get(key)
                if isinstance(value, list):
                    segments.extend(_segments_from_list(value, label_map))
                    if segments:
                        break
        result.clips.append(
            ClipSpec(
                label=label,
                video_path=str(resolved),
                clip_id=path.stem,
                segments=segments,
                note=f"aihub:{path.name}",
            )
        )
    return result


def load_label_map(path: str | Path | None) -> dict[str, str]:
    """`--label-map` JSON: {"원본 라벨": "fall", ...}."""
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("label-map은 {원본 라벨: 표준 클래스} 형태의 JSON이어야 합니다")
    out: dict[str, str] = {}
    for key, value in data.items():
        cls = str(value)
        if cls not in CLASSES:
            raise ValueError(f"label-map 값은 {CLASSES} 중 하나여야 합니다: {value!r}")
        out[str(key)] = cls
    return out
