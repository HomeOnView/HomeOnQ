import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview.detector import analyze_sequence, count_steps, motion_energy, torso_angle_deg  # noqa: E402
from onview.skeleton_source import SCENARIO_FILES, load_sequence  # noqa: E402
from onview.synthetic import build_sample, fall_event, long_inactive, normal_walk, wandering  # noqa: E402


def test_samples_exist_and_are_valid():
    for name in SCENARIO_FILES.values():
        seq = load_sequence(ROOT / "samples" / name)
        assert len(seq.frames) > 20
        assert len(seq.frames[0]) == 33
        assert seq.fps > 0


def test_normal_walk_has_no_fall_and_counts_steps():
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["normal"])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
    assert [e for e in analysis.events if e.kind == "fall"] == []
    assert analysis.metrics["steps"] > 10
    assert analysis.metrics["torso_angle_max"] < 30


def test_fall_sample_is_detected_with_confidence():
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["fall"])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
    falls = [e for e in analysis.events if e.kind == "fall"]
    assert len(falls) == 1
    event = falls[0]
    assert event.confidence >= 0.55
    assert event.features["torso_angle_deg"] >= 55
    assert event.features["lying_seconds"] >= 1.0
    assert "낮은 자세" in event.reasoning


def test_inactivity_sample_reports_hours():
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["inactive"])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
    events = [e for e in analysis.events if e.kind == "inactivity"]
    assert len(events) == 1
    assert events[0].duration_s / 3600 >= 4.0


def test_wandering_sample_counts_crossings():
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["wandering"])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
    events = [e for e in analysis.events if e.kind == "wandering"]
    assert len(events) == 1
    assert events[0].features["crossings"] >= 6
    assert analysis.metrics["wandering_minutes"] >= 10


def test_empty_and_short_sequences_are_safe():
    assert analyze_sequence([], fps=15).events == []
    short = normal_walk(seconds=0.2)["frames"]
    assert analyze_sequence(short, fps=15).metrics["frame_count"] == 3


def test_torso_angle_and_motion_helpers():
    upright = normal_walk(seconds=0.2)["frames"][0]
    lying = fall_event(seconds=6)["frames"][-1]
    assert torso_angle_deg(upright) < 20
    assert torso_angle_deg(lying) > 60
    assert motion_energy(upright, lying) > 0.1
    assert count_steps(normal_walk(seconds=3)["frames"]) > 0


def test_lying_pose_does_not_count_as_activity():
    frames = long_inactive()["frames"]
    analysis = analyze_sequence(frames, fps=5, time_scale=1800)
    assert analysis.metrics["steps"] == 0
