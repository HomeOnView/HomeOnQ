"""관절 좌표 시퀀스 → 낙상 / 장시간 무활동 / 배회 감지 (규칙 기반 v1).

입력 좌표는 MediaPipe Pose의 정규화 이미지 좌표(x, y: 0~1, 화면 기준 y는 아래로 증가,
z: 상대 깊이, visibility: 0~1)를 따른다. 미터 단위가 아니므로 속도·거리 임계값은
'정규화 좌표/초' 기준이며, 카메라 설치 높이에 따라 현장 보정이 필요하다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import atan2, degrees

from .config import CONFIG, Config
from .schemas import (
    DetectedEvent, LEFT_ANKLE, LEFT_HIP, LEFT_KNEE, LEFT_SHOULDER, LEFT_WRIST,
    KEY_JOINTS, NOSE, RIGHT_ANKLE, RIGHT_HIP, RIGHT_KNEE, RIGHT_SHOULDER, RIGHT_WRIST,
    SequenceAnalysis,
)

Frame = list[list[float]]


def _point(frame: Frame, idx: int) -> tuple[float, float, float]:
    if idx >= len(frame):
        return (0.5, 0.5, 0.0)
    p = frame[idx]
    return (float(p[0]), float(p[1]), float(p[3]) if len(p) > 3 else 1.0)


def _mid(frame: Frame, a: int, b: int) -> tuple[float, float]:
    ax, ay, _ = _point(frame, a)
    bx, by, _ = _point(frame, b)
    return ((ax + bx) / 2, (ay + by) / 2)


def hip_y(frame: Frame) -> float:
    return _mid(frame, LEFT_HIP, RIGHT_HIP)[1]


def shoulder_y(frame: Frame) -> float:
    return _mid(frame, LEFT_SHOULDER, RIGHT_SHOULDER)[1]


def body_center(frame: Frame) -> tuple[float, float]:
    hx, hy = _mid(frame, LEFT_HIP, RIGHT_HIP)
    sx, sy = _mid(frame, LEFT_SHOULDER, RIGHT_SHOULDER)
    return ((hx + sx) / 2, (hy + sy) / 2)


def torso_angle_deg(frame: Frame) -> float:
    """몸통 기울기: 0° = 직립, 90° = 완전히 누움."""
    sx, sy = _mid(frame, LEFT_SHOULDER, RIGHT_SHOULDER)
    hx, hy = _mid(frame, LEFT_HIP, RIGHT_HIP)
    dx, dy = sx - hx, sy - hy
    if dx == 0 and dy == 0:
        return 0.0
    return degrees(atan2(abs(dx), abs(dy)))


def motion_energy(prev: Frame | None, cur: Frame, joints=KEY_JOINTS) -> float:
    if prev is None:
        return 0.0
    total, count = 0.0, 0
    for idx in joints:
        x1, y1, v1 = _point(prev, idx)
        x2, y2, v2 = _point(cur, idx)
        if v1 < 0.2 or v2 < 0.2:
            continue
        total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        count += 1
    return total / count if count else 0.0


def count_steps(frames: list[Frame]) -> int:
    """양 발목의 상하 교대(부호 변화)로 걸음 수를 센다."""
    steps, sign, last_diff = 0, 0, 0.0
    for frame in frames:
        lx, ly, lv = _point(frame, LEFT_ANKLE)
        rx, ry, rv = _point(frame, RIGHT_ANKLE)
        if lv < 0.3 or rv < 0.3:
            continue
        diff = ly - ry
        if abs(diff) < 0.02:
            continue
        new_sign = 1 if diff > 0 else -1
        if sign != 0 and new_sign != sign:
            steps += 1
        sign = new_sign
        last_diff = diff
    return steps


def _longest_inactive_run(energies: list[float], threshold: float) -> tuple[int, int, int]:
    best_start, best_len, start = 0, 0, None
    for i, e in enumerate(energies):
        if e < threshold:
            if start is None:
                start = i
            length = i - start + 1
            if length > best_len:
                best_start, best_len = start, length
        else:
            start = None
    return best_start, best_len, sum(1 for e in energies if e < threshold)


def analyze_sequence(
    frames: list[Frame],
    fps: float = 15.0,
    time_scale: float = 1.0,
    config: Config | None = None,
    started_at: datetime | None = None,
    label: str = "",
) -> SequenceAnalysis:
    cfg = config or CONFIG
    if not frames:
        return SequenceAnalysis([], fps, time_scale, [], {}, 0.0, 0.0)
    fps = max(0.1, float(fps))
    started_at = started_at or datetime.now(timezone.utc)

    angles = [torso_angle_deg(f) for f in frames]
    hips = [hip_y(f) for f in frames]
    shoulders = [shoulder_y(f) for f in frames]
    energies = [0.0] + [motion_energy(frames[i - 1], frames[i]) for i in range(1, len(frames))]

    # --- 낙상 ---
    events: list[DetectedEvent] = []
    window = max(1, int(round(fps * 0.4)))
    drop_speeds = [0.0] * len(frames)
    for i in range(window, len(frames)):
        drop_speeds[i] = (hips[i] - hips[i - window]) / (window / fps)

    candidate = None
    for i in range(window, len(frames)):
        rapid_drop = drop_speeds[i] >= 0.30
        horizontal = angles[i] >= 50 and hips[i] >= 0.62
        if rapid_drop or horizontal:
            candidate = i
            break

    drop_speed_max = max(drop_speeds) if drop_speeds else 0.0
    lying_frames = 0
    low_motion_after = 0.0
    if candidate is not None:
        lookahead = int(min(len(frames), candidate + fps * 4))
        for j in range(candidate, lookahead):
            if angles[j] >= 50 or (shoulders[j] - hips[j]) <= 0.05:
                lying_frames += 1
        after = energies[candidate:lookahead]
        low_motion_after = 1.0 - min(1.0, (sum(after) / len(after)) / 0.01) if after else 0.0

    lying_s = lying_frames / fps
    if candidate is not None:
        confidence = 0.45
        confidence += min(0.20, max(0.0, drop_speed_max - 0.20) * 0.45)
        confidence += min(0.20, lying_s * 0.07)
        if max(angles[candidate:]) >= 60:
            confidence += 0.10
        if low_motion_after > 0.5:
            confidence += 0.05
        confidence = round(min(0.98, confidence), 3)
        if confidence >= cfg.FALL_CONFIDENCE_THRESHOLD:
            occurred = started_at.timestamp() + candidate / fps
            events.append(
                DetectedEvent(
                    kind="fall",
                    event_type="FALL",
                    confidence=confidence,
                    reasoning=(
                        f"골반 높이가 {drop_speed_max:.2f}/s 속도로 급격히 낮아지고 "
                        f"몸통 기울기가 {max(angles):.0f}°까지 커진 뒤 {lying_s:.1f}초간 낮은 자세가 유지되었습니다."
                    ),
                    occurred_at=datetime.fromtimestamp(occurred, tz=timezone.utc),
                    duration_s=lying_s,
                    frame_index=candidate,
                    features={
                        "drop_speed": round(drop_speed_max, 3),
                        "torso_angle_deg": round(max(angles), 1),
                        "lying_seconds": round(lying_s, 2),
                        "low_motion_after": round(low_motion_after, 2),
                    },
                )
            )

    # --- 장시간 무활동 ---
    run_start, run_len, inactive_total = _longest_inactive_run(energies[1:], cfg.MOTION_THRESHOLD)
    run_start += 1
    inactive_seconds = run_len / fps * time_scale
    if inactive_seconds >= cfg.INACTIVITY_MINUTES * 60:
        events.append(
            DetectedEvent(
                kind="inactivity",
                event_type="INACTIVE",
                confidence=round(min(0.95, 0.6 + inactive_seconds / 3600 * 0.1), 3),
                reasoning=f"{inactive_seconds / 3600:.1f}시간 동안 관절 움직임이 기준 이하로 유지되었습니다.",
                occurred_at=datetime.fromtimestamp(started_at.timestamp() + run_start / fps, tz=timezone.utc),
                duration_s=inactive_seconds,
                frame_index=run_start,
                features={"inactive_seconds": round(inactive_seconds), "threshold": cfg.INACTIVITY_MINUTES * 60},
            )
        )

    # --- 배회 ---
    centers = [body_center(f)[0] for f in frames]
    mean_x = sum(centers) / len(centers) if centers else 0.5
    crossings, side, run = 0, 0, 0
    for x in centers:
        if abs(x - mean_x) < 0.05:
            run += 1
            continue
        new_side = 1 if x > mean_x else -1
        if side != 0 and new_side != side and run <= 6:
            crossings += 1
        side = new_side
        run = 0
    elapsed_minutes = len(frames) / fps * time_scale / 60
    if crossings >= cfg.WANDERING_MIN_CROSSINGS and elapsed_minutes >= cfg.WANDERING_MINUTES:
        events.append(
            DetectedEvent(
                kind="wandering",
                event_type="WANDERING",
                confidence=round(min(0.9, 0.5 + crossings * 0.03), 3),
                reasoning=f"{elapsed_minutes:.0f}분 동안 좌우 이동이 {crossings}회 반복되어 배회 패턴으로 판단했습니다.",
                occurred_at=datetime.fromtimestamp(started_at.timestamp(), tz=timezone.utc),
                duration_s=elapsed_minutes * 60,
                features={"crossings": crossings, "minutes": round(elapsed_minutes, 1)},
            )
        )

    steps = count_steps(frames)
    active_frames = sum(1 for e in energies[1:] if e >= cfg.MOTION_THRESHOLD)
    metrics = {
        "steps": steps,
        "walking_seconds": round(active_frames / fps, 1),
        "walking_minutes": round(active_frames / fps / 60, 1),
        "inactivity_seconds": round(inactive_seconds, 1),
        "inactivity_minutes": round(inactive_seconds / 60, 1),
        "inactive_ratio": round(inactive_total / max(1, len(energies) - 1), 3),
        "wandering_crossings": crossings,
        "wandering_minutes": round(elapsed_minutes, 1) if crossings >= cfg.WANDERING_MIN_CROSSINGS else 0.0,
        "torso_angle_max": round(max(angles), 1),
        "torso_tilt_mean": round(sum(angles) / len(angles), 1),
        "gait_stability": round(max(0.0, 1.0 - (sum(energies) / len(energies)) * 20), 2),
        "frame_count": len(frames),
        "clip_seconds": round(len(frames) / fps, 2),
        "time_scale": time_scale,
        "label": label,
    }
    return SequenceAnalysis(
        frames=frames, fps=fps, time_scale=time_scale, events=events, metrics=metrics,
        torso_angle_max=max(angles), drop_speed_max=drop_speed_max,
    )
