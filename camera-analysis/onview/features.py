"""33관절 시계열 → 정규화·시계열 특징 (학습·추론 공용).

학습(`training/`)과 실시간 추론(`onview/inference.py`)이 **같은 코드**로 특징을 만들도록
한 곳에 모았다. 여기서 만든 특징 이름·순서·스케일이 모델 메타데이터(`*.json`)의
`feature_version` 과 짝을 이루므로, 규칙을 바꾸면 `FEATURE_VERSION` 을 올려야 한다.
(버전이 다르면 추론기가 모델을 쓰지 않고 규칙 기반으로 자동 폴백한다.)

입력 좌표는 MediaPipe Pose의 정규화 이미지 좌표(x, y: 0~1, 화면 기준 y는 아래로 증가,
z: 상대 깊이, visibility: 0~1)이다. 모든 몸 형태 특징은
- 중심: 양 골반 중점
- 스케일: 어깨 중점~골반 중점 거리(몸통 길이)
로 정규화해 카메라 거리·화면 위치가 달라도 같은 값이 나오게 한다.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

from .schemas import (
    KEY_JOINTS, LEFT_ANKLE, LEFT_HIP, LEFT_KNEE, LEFT_SHOULDER, LEFT_WRIST, NOSE,
    RIGHT_ANKLE, RIGHT_HIP, RIGHT_KNEE, RIGHT_SHOULDER, RIGHT_WRIST,
)

FEATURE_VERSION = "HOMEONQ-FEAT-v1"
LANDMARK_COUNT = 33
DEFAULT_FPS = 15.0

# 프레임 단위 채널(순서 고정). 값은 대부분 '몸통 길이 = 1' 단위로 정규화되어 있다.
SEQUENCE_CHANNELS: tuple[str, ...] = (
    "hip_height",          # 골반~발목 높이(직립 2~3, 누움 0 근처)
    "torso_vertical",      # 골반 y - 어깨 y (직립 +, 누움 0 근처)
    "torso_lean",          # 몸통 기울기 0(직립)~1(누움)
    "head_above_hip",      # 골반 위 머리 높이
    "bbox_height",         # 전신 세로 크기
    "bbox_width",          # 전신 가로 크기
    "stride_width",        # 양 발목 좌우 간격
    "ankle_separation_y",  # 양 발목 높이차(보행 위상, 부호 있음)
    "knee_angle_left",     # 무릎 각도 0~1(1=폄)
    "knee_angle_right",
    "arm_swing",           # 양 손목 높이차
    "wrist_above_hip",     # 골반 위 손목 높이
    "motion",              # 주요 관절 평균 이동량/프레임
    "hip_velocity",        # 골반 수직 속도(1초 기준, +면 하강)
    "lean_velocity",       # 몸통 기울기 변화 속도(1초 기준)
    "center_x",            # 화면 중심 대비 몸통 x(-0.5~0.5)
    "center_x_velocity",   # 몸통 좌우 속도(1초 기준)
    "visible_ratio",       # 신뢰도 있는 주요 관절 비율
)

# 창(window) 단위 집계: 채널별 mean/std/max/min/변화량 + 창 전체 지표
_WINDOW_STATS: tuple[str, ...] = ("mean", "std", "max", "min", "delta")
WINDOW_EXTRA_FEATURES: tuple[str, ...] = (
    "xc_crossings",     # 좌우 속도 부호 반전 횟수(배회)
    "x_range",          # 창 안 몸통 x 이동 폭
    "lying_ratio",      # 누운 자세 비율
    "low_motion_ratio", # 거의 움직이지 않은 프레임 비율
    "peak_hip_velocity",
    "peak_lean_velocity",
    "observable_ratio",
)

VECTOR_FEATURES: tuple[str, ...] = (
    tuple(f"{ch}_{stat}" for ch in SEQUENCE_CHANNELS for stat in _WINDOW_STATS)
    + WINDOW_EXTRA_FEATURES
)

_EPS = 1e-6
_LYING_LEAN = 0.55
_LOW_MOTION = 0.02
_XC_CROSSING_EPS = 0.02
# 전신 크기는 실제 몸 관절만으로 잰다(검출 실패로 0.5,0.5에 찍힌 빈 관절이 섞이면 왜곡된다).
_BODY_IDX = tuple(sorted(set(KEY_JOINTS) | {NOSE}))


# --------------------------------------------------------------------------- #
# 배열 변환
# --------------------------------------------------------------------------- #
def frames_to_array(frames: Sequence[Sequence[Sequence[float]]]) -> np.ndarray:
    """(n, 33, 4) float32 배열로 변환. 관절이 모자라거나 비어 있으면 중립값으로 채운다."""
    if not frames:
        return np.zeros((0, LANDMARK_COUNT, 4), dtype=np.float32)
    out = np.full((len(frames), LANDMARK_COUNT, 4), 0.5, dtype=np.float32)
    out[:, :, 2] = 0.0
    for i, frame in enumerate(frames):
        for j, p in enumerate(frame[:LANDMARK_COUNT]):
            out[i, j, 0] = float(p[0])
            out[i, j, 1] = float(p[1])
            if len(p) > 2:
                out[i, j, 2] = float(p[2])
            out[i, j, 3] = float(p[3]) if len(p) > 3 else 1.0
    return out


def _mid(arr: np.ndarray, a: int, b: int) -> np.ndarray:
    return (arr[:, a, :2] + arr[:, b, :2]) / 2.0


def _knee_angle(arr: np.ndarray, hip: int, knee: int, ankle: int) -> np.ndarray:
    """(골반→무릎)과 (발목→무릎) 사이 각도(0~180°). 뻗으면 180°."""
    a = arr[:, hip, :2] - arr[:, knee, :2]
    b = arr[:, ankle, :2] - arr[:, knee, :2]
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    cos = np.sum(a * b, axis=1) / np.maximum(na * nb, _EPS)
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def sequence_features(
    frames: Sequence[Sequence[Sequence[float]]] | np.ndarray,
    fps: float = DEFAULT_FPS,
) -> np.ndarray:
    """프레임별 특징 (n, len(SEQUENCE_CHANNELS)) float32. 모든 값은 유한하다."""
    arr = frames if isinstance(frames, np.ndarray) else frames_to_array(frames)
    if arr.ndim != 3 or arr.shape[0] == 0:
        return np.zeros((0, len(SEQUENCE_CHANNELS)), dtype=np.float32)
    arr = arr.astype(np.float32, copy=False)
    fps = max(0.1, float(fps))
    dt = 1.0 / fps
    n = arr.shape[0]

    hip = _mid(arr, LEFT_HIP, RIGHT_HIP)
    shoulder = _mid(arr, LEFT_SHOULDER, RIGHT_SHOULDER)
    ankle = _mid(arr, LEFT_ANKLE, RIGHT_ANKLE)
    wrist = _mid(arr, LEFT_WRIST, RIGHT_WRIST)

    torso = shoulder - hip
    torso_len = np.linalg.norm(torso, axis=1)
    scale = np.maximum(torso_len, 0.02)  # 몸통이 찌그러진 프레임에서도 0으로 나누지 않는다

    hip_height = (ankle[:, 1] - hip[:, 1]) / scale
    torso_vertical = (hip[:, 1] - shoulder[:, 1]) / scale
    torso_lean = np.degrees(np.arctan2(np.abs(torso[:, 0]), np.abs(torso[:, 1]) + _EPS)) / 90.0
    head_above_hip = (hip[:, 1] - arr[:, NOSE, 1]) / scale

    xy = arr[:, list(_BODY_IDX), :2]
    bbox_height = (xy[:, :, 1].max(axis=1) - xy[:, :, 1].min(axis=1)) / scale
    bbox_width = (xy[:, :, 0].max(axis=1) - xy[:, :, 0].min(axis=1)) / scale

    stride_width = np.abs(arr[:, LEFT_ANKLE, 0] - arr[:, RIGHT_ANKLE, 0]) / scale
    ankle_separation_y = (arr[:, LEFT_ANKLE, 1] - arr[:, RIGHT_ANKLE, 1]) / scale
    knee_left = _knee_angle(arr, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE) / 180.0
    knee_right = _knee_angle(arr, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE) / 180.0

    arm_swing = np.abs(arr[:, LEFT_WRIST, 1] - arr[:, RIGHT_WRIST, 1]) / scale
    wrist_above_hip = (hip[:, 1] - wrist[:, 1]) / scale

    joints = arr[:, list(KEY_JOINTS), :2]
    if n > 1:
        disp = np.linalg.norm(np.diff(joints, axis=0), axis=2) / scale[1:][:, None]
        motion = np.concatenate([[0.0], disp.mean(axis=1)])
        hip_velocity = np.concatenate([[0.0], np.diff(hip[:, 1]) / scale[1:] / dt])
        lean_velocity = np.concatenate([[0.0], np.diff(torso_lean) / dt])
        center_x_velocity = np.concatenate([[0.0], np.diff(hip[:, 0]) / dt])
    else:
        motion = np.zeros(1, dtype=np.float32)
        hip_velocity = np.zeros(1, dtype=np.float32)
        lean_velocity = np.zeros(1, dtype=np.float32)
        center_x_velocity = np.zeros(1, dtype=np.float32)

    center_x = hip[:, 0] - 0.5
    visible_ratio = (arr[:, list(KEY_JOINTS), 3] >= 0.3).mean(axis=1)

    feats = np.stack(
        [
            np.clip(hip_height, -10, 10),
            np.clip(torso_vertical, -10, 10),
            np.clip(torso_lean, 0, 10),
            np.clip(head_above_hip, -10, 10),
            np.clip(bbox_height, 0, 20),
            np.clip(bbox_width, 0, 20),
            np.clip(stride_width, 0, 10),
            np.clip(ankle_separation_y, -10, 10),
            np.clip(knee_left, 0, 1),
            np.clip(knee_right, 0, 1),
            np.clip(arm_swing, 0, 10),
            np.clip(wrist_above_hip, -10, 10),
            np.clip(motion, 0, 10),
            np.clip(hip_velocity, -20, 20),
            np.clip(lean_velocity, -20, 20),
            np.clip(center_x, -1, 1),
            np.clip(center_x_velocity, -20, 20),
            np.clip(visible_ratio, 0, 1),
        ],
        axis=1,
    )
    return np.nan_to_num(feats, nan=0.0, posinf=10.0, neginf=-10.0).astype(np.float32)


def _crossings(values: np.ndarray) -> int:
    """부호가 바뀌는(±_XC_CROSSING_EPS 초과) 횟수."""
    signs = np.sign(values[np.abs(values) > _XC_CROSSING_EPS])
    if signs.size < 2:
        return 0
    return int(np.sum(signs[1:] != signs[:-1]))


def window_vector(
    frames: Sequence[Sequence[Sequence[float]]] | np.ndarray,
    fps: float = DEFAULT_FPS,
) -> np.ndarray:
    """창 하나의 고정 길이 특징 벡터 (len(VECTOR_FEATURES),)."""
    feats = sequence_features(frames, fps=fps)
    if feats.shape[0] == 0:
        return np.zeros(len(VECTOR_FEATURES), dtype=np.float32)

    parts = []
    for ch in range(feats.shape[1]):
        col = feats[:, ch]
        parts.extend(
            [
                float(col.mean()),
                float(col.std()),
                float(col.max()),
                float(col.min()),
                float(col[-1] - col[0]),
            ]
        )
    c = {name: feats[:, i] for i, name in enumerate(SEQUENCE_CHANNELS)}
    extras = [
        float(_crossings(c["center_x_velocity"])),
        float(c["center_x"].max() - c["center_x"].min()),
        float(np.mean(c["torso_lean"] >= _LYING_LEAN)),
        float(np.mean(c["motion"] < _LOW_MOTION)),
        float(c["hip_velocity"].max()),
        float(np.max(np.abs(c["lean_velocity"]))),
        float(c["visible_ratio"].mean()),
    ]
    out = np.concatenate([np.asarray(parts, dtype=np.float32), np.asarray(extras, dtype=np.float32)])
    return np.nan_to_num(out, nan=0.0, posinf=10.0, neginf=-10.0).astype(np.float32)


def window_sequence(
    frames: Sequence[Sequence[Sequence[float]]] | np.ndarray,
    fps: float = DEFAULT_FPS,
) -> np.ndarray:
    """1D-CNN 입력용 (프레임, 채널) 배열."""
    return sequence_features(frames, fps=fps)


# --------------------------------------------------------------------------- #
# 창 자르기
# --------------------------------------------------------------------------- #
def pad_window(arr: np.ndarray, window: int) -> np.ndarray:
    """창보다 짧은 시퀀스는 가장자리 프레임을 반복해 늘린다(추론 시 짧은 클립 대응)."""
    if arr.shape[0] >= window:
        return arr
    if arr.shape[0] == 0:
        return np.full((window, LANDMARK_COUNT, 4), 0.5, dtype=np.float32)
    pad = np.repeat(arr[-1:], window - arr.shape[0], axis=0)
    return np.concatenate([arr, pad], axis=0)


def iter_windows(n_frames: int, window: int, stride: int | None = None) -> Iterable[tuple[int, int]]:
    """[start, end) 창 목록. 마지막 창은 끝에 맞춰 붙인다."""
    window = max(1, int(window))
    stride = max(1, int(stride or window // 2))
    if n_frames <= 0:
        return []
    if n_frames <= window:
        return [(0, n_frames)]
    spans = list(range(0, n_frames - window + 1, stride))
    if spans[-1] + window < n_frames:
        spans.append(n_frames - window)
    return [(s, s + window) for s in spans]


def describe() -> dict:
    """모델 메타데이터에 기록할 특징 명세."""
    return {
        "feature_version": FEATURE_VERSION,
        "sequence_channels": list(SEQUENCE_CHANNELS),
        "vector_features": list(VECTOR_FEATURES),
        "landmark_count": LANDMARK_COUNT,
    }
