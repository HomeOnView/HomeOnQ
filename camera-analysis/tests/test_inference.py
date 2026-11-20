"""ONNX 추론기 연결·폴백 테스트.

모델 파일이 없는 기본 상태(저장소 기본값)에서는 규칙 기반 결과가 **완전히 그대로** 나와야 하고,
모델이 있으면 규칙 결과에 AI 판정이 더해져야 한다. 모델이 깨져 있어도 파이프라인은 멈추지 않는다.
"""
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onview.config import load_config  # noqa: E402
from onview.detector import analyze_sequence  # noqa: E402
from onview.inference import ModelAssessment, build_classifier, model_status  # noqa: E402
from onview.schemas import DetectedEvent  # noqa: E402
from onview.skeleton_source import SCENARIO_FILES, load_sequence  # noqa: E402


def _seq(scenario: str = "fall"):
    return load_sequence(ROOT / "samples" / SCENARIO_FILES[scenario])


def _event(kind: str = "wandering", confidence: float = 0.91) -> DetectedEvent:
    return DetectedEvent(
        kind=kind,
        event_type=kind.upper(),
        confidence=confidence,
        reasoning="테스트용 모델 판정",
        occurred_at=datetime.now(timezone.utc),
        duration_s=12.0,
        frame_index=30,
        features={"source": "onnx", "model": "stub", "probability": confidence},
    )


@dataclass
class StubClassifier:
    """onnxruntime 없이 병합 로직을 검증하기 위한 가짜 분류기."""

    events: list
    available: bool = True
    raises: bool = False
    payload: object | None = None

    def analyze(self, frames, fps=15.0, time_scale=1.0, started_at=None, config=None):
        if self.raises:
            raise RuntimeError("가짜 추론 실패")
        if self.payload is not None:
            return self.payload
        return ModelAssessment(
            events=list(self.events),
            metrics={
                "source": "onnx", "model_name": "stub", "model_version": "t0",
                "probabilities": {"normal": 0.1, "fall": 0.2, "inactivity": 0.3, "wandering": 0.4},
                "top_class": "wandering", "window_count": 2,
            },
            windows=[],
        )


# --------------------------------------------------------------------------- #
# 모델 없음/설정
# --------------------------------------------------------------------------- #
def test_missing_model_falls_back_to_rules():
    cfg = load_config(ACTION_MODEL_PATH=str(ROOT / "models" / "does-not-exist.onnx"))
    classifier, reason = build_classifier(cfg)
    assert classifier is None
    assert "모델 파일 없음" in reason
    status = model_status(cfg)
    assert status["available"] is False
    assert "configured_path" in status


def test_use_action_model_off_disables_model():
    cfg = load_config(USE_ACTION_MODEL="off")
    classifier, reason = build_classifier(cfg)
    assert classifier is None
    assert "off" in reason


def test_missing_metadata_is_reported(tmp_path):
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(b"not-a-real-model")
    classifier, reason = build_classifier(load_config(ACTION_MODEL_PATH=str(onnx_path)))
    assert classifier is None
    assert "메타데이터" in reason


def test_feature_version_mismatch_is_rejected(tmp_path):
    pytest.importorskip("numpy")
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(b"x")
    onnx_path.with_suffix(".json").write_text(
        json.dumps({
            "format": "HOMEONQ-action-model/1",
            "classes": ["normal", "fall", "inactivity", "wandering"],
            "input_kind": "vector",
            "window": 30,
            "feature_version": "OLD-FEATURE-v0",
        }),
        encoding="utf-8",
    )
    classifier, reason = build_classifier(load_config(ACTION_MODEL_PATH=str(onnx_path)))
    assert classifier is None
    assert "특징 버전" in reason


# --------------------------------------------------------------------------- #
# 병합/폴백
# --------------------------------------------------------------------------- #
def test_rule_based_result_unchanged_without_classifier():
    seq = _seq("fall")
    plain = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
    assert plain.metrics["detector"] == "rule"
    assert "ai_model" not in plain.metrics
    assert [e.kind for e in plain.events] == ["fall"]


def test_model_only_event_is_added_to_rule_events():
    seq = _seq("fall")
    stub = StubClassifier(events=[_event("wandering", 0.88)])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale, classifier=stub)
    kinds = [e.kind for e in analysis.events]
    assert "fall" in kinds  # 규칙이 잡은 낙상은 유지
    assert "wandering" in kinds  # 모델이 추가로 잡은 배회
    assert analysis.metrics["detector"] == "rule+onnx"
    assert analysis.metrics["ai_model"]["model_only_events"] == 1
    assert analysis.metrics["ai_model"]["top_class"] == "wandering"


def test_model_event_for_existing_kind_is_merged_not_duplicated():
    seq = _seq("fall")
    stub = StubClassifier(events=[_event("fall", 0.93)])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale, classifier=stub)
    falls = [e for e in analysis.events if e.kind == "fall"]
    assert len(falls) == 1
    assert falls[0].features["model_probability"] == 0.93
    assert analysis.metrics["ai_model"]["model_only_events"] == 0


def test_model_failure_keeps_rule_result():
    seq = _seq("wandering")
    plain = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
    broken = StubClassifier(events=[], raises=True)
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale, classifier=broken)
    assert [e.kind for e in analysis.events] == [e.kind for e in plain.events]
    assert analysis.metrics["detector"] == "rule"
    assert "추론 실패" in analysis.metrics["ai_model"]["fallback_reason"]


def test_unexpected_model_output_is_rejected_safely():
    seq = _seq("normal")
    weird = StubClassifier(events=[], payload={"not": "an assessment"})
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale, classifier=weird)
    assert analysis.events == []
    assert analysis.metrics["detector"] == "rule"
    assert "형식" in analysis.metrics["ai_model"]["fallback_reason"]


def test_unavailable_classifier_is_ignored():
    seq = _seq("normal")
    offline = StubClassifier(events=[_event("fall", 0.99)], available=False)
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale, classifier=offline)
    assert analysis.events == []
    assert analysis.metrics["detector"] == "rule"


def test_empty_frames_with_classifier_is_safe():
    stub = StubClassifier(events=[_event("fall", 0.99)])
    analysis = analyze_sequence([], fps=15.0, classifier=stub)
    assert analysis.events == []
    assert analysis.metrics == {}
