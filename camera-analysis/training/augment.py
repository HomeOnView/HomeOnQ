"""33관절 시계열 증강 — 적은 데이터(샘플 4종)로도 학습 뼈대를 검증하기 위한 도구.

증강은 **원본 좌표계에서** 적용한 뒤 특징을 다시 계산한다. 그래야 특징 추출이
위치·크기에 불변하다는 성질까지 함께 검증된다.

- `jitter`    : 관절 좌표에 작은 가우시안 잡음(검출 오차 흉내)
- `mirror`    : 좌우 반전(x → 1-x, 좌/우 관절 교환)
- `time_warp` : 프레임 보간으로 0.8~1.2배 빠르게/느리게
- `scale_shift`: 화면 위치 이동 + 확대/축소(카메라 설치 거리 차이 흉내)
- `dropout`   : 일부 프레임의 관절 신뢰도(visibility)를 낮춤
"""
from __future__ import annotations

import numpy as np

from onview.features import LANDMARK_COUNT

# 좌/우 교환 쌍 (MediaPipe Pose 33)
_LR_PAIRS = (
    (1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16),
    (17, 18), (19, 20), (21, 22), (23, 24), (25, 26), (27, 28), (29, 30), (31, 32),
)


def jitter(frames: np.ndarray, rng: np.random.Generator, sigma: float = 0.003) -> np.ndarray:
    out = frames.copy()
    noise = rng.normal(0.0, sigma, size=out[:, :, :2].shape).astype(np.float32)
    out[:, :, :2] += noise
    return out


def mirror(frames: np.ndarray) -> np.ndarray:
    out = frames.copy()
    out[:, :, 0] = 1.0 - out[:, :, 0]
    for a, b in _LR_PAIRS:
        tmp = out[:, a, :].copy()
        out[:, a, :] = out[:, b, :]
        out[:, b, :] = tmp
    return out


def time_warp(frames: np.ndarray, rng: np.random.Generator, low: float = 0.8, high: float = 1.2) -> np.ndarray:
    n = frames.shape[0]
    if n < 4:
        return frames.copy()
    factor = float(rng.uniform(low, high))
    src_idx = np.linspace(0, n - 1, max(2, int(round(n * factor))))
    src = np.arange(n)
    out = np.empty((len(src_idx), frames.shape[1], frames.shape[2]), dtype=np.float32)
    for j in range(frames.shape[1]):
        for k in range(frames.shape[2]):
            out[:, j, k] = np.interp(src_idx, src, frames[:, j, k])
    return out


def scale_shift(frames: np.ndarray, rng: np.random.Generator,
                max_shift: float = 0.08, scale_range: tuple[float, float] = (0.85, 1.2)) -> np.ndarray:
    out = frames.copy()
    scale = float(rng.uniform(*scale_range))
    dx = float(rng.uniform(-max_shift, max_shift))
    dy = float(rng.uniform(-max_shift * 0.5, max_shift * 0.5))
    cx, cy = 0.5, 0.6
    out[:, :, 0] = (out[:, :, 0] - cx) * scale + cx + dx
    out[:, :, 1] = (out[:, :, 1] - cy) * scale + cy + dy
    return out


def dropout(frames: np.ndarray, rng: np.random.Generator, p: float = 0.1) -> np.ndarray:
    out = frames.copy()
    mask = rng.random(out.shape[:2]) < p
    out[:, :, 3] = np.where(mask, np.minimum(out[:, :, 3], 0.1), out[:, :, 3])
    return out


def augment(frames: np.ndarray, rng: np.random.Generator, strength: float = 1.0) -> np.ndarray:
    """한 번의 무작위 증강 조합."""
    out = np.asarray(frames, dtype=np.float32)
    out = jitter(out, rng, sigma=0.003 * strength)
    if rng.random() < 0.5:
        out = mirror(out)
    if rng.random() < 0.7:
        out = time_warp(out, rng)
    if rng.random() < 0.7:
        out = scale_shift(out, rng)
    if rng.random() < 0.4:
        out = dropout(out, rng, p=0.08 * strength)
    return out.astype(np.float32)


def expand_clips(clips: list, copies: int, seed: int = 0) -> list:
    """클립 목록을 `copies`배로 늘린 증강 사본을 만든다(원본 포함).

    클립은 `frames`/`fps`/`label`/`clip_id`/`segments` 속성을 가진 객체(`dataset.Clip`)다.
    증강 사본은 `clip_id`에 `-augN`을 붙여 추적할 수 있게 하되 `group_id`는 원본 클립으로
    두어, 교차검증에서 원본과 사본이 서로 다른 폴드로 갈라지지 않게 한다(라벨 누설 방지).
    """
    if copies <= 0:
        return list(clips)
    rng = np.random.default_rng(seed)
    out = list(clips)
    for clip in clips:
        for i in range(copies):
            clone = type(clip)(
                clip_id=f"{clip.clip_id}-aug{i + 1}",
                frames=augment(np.asarray(clip.frames, dtype=np.float32), rng),
                fps=clip.fps,
                label=clip.label,
                segments=list(clip.segments),
                source=clip.source,
                pose_coverage=clip.pose_coverage,
                group_id=getattr(clip, "group_key", clip.clip_id),
            )
            out.append(clone)
    return out


def validate_frames(frames: np.ndarray) -> None:
    if frames.ndim != 3 or frames.shape[1] != LANDMARK_COUNT or frames.shape[2] != 4:
        raise ValueError(f"frames는 (n, 33, 4)여야 합니다: {frames.shape}")
