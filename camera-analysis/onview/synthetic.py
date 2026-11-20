"""시연용 합성 관절좌표 시퀀스 생성기.

실제 카메라 없이도 분석·저장·알림 흐름을 검증할 수 있도록, MediaPipe Pose와 같은
33개 관절 좌표 형식(x, y, z, visibility)으로 사람의 자세를 모델링한다.
"""
from __future__ import annotations

import math
import random
from typing import Any

FPS_DEFAULT = 15.0

# MediaPipe Pose 33 landmark indices
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28
L_HEEL, R_HEEL = 29, 30
L_FOOT, R_FOOT = 31, 32


def _blank_pose() -> list[list[float]]:
    return [[0.5, 0.5, 0.0, 0.5] for _ in range(33)]


def make_pose(
    cx: float = 0.5,
    hip_y: float = 0.55,
    shoulder_y: float = 0.33,
    head_y: float = 0.24,
    ankle_y: float = 0.92,
    torso_lean: float = 0.0,
    spread: float = 1.0,
    noise: float = 0.0,
    rng: random.Random | None = None,
) -> list[list[float]]:
    """직립(=torso_lean 0) 또는 기울어진 자세를 33관절로 만든다."""
    rng = rng or random.Random(0)
    pose = _blank_pose()
    lean = math.radians(torso_lean)
    lean_ratio = min(1.0, abs(torso_lean) / 90.0)
    # 몸통 길이를 고정하고 기울기에 따라 어깨를 회전시킨다.
    # (직립: 어깨가 골반 위 / 누움: 어깨가 골반 옆 같은 높이)
    shoulder_y = hip_y - (hip_y - shoulder_y) * (1 - 0.85 * lean_ratio)
    head_y = shoulder_y - 0.09 * (1 - lean_ratio)
    dx = 0.18 * math.sin(lean)

    def put(idx: int, x: float, y: float, vis: float = 0.9) -> None:
        pose[idx] = [
            round(x + rng.uniform(-noise, noise), 4),
            round(y + rng.uniform(-noise, noise), 4),
            0.0,
            round(max(0.0, min(1.0, vis + rng.uniform(-noise, noise))), 3),
        ]

    sx = cx + dx
    put(NOSE, sx, head_y)
    put(L_SHOULDER, sx - 0.07 * spread, shoulder_y)
    put(R_SHOULDER, sx + 0.07 * spread, shoulder_y)
    put(L_ELBOW, sx - 0.10 * spread, shoulder_y + 0.10)
    put(R_ELBOW, sx + 0.10 * spread, shoulder_y + 0.10)
    put(L_WRIST, sx - 0.09 * spread, shoulder_y + 0.19)
    put(R_WRIST, sx + 0.09 * spread, shoulder_y + 0.19)
    put(L_HIP, cx - 0.06 * spread, hip_y)
    put(R_HIP, cx + 0.06 * spread, hip_y)
    knee_y = hip_y + (ankle_y - hip_y) * 0.52
    put(L_KNEE, cx - 0.055 * spread, knee_y)
    put(R_KNEE, cx + 0.055 * spread, knee_y)
    put(L_ANKLE, cx - 0.05 * spread, ankle_y)
    put(R_ANKLE, cx + 0.05 * spread, ankle_y)
    put(L_HEEL, cx - 0.05 * spread, ankle_y + 0.02, 0.8)
    put(R_HEEL, cx + 0.05 * spread, ankle_y + 0.02, 0.8)
    put(L_FOOT, cx - 0.045 * spread, ankle_y + 0.03, 0.8)
    put(R_FOOT, cx + 0.045 * spread, ankle_y + 0.03, 0.8)
    return pose


def _noise(rng: random.Random, amount: float = 0.0015) -> float:
    return rng.uniform(-amount, amount)


def normal_walk(seconds: float = 10.0, fps: float = FPS_DEFAULT) -> dict[str, Any]:
    rng = random.Random(11)
    frames = []
    n = int(seconds * fps)
    for i in range(n):
        t = i / fps
        cx = 0.5 + 0.015 * math.sin(2 * math.pi * 0.15 * t)
        bob = 0.006 * abs(math.sin(2 * math.pi * 1.2 * t))
        pose = make_pose(cx=cx, hip_y=0.55 + bob, shoulder_y=0.33 + bob, head_y=0.24 + bob, noise=0.0012, rng=rng)
        # 양 발목 교대(걸음)
        swing = 0.035 * math.sin(2 * math.pi * 1.2 * t)
        pose[L_ANKLE][1] = round(0.92 - swing + _noise(rng), 4)
        pose[R_ANKLE][1] = round(0.92 + swing + _noise(rng), 4)
        pose[L_HEEL][1] = round(pose[L_ANKLE][1] + 0.02, 4)
        pose[R_HEEL][1] = round(pose[R_ANKLE][1] + 0.02, 4)
        frames.append(pose)
    return {
        "scenario": "normal",
        "label": "정상 보행",
        "description": "거실을 천천히 걷는 10초 구간(정상 보행)",
        "fps": fps,
        "time_scale": 1.0,
        "night": False,
        "daily_context": {
            "steps": 3380, "night_activity_minutes": 18, "toilet_visits": 6,
            "bedroom_minutes": 470, "inactivity_minutes": 90, "walking_minutes": 55,
            "baseline": {"steps": 4100, "walking_minutes": 62, "night_activity_minutes": 18},
        },
        "frames": frames,
    }


def fall_event(seconds: float = 9.0, fps: float = FPS_DEFAULT) -> dict[str, Any]:
    rng = random.Random(22)
    n = int(seconds * fps)
    fall_at = 2.5
    frames = []
    for i in range(n):
        t = i / fps
        if t < fall_at:
            phase = t / fall_at
            pose = make_pose(hip_y=0.55 + 0.005 * math.sin(t * 6), shoulder_y=0.33, head_y=0.24, noise=0.0012, rng=rng)
            swing = 0.03 * math.sin(2 * math.pi * 1.1 * t)
            pose[L_ANKLE][1] = round(0.92 - swing, 4)
            pose[R_ANKLE][1] = round(0.92 + swing, 4)
        elif t < fall_at + 0.6:
            p = (t - fall_at) / 0.6
            ease = p * p
            pose = make_pose(
                cx=0.5 + 0.04 * ease,
                hip_y=0.55 + 0.33 * ease,
                shoulder_y=0.33 + 0.53 * ease,
                head_y=0.24 + 0.63 * ease,
                ankle_y=0.92 - 0.05 * ease,
                torso_lean=85 * ease,
                spread=1.0 + 0.5 * ease,
                noise=0.0016,
                rng=rng,
            )
        else:
            pose = make_pose(
                cx=0.54, hip_y=0.885, shoulder_y=0.862, head_y=0.875,
                ankle_y=0.93, torso_lean=88, spread=1.5, noise=0.0008, rng=rng,
            )
        frames.append(pose)
    return {
        "scenario": "fall",
        "label": "낙상 발생",
        "description": "걷던 중 2.5초에 넘어져 바닥에 누운 9초 구간",
        "fps": fps,
        "time_scale": 1.0,
        "night": False,
        "daily_context": {
            "steps": 2980, "night_activity_minutes": 75, "toilet_visits": 9,
            "bedroom_minutes": 420, "inactivity_minutes": 265, "walking_minutes": 32,
            "baseline": {"steps": 4100, "walking_minutes": 62, "night_activity_minutes": 18},
        },
        "frames": frames,
    }


def long_inactive(seconds: float = 9.6, fps: float = 5.0, time_scale: float = 1800.0) -> dict[str, Any]:
    """소파에 앉아 거의 움직이지 않는 구간(시간 배속 1800 → 8초 = 4시간)."""
    rng = random.Random(33)
    n = int(seconds * fps)
    frames = []
    for _ in range(n):
        pose = make_pose(
            cx=0.5, hip_y=0.62, shoulder_y=0.42, head_y=0.32, ankle_y=0.90,
            torso_lean=8, noise=0.0006, rng=rng,
        )
        # 아주 미세한 호흡/자세 흔들림만 있다.
        pose[NOSE][1] = round(pose[NOSE][1] + _noise(rng, 0.0004), 4)
        frames.append(pose)
    return {
        "scenario": "inactive",
        "label": "장시간 무활동",
        "description": f"소파에 앉아 {n / fps:.0f}초 동안 거의 움직이지 않은 구간(시간 배속 {time_scale:g}배 = 약 {n / fps * time_scale / 3600:.1f}시간)",
        "fps": fps,
        "time_scale": time_scale,
        "night": True,
        "daily_context": {
            "steps": 640, "night_activity_minutes": 25, "toilet_visits": 5,
            "bedroom_minutes": 510, "inactivity_minutes": 380, "walking_minutes": 9,
            "baseline": {"steps": 4100, "walking_minutes": 62, "night_activity_minutes": 18},
        },
        "frames": frames,
    }


def wandering(seconds: float = 24.0, fps: float = 10.0, time_scale: float = 30.0) -> dict[str, Any]:
    """밤에 거실을 좌우로 반복해 오가는 구간(시간 배속 30 → 24초 = 12분)."""
    rng = random.Random(44)
    n = int(seconds * fps)
    frames = []
    for i in range(n):
        t = i / fps
        cx = 0.5 + 0.22 * math.sin(2 * math.pi * 0.22 * t)
        pose = make_pose(cx=cx, hip_y=0.55, shoulder_y=0.34, head_y=0.25, noise=0.0014, rng=rng)
        swing = 0.03 * math.sin(2 * math.pi * 1.3 * t)
        pose[L_ANKLE][1] = round(0.92 - swing, 4)
        pose[R_ANKLE][1] = round(0.92 + swing, 4)
        frames.append(pose)
    return {
        "scenario": "wandering",
        "label": "배회",
        "description": f"야간 거실 좌우 이동 반복 구간(시간 배속 {time_scale:g}배 = 약 {n / fps * time_scale / 60:.0f}분)",
        "fps": fps,
        "time_scale": time_scale,
        "night": True,
        "daily_context": {
            "steps": 1500, "night_activity_minutes": 65, "toilet_visits": 9,
            "bedroom_minutes": 390, "inactivity_minutes": 130, "walking_minutes": 26,
            "baseline": {"steps": 4100, "walking_minutes": 62, "night_activity_minutes": 18},
        },
        "frames": frames,
    }


BUILDERS = {
    "normal": normal_walk,
    "fall": fall_event,
    "inactive": long_inactive,
    "wandering": wandering,
}


def build_sample(scenario: str) -> dict[str, Any]:
    if scenario not in BUILDERS:
        raise ValueError(f"unknown scenario: {scenario}")
    return BUILDERS[scenario]()
