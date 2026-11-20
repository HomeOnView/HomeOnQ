"""33관절 특징 추출 테스트 — 정규화 불변성·결측 처리·창 생성."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

np = pytest.importorskip("numpy", reason="특징 추출에는 numpy가 필요합니다")

from onview.features import (  # noqa: E402
    SEQUENCE_CHANNELS, VECTOR_FEATURES, frames_to_array, iter_windows, pad_window,
    sequence_features, window_sequence, window_vector,
)
from onview.synthetic import fall_event, long_inactive, normal_walk, wandering  # noqa: E402


def _frames(seconds: float = 6.0) -> np.ndarray:
    return np.asarray(normal_walk(seconds=seconds)["frames"], dtype=np.float32)


def test_sequence_features_shape_and_finite():
    feats = sequence_features(_frames(), fps=15.0)
    assert feats.shape == (len(_frames()), len(SEQUENCE_CHANNELS))
    assert np.isfinite(feats).all()


def test_features_are_invariant_to_position_and_distance():
    """같은 동작을 화면 다른 위치·다른 크기로 찍어도 몸 형태 특징은 같아야 한다."""
    frames = _frames()
    scaled = frames.copy()
    # 중심(0.5, 0.6) 기준 0.8배 축소 + 오른쪽 아래로 이동
    scaled[:, :, 0] = (scaled[:, :, 0] - 0.5) * 0.8 + 0.5 + 0.12
    scaled[:, :, 1] = (scaled[:, :, 1] - 0.6) * 0.8 + 0.6 + 0.05

    base = sequence_features(frames, fps=15.0)
    moved = sequence_features(scaled, fps=15.0)
    # center_x 는 화면 위치를 일부러 남긴 채널이라 제외한다(배회 판단에 필요).
    keep = [i for i, name in enumerate(SEQUENCE_CHANNELS) if name != "center_x"]
    diff = float(np.abs(base[:, keep] - moved[:, keep]).max())
    # 샘플 좌표가 소수 4자리로 양자화되어 있어 속도 채널에는 작은 잡음이 남는다(≈1e-2).
    assert diff < 2e-2, f"위치/크기 변화에 특징이 흔들립니다: {diff}"


def test_lying_pose_has_low_hip_height_and_high_lean():
    upright = sequence_features(_frames(), fps=15.0)[0]
    lying = sequence_features(np.asarray(fall_event(seconds=8)["frames"], dtype=np.float32)[-1:], fps=15.0)[0]
    idx = {name: i for i, name in enumerate(SEQUENCE_CHANNELS)}
    assert upright[idx["hip_height"]] > lying[idx["hip_height"]] + 1.0
    assert lying[idx["torso_lean"]] > 0.5 > upright[idx["torso_lean"]]


def test_inactivity_has_lower_motion_than_walking():
    idx = {name: i for i, name in enumerate(SEQUENCE_CHANNELS)}
    walk = sequence_features(_frames(), fps=15.0)[:, idx["motion"]]
    still = sequence_features(np.asarray(long_inactive()["frames"], dtype=np.float32), fps=5.0)[:, idx["motion"]]
    assert walk.mean() > 3 * still.mean()


def test_missing_and_short_sequences_are_safe():
    empty = frames_to_array([])
    assert empty.shape == (0, 33, 4)
    assert sequence_features(empty).shape == (0, len(SEQUENCE_CHANNELS))
    assert window_vector(empty).shape == (len(VECTOR_FEATURES),)
    one = np.zeros((1, 33, 4), dtype=np.float32)  # 모든 좌표 0 → 몸통 길이 0
    feats = sequence_features(one, fps=15.0)
    assert np.isfinite(feats).all()
    short = sequence_features(_frames(0.2), fps=15.0)
    assert short.shape[0] == 3


def test_window_vector_and_sequence_lengths():
    frames = _frames()
    vec = window_vector(frames, fps=15.0)
    assert vec.shape == (len(VECTOR_FEATURES),)
    assert len(VECTOR_FEATURES) == len(SEQUENCE_CHANNELS) * 5 + 7
    seq = window_sequence(frames, fps=15.0)
    assert seq.shape == (len(frames), len(SEQUENCE_CHANNELS))
    padded = pad_window(np.zeros((10, 33, 4), dtype=np.float32), 30)
    assert padded.shape == (30, 33, 4)


def test_wandering_windows_have_lateral_movement():
    idx = {name: i for i, name in enumerate(SEQUENCE_CHANNELS)}
    frames = np.asarray(wandering(seconds=20)["frames"], dtype=np.float32)
    feats = sequence_features(frames, fps=10.0)
    assert feats[:, idx["center_x"]].max() - feats[:, idx["center_x"]].min() > 0.25
    v = window_vector(frames, fps=10.0)
    assert v[len(SEQUENCE_CHANNELS) * 5 + 1] > 0.2  # x_range


def test_iter_windows_covers_end_and_respects_length():
    spans = iter_windows(100, 30, 15)
    assert spans[0] == (0, 30)
    assert spans[-1][1] == 100
    assert all(0 <= s < e <= 100 and e - s == 30 for s, e in spans)
    assert iter_windows(20, 30) == [(0, 20)]
    assert iter_windows(0, 30) == []
