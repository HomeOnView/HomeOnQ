"""모델 학습·교차검증·평가·ONNX 내보내기.

    # 샘플 4종으로 뼈대 검증(증강 포함, 1분 이내)
    python -m training.train_action_model --demo --out models/action_classifier.onnx

    # 실제 데이터
    python -m training.train_action_model --dataset data/aihub \
        --out models/action_classifier.onnx --report-dir reports --augment 2 --folds 5

산출물
- `<out>`            : ONNX 모델
- `<out>.json`       : 모델 메타데이터(클래스·창 길이·특징 버전·임계값·검증 지표)
- `<report-dir>/action_model_report.{md,json}` : 혼동행렬·정밀도·재현율·오탐률

`camera-analysis/onview/inference.py` 는 이 두 파일(ONNX+JSON)만 있으면 자동으로
모델을 사용하고, 없으면 규칙 기반으로 폴백한다. 서버·웹앱 코드는 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from onview.features import FEATURE_VERSION, SEQUENCE_CHANNELS, VECTOR_FEATURES
from onview.inference import CLASSES, MODEL_FORMAT

from .augment import expand_clips
from .dataset import Clip, Dataset, build_xy, load_dataset
from .evaluate import evaluate, format_markdown
from .extract_landmarks import SAMPLE_SEGMENTS
from .numpy_model import NumpyMLP, TrainConfig, export_onnx, verify_onnx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE_DIR = ROOT / "samples"


# --------------------------------------------------------------------------- #
# 데이터 준비
# --------------------------------------------------------------------------- #
def dataset_from_samples(sample_dir: str | Path | None = None, durations: tuple[float, ...] = (6.0, 9.0, 12.0, 15.0)) -> Dataset:
    """저장소 샘플 시나리오를 여러 길이로 만들어 메모리 데이터셋으로 만든다(영상·MediaPipe 불필요).

    시나리오당 클립을 여러 개(기본 4개 길이) 만들기 때문에, 클립 단위 교차검증에서
    "학습하지 않은 클래스"를 맞히는 문제 없이 파이프라인 전체를 검증할 수 있다.
    """
    from onview.synthetic import BUILDERS

    clips: list[Clip] = []
    for scenario, builder in BUILDERS.items():
        label = "inactivity" if scenario == "inactive" else scenario
        for i, seconds in enumerate(durations):
            data = builder(seconds=seconds)
            clip_id = scenario if i == 0 else f"{scenario}-{seconds:g}s"
            clips.append(
                Clip(
                    clip_id=clip_id,
                    frames=np.asarray(data["frames"], dtype=np.float32),
                    fps=float(data["fps"]),
                    label=label,
                    segments=list(SAMPLE_SEGMENTS.get(scenario, [])),
                    source=f"synthetic:{scenario}:{seconds:g}s",
                )
            )
    if not clips:
        raise FileNotFoundError(f"샘플을 만들 수 없습니다: {sample_dir}")
    return Dataset(clips=clips, meta={"source": "samples", "path": str(sample_dir or DEFAULT_SAMPLE_DIR)})

def group_folds(groups: np.ndarray, k: int, seed: int) -> list[np.ndarray]:
    """클립 단위로 겹치지 않는 교차검증 폴드(같은 클립의 창이 train/val에 섞이지 않게)."""
    unique = np.unique(groups)
    if k <= 1 or len(unique) < 2:
        return [np.arange(len(groups))]
    k = min(k, len(unique))
    rng = np.random.default_rng(seed)
    order = rng.permutation(unique)
    chunks = np.array_split(order, k)
    folds = []
    for chunk in chunks:
        mask = np.isin(groups, chunk)
        folds.append(np.flatnonzero(mask))
    return folds


def tune_threshold(y_true_bin: np.ndarray, probs: np.ndarray, default: float = 0.6) -> tuple[float, dict[str, float]]:
    """클래스 확률 임계값을 F1 최대로 고른다(0.5~0.9, 0.5 미만으로는 내리지 않음)."""
    if y_true_bin.sum() == 0:
        return default, {"f1": 0.0, "precision": 0.0, "recall": 0.0}
    best = (default, -1.0, {})
    for thr in np.round(np.arange(0.5, 0.91, 0.05), 2):
        pred = probs >= thr
        tp = float(np.sum(pred & y_true_bin))
        fp = float(np.sum(pred & ~y_true_bin))
        fn = float(np.sum(~pred & y_true_bin))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        if f1 > best[1] + 1e-9:
            best = (float(thr), f1, {"f1": round(f1, 4), "precision": round(precision, 4), "recall": round(recall, 4)})
    return best[0], best[2]


# --------------------------------------------------------------------------- #
# 학습
# --------------------------------------------------------------------------- #
def train_and_export(
    dataset: Dataset,
    out_path: str | Path,
    report_dir: str | Path | None = None,
    window: int = 30,
    stride: int | None = None,
    input_kind: str = "vector",
    fps: float = 15.0,
    folds: int = 5,
    epochs: int = 300,
    hidden: tuple[int, ...] = (64, 32),
    lr: float = 0.01,
    augment_copies: int = 0,
    seed: int = 7,
    min_coverage: float = 0.3,
    allow_pad: bool = True,
    class_weight: bool = True,
    version: str = "v1",
    model_name: str = "HOMEONQ-ActionNet",
) -> dict[str, Any]:
    out_path = Path(out_path)
    clips = expand_clips(dataset.clips, augment_copies, seed=seed) if augment_copies else list(dataset.clips)
    work = Dataset(clips=clips, meta=dataset.meta)
    x, y, groups, ws = build_xy(
        work, window=window, stride=stride, input_kind=input_kind, fps=fps,
        allow_pad=allow_pad, min_coverage=min_coverage,
    )
    label_counts = ws.label_counts()

    cfg = TrainConfig(hidden=hidden, epochs=epochs, lr=lr, seed=seed, class_weight=class_weight)
    fold_indices = group_folds(groups, folds, seed)

    y_true: list[int] = []
    y_pred: list[int] = []
    prob_rows: list[np.ndarray] = []
    fold_reports: list[dict[str, Any]] = []
    best_epochs: list[int] = []
    for i, val_idx in enumerate(fold_indices, start=1):
        train_idx = np.setdiff1d(np.arange(len(y)), val_idx)
        if len(val_idx) == 0 or len(train_idx) == 0:
            continue
        model = NumpyMLP(x.shape[1], len(CLASSES), hidden=hidden, seed=seed + i)
        model.fit(x[train_idx], y[train_idx], config=cfg)
        probs = model.predict_proba(x[val_idx])
        preds = np.argmax(probs, axis=1)
        y_true.extend(y[val_idx].tolist())
        y_pred.extend(preds.tolist())
        prob_rows.append(probs)
        fold_reports.append(
            {
                "fold": i,
                "val_windows": int(len(val_idx)),
                "accuracy": round(float(np.mean(preds == y[val_idx])) if len(val_idx) else 0.0, 4),
            }
        )
        best_epochs.append(max(1, model.history.best_epoch))

    if not y_true:
        raise ValueError("교차검증을 수행할 창이 없습니다(클립 수·창 길이 확인).")

    cv_report = evaluate(y_true, y_pred, CLASSES)
    all_probs = np.concatenate(prob_rows, axis=0)
    y_true_arr = np.asarray(y_true, dtype=np.int64)
    thresholds: dict[str, float] = {}
    threshold_metrics: dict[str, dict[str, float]] = {}
    for cls in ("fall", "inactivity", "wandering"):
        idx = CLASSES.index(cls)
        thr, metrics = tune_threshold(y_true_arr == idx, all_probs[:, idx])
        thresholds[cls] = thr
        threshold_metrics[cls] = metrics

    # 최종 모델: 전체 데이터, 교차검증에서 고른 평균 epoch 만큼 학습
    final_epochs = int(np.clip(np.mean(best_epochs) if best_epochs else epochs, 20, epochs))
    final_cfg = TrainConfig(hidden=hidden, epochs=final_epochs, lr=lr, seed=seed, class_weight=class_weight)
    final_model = NumpyMLP(x.shape[1], len(CLASSES), hidden=hidden, seed=seed)
    final_model.fit(x, y, config=final_cfg)

    export_onnx(final_model, out_path)
    onnx_check: dict[str, Any] = {"exported": True, "path": str(out_path)}
    try:
        onnx_check.update(verify_onnx(final_model, out_path, x[: min(8, len(x))]))
    except Exception as exc:  # onnxruntime 없음 등 — 학습 산출물은 남긴다
        onnx_check.update({"verified": False, "reason": str(exc)})

    warnings: list[str] = []
    if dataset.meta.get("source") == "samples":
        warnings.append(
            "합성 시연 샘플로 만든 데모 모델입니다. 구조·연동 검증용이며 실제 성능 지표가 아닙니다."
        )
    elif len(clips) < 10:
        warnings.append(
            f"클립이 {len(clips)}개뿐입니다. 이 수치는 파이프라인 동작 검증용이며 실제 성능 지표가 아닙니다."
        )
    empty = [cls for cls, count in label_counts.items() if count == 0]
    if empty:
        warnings.append(f"학습 창이 없는 클래스: {', '.join(empty)} — 해당 클래스는 판정하지 못합니다.")

    summary = dataset.summary()
    metadata = {
        "format": MODEL_FORMAT,
        "model_name": model_name,
        "version": version,
        "backend": "numpy-mlp",
        "input_kind": input_kind,
        "window": int(window),
        "stride": int(stride or max(1, window // 2)),
        "fps": float(fps),
        "feature_version": FEATURE_VERSION,
        "classes": list(CLASSES),
        "thresholds": thresholds,
        "threshold_metrics": threshold_metrics,
        "hidden": list(hidden),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {**summary, "window_labels": label_counts, "windows": int(len(y)),
                    "augment_copies": augment_copies},
        "metrics": {
            "cv": {k: v for k, v in cv_report.items() if k != "classes"},
            "cv_per_class": cv_report["classes"],
            "folds": fold_reports,
            "onnx": onnx_check,
            "final_epochs": final_epochs,
        },
        "feature_spec": {
            "sequence_channels": list(SEQUENCE_CHANNELS),
            "vector_features": list(VECTOR_FEATURES),
        },
        "warnings": warnings,
    }
    meta_path = out_path.with_suffix(".json")
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "created_at": metadata["trained_at"],
        "model": {"path": str(out_path), "metadata": str(meta_path), "name": model_name, "version": version,
                  "input_kind": input_kind, "window": int(window), "hidden": list(hidden)},
        "dataset": metadata["dataset"],
        "cv": cv_report,
        "folds": fold_reports,
        "thresholds": thresholds,
        "threshold_metrics": threshold_metrics,
        "onnx": onnx_check,
        "warnings": warnings,
    }
    if report_dir:
        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "action_model_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (report_dir / "action_model_report.md").write_text(_report_markdown(report), encoding="utf-8")
    return report


def _report_markdown(report: dict[str, Any]) -> str:
    ds = report["dataset"]
    lines = [
        "# HOMEONQ 행동 분류 모델 리포트",
        "",
        f"- 생성: {report['created_at']}",
        f"- 모델: `{report['model']['path']}` ({report['model']['name']} {report['model']['version']}, "
        f"{report['model']['input_kind']}, 창 {report['model']['window']}프레임)",
        f"- 데이터: 클립 {ds['clips']}개 / 창 {ds['windows']}개 / 프레임 {ds['frames']} / "
        f"클래스별 클립 {ds['class_counts']}",
        "",
        "## 교차검증(클립 단위)",
        "",
        format_markdown(report["cv"]),
        "",
        "## 클래스별 확률 임계값(자동 선택)",
        "",
        "| 클래스 | 임계값 | F1 | 정밀도 | 재현율 |",
        "|---|---|---|---|---|",
    ]
    for cls, thr in report["thresholds"].items():
        m = report["threshold_metrics"].get(cls, {})
        lines.append(f"| {cls} | {thr:.2f} | {m.get('f1', 0):.3f} | {m.get('precision', 0):.3f} | {m.get('recall', 0):.3f} |")
    onnx_check = report.get("onnx", {})
    lines += [
        "",
        "## ONNX 검증",
        "",
        f"- 저장: {onnx_check.get('path')}",
        f"- onnxruntime: {onnx_check.get('onnxruntime', '—')}",
        f"- NumPy 대비 최대 오차: {onnx_check.get('max_abs_diff', '—')} "
        f"(일치: {onnx_check.get('matches_numpy', '—')})",
        "",
    ]
    if report["warnings"]:
        lines += ["## 주의", ""]
        lines += [f"- {w}" for w in report["warnings"]]
        lines.append("")
    lines += [
        "## 파이프라인 연결",
        "",
        "```bash",
        "cp <모델>.onnx camera-analysis/models/action_classifier.onnx",
        "cp <모델>.json camera-analysis/models/action_classifier.json",
        "cd camera-analysis && python -m onview.cli model-check",
        "```",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="training.train_action_model",
        description="33관절 데이터 학습 → ONNX 모델 + 평가 리포트",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--dataset", help="extract_landmarks 로 만든 데이터셋 폴더")
    src.add_argument("--demo", action="store_true", help="저장소 샘플 4종으로 즉시 학습(뼈대 검증)")
    parser.add_argument("--samples-dir", default=str(DEFAULT_SAMPLE_DIR))
    parser.add_argument("--out", default="models/action_classifier.onnx")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--window", type=int, default=30)
    parser.add_argument("--stride", type=int, default=None)
    parser.add_argument("--input-kind", default="vector", choices=["vector", "sequence"])
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--hidden", default="64,32")
    parser.add_argument("--augment", type=int, default=0, help="클립당 증강 사본 수")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--min-coverage", type=float, default=0.3)
    parser.add_argument("--no-pad", action="store_true", help="창보다 짧은 클립은 버린다")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--model-name", default="HOMEONQ-ActionNet")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.demo:
        dataset = dataset_from_samples(args.samples_dir)
        print(f"· 데모 데이터셋: 클립 {len(dataset.clips)}개 ({dataset.class_counts()})")
        if args.augment == 0:
            args.augment = 20
            print(f"· 데모 모드: 증강 사본 {args.augment}배 자동 적용")
    else:
        dataset = load_dataset(args.dataset)
        print(f"· 데이터셋: {args.dataset} — 클립 {len(dataset.clips)}개 ({dataset.class_counts()})")

    hidden = tuple(int(v) for v in str(args.hidden).split(",") if v.strip())
    report = train_and_export(
        dataset,
        out_path=args.out,
        report_dir=args.report_dir,
        window=args.window,
        stride=args.stride,
        input_kind=args.input_kind,
        fps=args.fps,
        folds=args.folds,
        epochs=args.epochs,
        hidden=hidden,
        lr=args.lr,
        augment_copies=args.augment,
        seed=args.seed,
        min_coverage=args.min_coverage,
        allow_pad=not args.no_pad,
        version=args.version,
        model_name=args.model_name,
    )
    cv = report["cv"]
    print("\n📊 교차검증(클립 단위)")
    print(f"   정확도 {cv['accuracy']:.3f} · 매크로 F1 {cv['macro_f1']:.3f} · 표본 {cv['n_samples']}창")
    for cls in CLASSES:
        m = cv["classes"][cls]
        print(f"   {cls:11s} 정밀도 {m['precision']:.3f} 재현율 {m['recall']:.3f} F1 {m['f1']:.3f} 오탐률 {m['fpr']:.3f}")
    onnx_check = report.get("onnx", {})
    print(f"\n💾 모델: {report['model']['path']}")
    print(f"   메타데이터: {report['model']['metadata']}")
    if onnx_check.get("matches_numpy") is not None:
        print(f"   ONNX 검증: NumPy 대비 최대 오차 {onnx_check.get('max_abs_diff')} "
              f"(일치 {onnx_check.get('matches_numpy')})")
    elif onnx_check.get("reason"):
        print(f"   ⚠️ ONNX 실행 검증 생략: {onnx_check['reason']}")
    if args.report_dir:
        print(f"   리포트: {Path(args.report_dir) / 'action_model_report.md'}")
    for warning in report["warnings"]:
        print(f"⚠️ {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
