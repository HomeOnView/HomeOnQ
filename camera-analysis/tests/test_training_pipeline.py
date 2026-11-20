"""전처리 → 학습 → ONNX → 추론 연결 전체 흐름 테스트.

MediaPipe·영상이 없는 환경에서도 검증되도록, 자세 추정기는 주입(fake estimator)으로 바꾸고
샘플 33관절 시퀀스와 합성 데이터를 사용한다.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

np = pytest.importorskip("numpy", reason="학습 파이프라인 테스트에는 numpy가 필요합니다")

from onview.config import load_config  # noqa: E402
from onview.detector import analyze_sequence  # noqa: E402
from onview.inference import build_classifier  # noqa: E402
from onview.skeleton_source import SCENARIO_FILES, load_sequence  # noqa: E402
from onview.synthetic import normal_walk  # noqa: E402
from training import extract_landmarks as ex  # noqa: E402
from training.augment import augment, mirror, scale_shift, time_warp, jitter  # noqa: E402
from training.dataset import Clip, load_dataset, save_clip, window_label, write_manifest  # noqa: E402
from training.evaluate import evaluate  # noqa: E402
from training.labels import (  # noqa: E402
    CLASSES, ClipSpec, Segment, collect_aihub_labels, load_label_file, load_label_map, normalize_label,
)
from training.train_action_model import dataset_from_samples, train_and_export  # noqa: E402


# --------------------------------------------------------------------------- #
# 라벨 표준화/어댑터
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("낙상", "fall"), ("낙상 발생", "fall"), ("쓰러짐", "fall"), ("Fall_Down", "fall"),
        ("장시간 무활동", "inactivity"), ("무활동", "inactivity"), ("inactivity", "inactivity"),
        ("배회", "wandering"), ("서성거림", "wandering"), ("wandering", "wandering"),
        ("정상 보행", "normal"), ("일상생활", "normal"), ("walking", "normal"),
        ("알수없는라벨", None), ("", None), (None, None),
    ],
)
def test_normalize_label(raw, expected):
    assert normalize_label(raw) == expected


def test_load_label_file_csv(tmp_path):
    labels = tmp_path / "labels.csv"
    with labels.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["video_path", "label", "start", "end"])
        writer.writerow(["clip1.mp4", "낙상", "2.0", "6.5"])
        writer.writerow(["clip2.mp4", "알수없음", "", ""])
    result = load_label_file(labels)
    assert len(result.clips) == 1
    spec = result.clips[0]
    assert spec.label == "fall"
    assert spec.clip_id == "clip1"
    # start/end 는 라벨 구간으로 해석되고, 앞 구간은 정상(배경)으로 남는다.
    assert [(s.label, s.start_s, s.end_s) for s in spec.segments] == [("normal", 0.0, 2.0), ("fall", 2.0, 6.5)]
    assert len(result.unmatched) == 1


def test_load_label_file_json_with_items(tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps({"items": [
            {"file": "a.mp4", "behavior": "배회"},
            {"file": "b.mp4", "behavior": "장시간 무활동"},
        ]}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = load_label_file(labels)
    assert [c.label for c in result.clips] == ["wandering", "inactivity"]


def test_label_map_overrides_unknown_labels(tmp_path):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps([{"path": "a.mp4", "label": "낙상의심-3단계"}]), encoding="utf-8")
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"낙상의심-3단계": "fall"}, ensure_ascii=False), encoding="utf-8")
    result = load_label_file(labels, load_label_map(mapping))
    assert result.clips[0].label == "fall"


def test_label_map_rejects_invalid_class(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"x": "sitting"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_label_map(mapping)


def test_aihub_folder_adapter(tmp_path):
    """AI 허브식 폴더: 라벨 JSON 여러 형태 + 원천데이터 영상 폴더."""
    label_root = tmp_path / "라벨링데이터" / "TL_낙상"
    label_root.mkdir(parents=True)
    video_root = tmp_path / "원천데이터" / "TS_낙상"
    video_root.mkdir(parents=True)
    (video_root / "clipA.mp4").write_bytes(b"fake")
    (video_root / "clipB.mp4").write_bytes(b"fake")

    (label_root / "clipA.json").write_text(
        json.dumps({"metadata": {"video_name": "clipA.mp4"},
                    "annotations": [{"label": "낙상", "start": 1.0, "end": 4.0}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (label_root / "clipB.json").write_text(
        json.dumps({"clip": {"source_file": "clipB.mp4", "behavior_name": "서성거림"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (label_root / "unknown.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")

    result = collect_aihub_labels(tmp_path / "라벨링데이터", video_root=tmp_path / "원천데이터")
    labels = sorted(c.label for c in result.clips)
    assert labels == ["fall", "wandering"]
    assert all(Path(c.video_path).exists() for c in result.clips)
    assert len(result.unmatched) == 1


# --------------------------------------------------------------------------- #
# 영상 → 관절 추출
# --------------------------------------------------------------------------- #
class FakeEstimator:
    """프레임 번호에 따라 합성 자세를 돌려주는 가짜 MediaPipe."""

    def __init__(self, drop: set[int] | None = None, scale: int = 2):
        self.drop = drop or set()
        self.scale = scale
        self.frames = normal_walk(seconds=3.0)["frames"]

    def estimate(self, image):
        idx = image[0] if isinstance(image, (list, tuple)) else int(image)
        if idx in self.drop:
            return None
        pose = self.frames[idx % len(self.frames)]
        return [[p[0], p[1], p[2], p[3]] for p in pose]


def test_extract_poses_interpolates_missing_frames(monkeypatch):
    fake_frames = [[i] for i in range(10)]  # sample_video_frames 결과(식별자 역할)
    monkeypatch.setattr(ex, "sample_video_frames", lambda *a, **k: (fake_frames, {"effective_fps": 15.0}))
    estimator = FakeEstimator(drop={4, 5})
    arr, stats = ex.extract_poses_from_video("dummy.mp4", estimator)
    assert arr.shape == (10, 33, 4)
    assert np.isfinite(arr).all()
    assert stats["pose_coverage"] == pytest.approx(0.8)
    # 보간된 프레임이 이웃 값 사이에 있어야 한다
    assert np.all(arr[4] >= np.minimum(arr[3], arr[6]) - 1e-6)


def test_build_from_specs_skips_low_coverage(tmp_path, monkeypatch):
    fake_frames = [[i] for i in range(12)]
    monkeypatch.setattr(ex, "sample_video_frames", lambda *a, **k: (fake_frames, {"effective_fps": 15.0}))
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    specs = [ClipSpec(label="normal", video_path=str(video), clip_id="good")]
    stats = ex.build_from_specs(specs, tmp_path / "out", estimator=FakeEstimator(), min_coverage=0.5)
    assert len(stats.entries) == 1
    assert (tmp_path / "out" / "good.npz").exists()

    estimator = FakeEstimator(drop=set(range(12)))  # 전부 실패
    stats2 = ex.build_from_specs(specs, tmp_path / "out2", estimator=estimator)
    assert stats2.entries == []
    assert "관절 검출" in stats2.skipped[0]["reason"]


def test_samples_cli_creates_manifest(tmp_path):
    assert ex.main(["--samples", "--out", str(tmp_path)]) == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["format"] == "HOMEONQ-joint-dataset/1"
    assert len(manifest["clips"]) == 4
    dataset = load_dataset(tmp_path)
    assert sorted(c.label for c in dataset.clips) == ["fall", "inactivity", "normal", "wandering"]
    assert dataset.class_counts()["fall"] == 1
    # 낙상 클립은 '낙상 전 구간'이 normal 세그먼트로 남아 있어야 한다
    fall_clip = next(c for c in dataset.clips if c.label == "fall")
    assert [s.label for s in fall_clip.segments] == ["normal", "fall"]


def test_cli_dry_run_does_not_extract(tmp_path, capsys):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps([{"path": "a.mp4", "label": "낙상"}]), encoding="utf-8")
    code = ex.main(["--labels", str(labels), "--out", str(tmp_path / "out"), "--dry-run"])
    assert code == 0
    assert not (tmp_path / "out" / "manifest.json").exists()
    assert "dry-run" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# 데이터셋/창/증강
# --------------------------------------------------------------------------- #
def test_window_label_uses_segment_overlap():
    clip = Clip(
        clip_id="c", frames=np.zeros((90, 33, 4), dtype=np.float32), fps=15.0, label="fall",
        segments=[Segment(0.0, 1.0, "normal"), Segment(1.0, 6.0, "fall")],
    )
    assert window_label(clip, 0, 15) == "normal"       # 0~1초
    assert window_label(clip, 30, 45) == "fall"        # 2~3초
    plain = Clip(clip_id="p", frames=np.zeros((30, 33, 4), dtype=np.float32), fps=15.0, label="inactivity")
    assert window_label(plain, 0, 15) == "inactivity"  # 구간 정보 없으면 클립 라벨


def test_save_and_load_clip_roundtrip(tmp_path):
    frames = np.asarray(normal_walk(seconds=2.0)["frames"], dtype=np.float32)
    entry = save_clip(tmp_path, "clip-1", frames, fps=15.0, label="normal", segments=[Segment(0, 2, "normal")])
    write_manifest(tmp_path, [entry])
    dataset = load_dataset(tmp_path)
    assert len(dataset.clips) == 1
    clip = dataset.clips[0]
    assert clip.clip_id == "clip-1"
    assert np.allclose(clip.frames, frames)
    assert clip.segments[0].label == "normal"


def test_augmentations_preserve_shape_and_pipeline_invariance():
    frames = np.asarray(normal_walk(seconds=3.0)["frames"], dtype=np.float32)
    rng = np.random.default_rng(0)
    variants = [
        jitter(frames, rng),
        mirror(frames),
        time_warp(frames, rng),
        scale_shift(frames, rng),
        augment(frames, rng),
    ]
    for out in variants:
        assert out.ndim == 3 and out.shape[1:] == (33, 4)
        assert np.isfinite(out).all()
    assert np.allclose(mirror(frames)[:, 11, 0], 1.0 - frames[:, 12, 0], atol=1e-6)  # 좌우 어깨 교환
    assert time_warp(frames, rng).shape[0] > 0


# --------------------------------------------------------------------------- #
# 평가 지표
# --------------------------------------------------------------------------- #
def test_evaluate_metrics_and_fpr():
    y_true = [0, 0, 0, 0, 1, 1]
    y_pred = [0, 0, 1, 0, 1, 0]  # 정상 1건을 낙상으로 오탐, 낙상 1건을 놓침
    report = evaluate(y_true, y_pred, CLASSES)
    assert report["accuracy"] == pytest.approx(4 / 6, abs=1e-4)
    fall = report["classes"]["fall"]
    assert fall["recall"] == pytest.approx(0.5)
    assert fall["precision"] == pytest.approx(0.5)
    assert fall["fpr"] == pytest.approx(0.25)  # 오탐 1 / (오탐 1 + 정상을 정상이라 한 3건)
    assert report["confusion_matrix"][1][1] == 1


def test_perfect_predictions():
    y = [0, 1, 2, 3]
    report = evaluate(y, y, CLASSES)
    assert report["accuracy"] == 1.0
    assert report["macro_f1"] == 1.0
    assert all(report["classes"][c]["fpr"] == 0.0 for c in CLASSES)


# --------------------------------------------------------------------------- #
# 학습 → ONNX → 추론 (핵심 통합 테스트)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def trained_model(tmp_path_factory):
    pytest.importorskip("onnx", reason="ONNX 내보내기에는 onnx 패키지가 필요합니다")
    out = tmp_path_factory.mktemp("model") / "action_classifier.onnx"
    report = train_and_export(
        dataset_from_samples(),
        out_path=out,
        report_dir=out.parent,
        window=30,
        folds=4,
        epochs=120,
        augment_copies=3,
        seed=3,
    )
    return out, report


def test_training_writes_onnx_metadata_and_report(trained_model):
    out, report = trained_model
    assert out.exists() and out.stat().st_size > 1000
    meta_path = out.with_suffix(".json")
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["format"] == "HOMEONQ-action-model/1"
    assert meta["input_kind"] == "vector"
    assert meta["classes"] == list(CLASSES)
    assert meta["dataset"]["clips"] == 16
    assert set(meta["thresholds"]) == {"fall", "inactivity", "wandering"}
    assert report["cv"]["accuracy"] > 0.5
    assert (out.parent / "action_model_report.md").exists()
    assert "혼동행렬" in (out.parent / "action_model_report.md").read_text(encoding="utf-8")


def test_trained_model_predicts_each_sample(trained_model):
    out, _ = trained_model
    classifier, reason = build_classifier(load_config(ACTION_MODEL_PATH=str(out)))
    assert classifier is not None, reason
    expected = {"normal": "normal", "fall": "fall", "inactive": "inactivity", "wandering": "wandering"}
    for scenario, want in expected.items():
        seq = load_sequence(ROOT / "samples" / SCENARIO_FILES[scenario])
        assessment = classifier.analyze(seq.frames, fps=seq.fps, time_scale=seq.time_scale)
        probs = assessment.metrics["probabilities"]
        assert sum(probs.values()) == pytest.approx(1.0, abs=1e-3)
        assert assessment.metrics["top_class"] == want, (scenario, probs)


def test_pipeline_uses_model_and_still_reports_events(trained_model):
    out, _ = trained_model
    cfg = load_config(ACTION_MODEL_PATH=str(out), DB_PATH=":memory:")
    classifier, reason = build_classifier(cfg)
    assert classifier is not None, reason
    seq = load_sequence(ROOT / "samples" / SCENARIO_FILES["fall"])
    analysis = analyze_sequence(seq.frames, fps=seq.fps, time_scale=seq.time_scale,
                                config=cfg, classifier=classifier)
    assert analysis.metrics["detector"] == "rule+onnx"
    assert any(e.kind == "fall" for e in analysis.events)
    assert analysis.metrics["ai_model"]["source"] == "onnx"
    probs = analysis.metrics["ai_model"]["probabilities"]
    assert probs["fall"] == max(probs.values())
    # 규칙 이벤트에 모델 확률이 교차 확인으로 붙는다
    fall_event_obj = next(e for e in analysis.events if e.kind == "fall")
    assert "model_probability" in fall_event_obj.features


def test_model_metadata_contains_feature_spec(trained_model):
    out, _ = trained_model
    meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["feature_spec"]["vector_features"]
    assert meta["metrics"]["onnx"].get("matches_numpy") is True
    assert meta["warnings"]  # 합성 데모 데이터 경고가 남는다
