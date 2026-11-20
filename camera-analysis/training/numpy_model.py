"""경량 MLP(순수 NumPy) 학습 + ONNX 내보내기.

무거운 프레임워크(PyTorch/TensorFlow) 없이도 학습·평가·ONNX 저장이 모두 동작하도록
NumPy로 직접 구현했다. 모델은 표준화(Sub/Div) → Linear → ReLU → Linear → ReLU →
Linear → Softmax 의 작은 MLP이며, 표준화까지 ONNX 그래프에 넣어 두어 추론기가
따로 평균·표준편차를 들고 있을 필요가 없다.

- 학습: Adam, 클래스 가중 교차엔트로피(데이터 불균형 대응), L2, 조기 종료
- 재현성: 시드 고정
- 입력: `(batch, feature_dim)` float32, 출력: `(batch, n_classes)` 확률

시계열 CNN 같은 더 큰 모델로 바꾸고 싶으면 `train_action_model.py`의 `BACKENDS`에
새 백엔드를 추가하면 된다(추론기는 `input_kind`와 메타데이터만 보고 동작하므로 서버·앱은
그대로 둔다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class TrainConfig:
    hidden: tuple[int, ...] = (64, 32)
    epochs: int = 300
    lr: float = 0.01
    batch_size: int = 64
    l2: float = 1e-4
    patience: int = 40
    seed: int = 7
    class_weight: bool = True
    verbose: bool = False


@dataclass
class History:
    train_loss: list[float] = field(default_factory=list)
    val_loss: list[float] = field(default_factory=list)
    best_epoch: int = 0
    stopped_early: bool = False


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)


def class_weights(y: np.ndarray, n_classes: int) -> np.ndarray:
    """균형 가중치(빈도 역수 정규화). 없는 클래스는 1.0."""
    counts = np.bincount(y, minlength=n_classes).astype(np.float64)
    weights = np.ones(n_classes, dtype=np.float64)
    present = counts > 0
    if present.any():
        weights[present] = counts.sum() / (present.sum() * counts[present])
    return weights


class NumpyMLP:
    """표준화 + 은닉층 MLP + Softmax."""

    def __init__(self, n_in: int, n_classes: int, hidden: tuple[int, ...] = (64, 32), seed: int = 7):
        self.n_in = int(n_in)
        self.n_classes = int(n_classes)
        self.hidden = tuple(hidden) or (64,)
        rng = np.random.default_rng(seed)
        dims = [self.n_in, *self.hidden, self.n_classes]
        self.weights: list[np.ndarray] = []
        self.biases: list[np.ndarray] = []
        for i in range(len(dims) - 1):
            limit = np.sqrt(6.0 / max(1, dims[i] + dims[i + 1]))
            self.weights.append(rng.uniform(-limit, limit, size=(dims[i], dims[i + 1])).astype(np.float64))
            self.biases.append(np.zeros(dims[i + 1], dtype=np.float64))
        self.mean = np.zeros(self.n_in, dtype=np.float64)
        self.std = np.ones(self.n_in, dtype=np.float64)
        self.history = History()

    # --- 전처리 ---
    def _standardize(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.std

    def _forward(self, x: np.ndarray) -> tuple[list[np.ndarray], np.ndarray]:
        activations = [x]
        h = x
        for i, (w, b) in enumerate(zip(self.weights, self.biases)):
            z = h @ w + b
            h = np.maximum(z, 0.0) if i < len(self.weights) - 1 else z
            activations.append(h)
        return activations, _softmax(h)

    # --- 학습 ---
    def fit(
        self,
        x: np.ndarray,
        y: np.ndarray,
        x_val: np.ndarray | None = None,
        y_val: np.ndarray | None = None,
        config: TrainConfig | None = None,
    ) -> History:
        cfg = config or TrainConfig()
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.int64)
        self.mean = x.mean(axis=0)
        self.std = np.where(x.std(axis=0) < 1e-6, 1.0, x.std(axis=0))
        x = self._standardize(x)
        if x_val is not None:
            x_val = self._standardize(np.asarray(x_val, dtype=np.float64))

        weights = class_weights(y, self.n_classes) if cfg.class_weight else np.ones(self.n_classes)
        n = x.shape[0]
        rng = np.random.default_rng(cfg.seed)
        params = self.weights + self.biases
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        beta1, beta2, eps = 0.9, 0.999, 1e-8
        best_loss, best_params, best_epoch, stale = np.inf, None, 0, 0
        step = 0

        for epoch in range(1, max(1, cfg.epochs) + 1):
            order = rng.permutation(n)
            epoch_loss = 0.0
            for begin in range(0, n, max(1, cfg.batch_size)):
                idx = order[begin:begin + max(1, cfg.batch_size)]
                xb, yb = x[idx], y[idx]
                activations, probs = self._forward(xb)
                sample_w = weights[yb]
                loss = -np.mean(sample_w * np.log(np.maximum(probs[np.arange(len(yb)), yb], 1e-12)))
                epoch_loss += float(loss) * len(idx)

                # backward
                grad = probs.copy()
                grad[np.arange(len(yb)), yb] -= 1.0
                grad *= (sample_w / len(yb))[:, None]
                grads_w: list[np.ndarray] = [np.zeros(0)] * len(self.weights)
                grads_b: list[np.ndarray] = [np.zeros(0)] * len(self.biases)
                for i in range(len(self.weights) - 1, -1, -1):
                    grads_w[i] = activations[i].T @ grad + cfg.l2 * self.weights[i]
                    grads_b[i] = grad.sum(axis=0)
                    if i > 0:
                        grad = grad @ self.weights[i].T
                        grad = grad * (activations[i] > 0)
                step += 1
                grads = grads_w + grads_b
                for k, g in enumerate(grads):
                    m[k] = beta1 * m[k] + (1 - beta1) * g
                    v[k] = beta2 * v[k] + (1 - beta2) * (g * g)
                    mh = m[k] / (1 - beta1 ** step)
                    vh = v[k] / (1 - beta2 ** step)
                    params[k] -= cfg.lr * mh / (np.sqrt(vh) + eps)

            train_loss = epoch_loss / max(1, n)
            self.history.train_loss.append(train_loss)
            if x_val is not None and y_val is not None:
                _, val_probs = self._forward(x_val)
                val_loss = float(
                    -np.mean(np.log(np.maximum(val_probs[np.arange(len(y_val)), y_val], 1e-12)))
                )
            else:
                val_loss = train_loss
            self.history.val_loss.append(val_loss)
            if val_loss < best_loss - 1e-5:
                best_loss, best_epoch, stale = val_loss, epoch, 0
                best_params = ([w.copy() for w in self.weights], [b.copy() for b in self.biases])
            else:
                stale += 1
                if stale >= cfg.patience:
                    self.history.stopped_early = True
                    break
            if cfg.verbose and epoch % 25 == 0:
                print(f"    epoch {epoch:3d}  train_loss={train_loss:.4f}  val_loss={val_loss:.4f}")

        if best_params is not None:
            self.weights, self.biases = best_params
        self.history.best_epoch = best_epoch
        return self.history

    # --- 추론 ---
    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        _, probs = self._forward(self._standardize(x))
        return probs.astype(np.float32)

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.argmax(self.predict_proba(x), axis=1)

    # --- 저장 ---
    def state_dict(self) -> dict[str, Any]:
        return {
            "n_in": self.n_in,
            "n_classes": self.n_classes,
            "hidden": list(self.hidden),
            "weights": [w.tolist() for w in self.weights],
            "biases": [b.tolist() for b in self.biases],
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "history": {
                "best_epoch": self.history.best_epoch,
                "stopped_early": self.history.stopped_early,
                "final_train_loss": self.history.train_loss[-1] if self.history.train_loss else None,
                "final_val_loss": self.history.val_loss[-1] if self.history.val_loss else None,
            },
        }


# --------------------------------------------------------------------------- #
# ONNX 내보내기
# --------------------------------------------------------------------------- #
def export_onnx(model: NumpyMLP, path: str | Path, opset: int = 13) -> Path:
    """MLP를 ONNX 그래프로 저장한다(표준화 포함). `onnx` 패키지가 필요하다."""
    try:
        import onnx
        from onnx import TensorProto, helper, numpy_helper
    except Exception as exc:  # pragma: no cover - onnx 미설치 환경
        raise RuntimeError(
            "ONNX 내보내기에는 onnx 패키지가 필요합니다: pip install -r requirements-train.txt"
        ) from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dim = model.n_in
    initializers = [
        numpy_helper.from_array(model.mean.astype(np.float32).reshape(1, dim), "mean"),
        numpy_helper.from_array(model.std.astype(np.float32).reshape(1, dim), "std"),
    ]
    nodes = [
        helper.make_node("Sub", ["input", "mean"], ["x0"]),
        helper.make_node("Div", ["x0", "std"], ["x1"]),
    ]
    current = "x1"
    for i, (w, b) in enumerate(zip(model.weights, model.biases)):
        w_name, b_name = f"W{i + 1}", f"b{i + 1}"
        initializers.append(numpy_helper.from_array(w.astype(np.float32), w_name))
        initializers.append(numpy_helper.from_array(b.astype(np.float32), b_name))
        mm, add = f"mm{i + 1}", f"add{i + 1}"
        nodes.append(helper.make_node("MatMul", [current, w_name], [mm]))
        nodes.append(helper.make_node("Add", [mm, b_name], [add]))
        current = add
        if i < len(model.weights) - 1:
            relu = f"relu{i + 1}"
            nodes.append(helper.make_node("Relu", [current], [relu]))
            current = relu
    nodes.append(helper.make_node("Softmax", [current], ["probabilities"], axis=1))

    graph = helper.make_graph(
        nodes,
        "HOMEONQ_ActionMLP",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, ["batch", dim])],
        [helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, ["batch", model.n_classes])],
        initializer=initializers,
    )
    onnx_model = helper.make_model(
        graph,
        producer_name="HOMEONQ-training",
        opset_imports=[helper.make_opsetid("", opset)],
    )
    # onnxruntime 구버전과도 호환되도록 IR 버전을 낮춰 고정한다(기본값은 최신).
    onnx_model.ir_version = min(getattr(onnx, "IR_VERSION", 10), 10)
    onnx_model.doc_string = "HOMEONQ 행동 분류 MLP (33관절 특징 → 정상/낙상/무활동/배회)"
    try:
        onnx.checker.check_model(onnx_model)
    except Exception as exc:  # 검증 실패는 저장 전에 알린다
        raise RuntimeError(f"ONNX 그래프 검증 실패: {exc}") from exc
    onnx.save(onnx_model, str(path))
    return path


def verify_onnx(model: NumpyMLP, onnx_path: str | Path, x_sample: np.ndarray) -> dict[str, Any]:
    """onnxruntime으로 저장된 모델을 실행해 NumPy 결과와 비교한다."""
    import onnxruntime

    session = onnxruntime.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    x = np.ascontiguousarray(np.asarray(x_sample, dtype=np.float32))
    out = session.run(None, {session.get_inputs()[0].name: x})[0]
    expected = model.predict_proba(x_sample)
    max_diff = float(np.max(np.abs(out - expected))) if out.size else 0.0
    return {
        "onnxruntime": onnxruntime.__version__,
        "input_shape": list(x.shape),
        "output_shape": list(np.asarray(out).shape),
        "max_abs_diff": round(max_diff, 8),
        "matches_numpy": bool(max_diff < 1e-4),
    }
