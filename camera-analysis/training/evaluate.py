"""평가 지표: 혼동행렬 · 정밀도/재현율/F1 · 오탐률(FPR).

낙상 감지에서 중요한 두 숫자를 함께 본다.
- **재현율(recall)**: 실제 낙상을 놓치지 않았는가
- **오탐률(FPR)**: 정상 상황을 낙상으로 잘못 알렸는가
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def confusion_matrix(y_true: Sequence[int], y_pred: Sequence[int], n_classes: int) -> np.ndarray:
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        if 0 <= int(t) < n_classes and 0 <= int(p) < n_classes:
            cm[int(t), int(p)] += 1
    return cm


def per_class_metrics(cm: np.ndarray) -> dict[str, dict[str, float]]:
    """클래스별 precision/recall/f1/support/fpr."""
    out: dict[str, dict[str, float]] = {}
    total = int(cm.sum())
    for i in range(cm.shape[0]):
        tp = int(cm[i, i])
        fn = int(cm[i, :].sum() - tp)
        fp = int(cm[:, i].sum() - tp)
        tn = total - tp - fn - fp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        out[str(i)] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "fpr": round(fpr, 4),
            "support": float(cm[i, :].sum()),
            "tp": float(tp),
            "fp": float(fp),
            "fn": float(fn),
        }
    return out


def evaluate(y_true: Sequence[int], y_pred: Sequence[int], classes: Sequence[str]) -> dict[str, Any]:
    cm = confusion_matrix(y_true, y_pred, len(classes))
    per_class = per_class_metrics(cm)
    named = {cls: per_class.setdefault(str(i), {}) for i, cls in enumerate(classes)}
    supports = [per_class[str(i)]["support"] for i in range(len(classes))]
    weighted_f1 = (
        sum(per_class[str(i)]["f1"] * supports[i] for i in range(len(classes))) / sum(supports)
        if sum(supports)
        else 0.0
    )
    accuracy = float(np.trace(cm) / cm.sum()) if cm.sum() else 0.0
    present = [per_class[str(i)]["f1"] for i in range(len(classes)) if supports[i] > 0]
    return {
        "accuracy": round(accuracy, 4),
        "macro_f1": round(float(np.mean(present)) if present else 0.0, 4),
        "weighted_f1": round(weighted_f1, 4),
        "classes": named,
        "confusion_matrix": cm.tolist(),
        "class_order": list(classes),
        "n_samples": int(cm.sum()),
    }


def format_markdown(report: dict[str, Any]) -> str:
    classes = report.get("class_order", [])
    cm = np.asarray(report.get("confusion_matrix", []))
    lines = [
        f"- 정확도 **{report.get('accuracy', 0):.3f}** · 매크로 F1 **{report.get('macro_f1', 0):.3f}**"
        f" · 가중 F1 **{report.get('weighted_f1', 0):.3f}** · 표본 {report.get('n_samples', 0)}개",
        "",
        "| 클래스 | 정밀도 | 재현율 | F1 | 오탐률(FPR) | 표본 |",
        "|---|---|---|---|---|---|",
    ]
    for cls in classes:
        m = report.get("classes", {}).get(cls, {})
        lines.append(
            f"| {cls} | {m.get('precision', 0):.3f} | {m.get('recall', 0):.3f} | "
            f"{m.get('f1', 0):.3f} | {m.get('fpr', 0):.3f} | {int(m.get('support', 0))} |"
        )
    if cm.size:
        lines += ["", "혼동행렬(행=실제, 열=예측)", ""]
        header = "| 실제 \\ 예측 | " + " | ".join(classes) + " |"
        lines.append(header)
        lines.append("|" + "---|" * (len(classes) + 1))
        for i, cls in enumerate(classes):
            row = " | ".join(str(int(v)) for v in cm[i])
            lines.append(f"| {cls} | {row} |")
    return "\n".join(lines)


def macro_summary(report: dict[str, Any]) -> dict[str, float]:
    return {
        "accuracy": report.get("accuracy", 0.0),
        "macro_f1": report.get("macro_f1", 0.0),
        "weighted_f1": report.get("weighted_f1", 0.0),
    }
