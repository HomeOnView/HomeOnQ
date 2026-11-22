"""HOMEONQ AI 허브 학습 노트북(ipynb)을 생성·검증한다.

노트북을 손으로 JSON으로 쓰면 오타/깨진 셀이 생기기 쉬워서, 이 스크립트로 만들고
nbformat으로 검증한다. 코드 셀은 실행 전에 Python 문법 검사까지 한다.
CLI 호출은 셸 매직(`!`) 대신 `subprocess`를 쓴다 — Colab의 한글 Drive 경로에서도 안전하다.

    python scripts/build_training_notebook.py            # 생성 + 검증
    python scripts/build_training_notebook.py --check     # 기존 노트북만 검증
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "training" / "HOMEONQ_AIHub_Training.ipynb"

RUN_HELPER = '''import subprocess, sys, os


def run(*args):
    """현재 폴더(camera-analysis)에서 CLI를 실행한다. 한글 경로에서도 안전하다."""
    print("$", " ".join(str(a) for a in args))
    return subprocess.run([sys.executable, *map(str, args)], text=True).returncode
'''

CELLS: list[tuple[str, str]] = [
    ("markdown", """# HOMEONQ 행동 모델 학습 노트북 (AI 허브 → ONNX)

**목적**: AI 허브 시니어 이상행동 데이터(또는 시니어 보행/낙상 영상)를 **33관절 시계열**로 바꾸고,
낙상·장시간 무활동·배회·정상을 구분하는 경량 모델을 학습해 **ONNX 파일 하나**로 저장합니다.
그 파일을 `camera-analysis/models/action_classifier.onnx` 에 넣으면 웹앱·API 서버 코드를 건드리지 않고
파이프라인 판정이 AI 모델로 바뀝니다(파일이 없으면 기존 규칙으로 자동 폴백).

**실행 순서**

| 단계 | 내용 | 소요 |
|---|---|---|
| 0 | 환경 확인 → 저장소 받기 → 패키지 설치 | 3~5분 |
| 1 | (선택) 샘플 4종으로 뼈대 먼저 검증 | 1~2분 |
| 2 | AI 허브 데이터 연결 + 라벨 인식률 확인 | 5분 |
| 3 | 영상 → 33관절 전처리 | 데이터 양에 따라 수십 분~수 시간 |
| 4 | 학습 + 교차검증 + ONNX 저장 | CPU로 수 분 |
| 5 | 결과 저장/내려받기 → 파이프라인 연결 | 2분 |

> **먼저 읽어 주세요**
> - AI 허브 데이터는 **본인 계정으로 승인·다운로드**해야 합니다(로그인/약관 동의는 자동화할 수 없습니다).
> - 라벨 인식기는 AI 허브 JSON 키 이름을 **후보로 넓게** 찾습니다. 데이터셋 버전마다 키가 달라서
>   2단계에서 **인식률과 미인식 목록**을 꼭 확인하고, 필요하면 `label_map.json`(매핑표)을 만들어 주세요.
> - 모델은 33관절 좌표만 입력으로 받습니다. 영상 원본은 학습 PC/Drive에만 있고 서버로 올라가지 않습니다.
> - **임상 진단 도구가 아닙니다.** 낙상 알림은 보호자 확인을 돕는 참고 신호입니다.
"""),
    ("markdown", "## 0-1. GPU·런타임 확인\n\nColab 메뉴 `런타임 → 런타임 유형 변경 → GPU` 를 고르면 조금 빨라집니다(없어도 동작)."),
    ("code", """!nvidia-smi || echo "GPU 없음 — CPU로 진행합니다(그래도 동작합니다)"
import platform
print("Python", platform.python_version(), "|", platform.platform())"""),
    ("markdown", "## 0-2. 저장소 받기 (app-demo 브랜치)\n\n이미 코드가 있으면 이 셀은 건너뛰세요."),
    ("code", """import os, pathlib, subprocess
if not pathlib.Path("HOMEONQ/camera-analysis").exists():
    subprocess.run(["git", "clone", "--depth", "1", "-b", "app-demo",
                    "https://github.com/HomeOnView/HOMEONQ.git"], check=False)
os.chdir("HOMEONQ/camera-analysis")
print("현재 위치:", os.getcwd())"""),
    ("markdown", "## 0-3. 학습 패키지 설치\n\nMediaPipe(관절 추출) + ONNX(내보내기/추론) + 테스트 도구를 설치합니다."),
    ("code", RUN_HELPER + """
run("-m", "pip", "install", "-q", "-r", "requirements-train.txt")
import numpy, onnx, onnxruntime
print("numpy", numpy.__version__, "| onnx", onnx.__version__, "| onnxruntime", onnxruntime.__version__)"""),
    ("markdown", """## 1. (선택) 샘플 4종으로 뼈대 먼저 검증

영상이 아직 없어도, 저장소에 들어 있는 합성 33관절 샘플로 **전처리 → 학습 → ONNX → 추론** 전체가
도는지 2분 안에 확인할 수 있습니다. 처음 한 번은 이 셀을 먼저 돌려 파이프라인이 정상인지 보세요."""),
    ("code", """run("-m", "training.extract_landmarks", "--samples", "--out", "data/samples")
run("-m", "training.train_action_model", "--demo",
    "--out", "models/demo_action_classifier.onnx", "--report-dir", "reports/demo")
run("-m", "onview.cli", "model-check", "--model", "models/demo_action_classifier.onnx")"""),
    ("markdown", """## 2. AI 허브 데이터 연결

1. [AI 허브](https://www.aihub.or.kr) 에서 **시니어 이상행동 영상(500시간)** 데이터를 신청·승인받고 내려받습니다.
2. 압축을 풀면 보통 `원천데이터`(영상)와 `라벨링데이터`(JSON) 폴더로 나뉩니다.
3. Google Drive에 올렸다면 아래 셀에서 Drive를 마운트하고 **본인 경로**로 고쳐 주세요.

> 라벨이 영상 파일과 다른 이름이거나 클래스 이름이 낯설면, 아래처럼 **원본 라벨 → 표준 4클래스**
> 매핑표를 만들어 `LABEL_MAP` 에 경로를 넣으면 됩니다.
> ```json
> {"낙상": "fall", "쓰러짐": "fall", "배회": "wandering", "장시간 미동작": "inactivity", "일상": "normal"}
> ```"""),
    ("code", """from google.colab import drive
drive.mount('/content/drive')

AIHUB_LABEL_DIR = "/content/drive/MyDrive/AIHub/라벨링데이터"
AIHUB_VIDEO_DIR = "/content/drive/MyDrive/AIHub/원천데이터"
DATASET_DIR     = "/content/drive/MyDrive/AIHub/dataset"   # 33관절 결과 저장 위치
LABEL_MAP       = ""   # 예: "/content/drive/MyDrive/AIHub/label_map.json"

import os
for path in (AIHUB_LABEL_DIR, AIHUB_VIDEO_DIR):
    print(("✅ " if os.path.exists(path) else "❌ 없음 ") + path)"""),
    ("markdown", "### 2-1. 라벨 인식률 확인 (추출 없이 20개만)\n\n`미인식` 항목이 나오면 그 JSON의 키 이름을 알려주시면 어댑터에 추가할 수 있습니다."),
    ("code", """args = ["-m", "training.extract_landmarks", "--aihub-root", AIHUB_LABEL_DIR,
        "--video-root", AIHUB_VIDEO_DIR, "--out", DATASET_DIR, "--limit", "20", "--dry-run"]
if LABEL_MAP:
    args += ["--label-map", LABEL_MAP]
run(*args)"""),
    ("markdown", """## 3. 영상 → 33관절 전처리

`--limit` 을 빼면 전체를 처리합니다. 데이터가 크면 **클래스별로 나눠 여러 번** 실행하고
`--append` 로 이어 붙이는 것을 권장합니다(중간에 끊겨도 이어서 진행).

- `--fps 15`: 추출 목표 fps(모델 기본 창 30프레임 = 2초)
- `--max-seconds 30`: 클립당 최대 길이(한 영상이 길 때 메모리 보호)
- `--append`: 기존 `manifest.json` 뒤에 추가"""),
    ("code", """args = ["-m", "training.extract_landmarks", "--aihub-root", AIHUB_LABEL_DIR,
        "--video-root", AIHUB_VIDEO_DIR, "--out", DATASET_DIR,
        "--fps", "15", "--max-seconds", "30", "--append"]
if LABEL_MAP:
    args += ["--label-map", LABEL_MAP]
# 시간이 오래 걸리면 args += ["--limit", "200"] 처럼 나눠서 실행하세요.
run(*args)"""),
    ("markdown", "### 3-1. 데이터 분포 확인"),
    ("code", '''import json, collections
manifest = json.load(open(f"{DATASET_DIR}/manifest.json", encoding="utf-8"))
counts = collections.Counter(c["label"] for c in manifest["clips"])
print("클립:", len(manifest["clips"]), "| 클래스:", dict(counts))
print("미인식:", len(manifest.get("unmatched", [])), "| 건너뜀:", len(manifest.get("skipped", [])))
for item in manifest.get("unmatched", [])[:5]:
    print("  -", item)
print("총 시간(시간):", round(sum(c["duration_s"] for c in manifest["clips"]) / 3600, 2))
assert counts and min(counts.values()) > 0, "클래스가 비어 있습니다. 라벨 매핑표(LABEL_MAP)를 확인하세요."'''),
    ("markdown", """## 4. 학습 + 교차검증 + ONNX 저장

- 교차검증은 **클립 단위**입니다(같은 영상의 창이 학습/검증에 섞이지 않음).
- 증강 사본은 원본과 같은 폴드에 묶여 라벨 누설이 없습니다.
- 결과: `models/action_classifier.onnx` + `.json`(메타데이터) + `reports/action_model_report.md`

**해석 포인트**: 낙상은 `재현율(recall)`(놓치지 않음)과 `오탐률(FPR)`(정상을 낙상이라 하지 않음)을
함께 보세요. 임계값은 검증 데이터에서 F1 최대로 자동 선택되지만 **0.5 미만으로는 내려가지 않습니다**(오탐 억제)."""),
    ("code", """run("-m", "training.train_action_model", "--dataset", DATASET_DIR,
    "--out", "models/action_classifier.onnx", "--report-dir", "reports",
    "--window", "30", "--folds", "5", "--epochs", "300", "--augment", "2")"""),
    ("code", """from IPython.display import Markdown, display
display(Markdown(open("reports/action_model_report.md", encoding="utf-8").read()))"""),
    ("markdown", "## 5. ONNX 모델 검증 (추론 속도/일관성)"),
    ("code", """import json, time, numpy as np, onnxruntime

meta = json.load(open("models/action_classifier.json", encoding="utf-8"))
sess = onnxruntime.InferenceSession("models/action_classifier.onnx", providers=["CPUExecutionProvider"])
x = np.zeros((1, len(meta["feature_spec"]["vector_features"])), dtype=np.float32)
for _ in range(5):
    sess.run(None, {sess.get_inputs()[0].name: x})
t0 = time.perf_counter()
for _ in range(200):
    sess.run(None, {sess.get_inputs()[0].name: x})
print(f"추론 1회 평균: {(time.perf_counter() - t0) / 200 * 1000:.2f} ms (CPU)")
print("클래스:", meta["classes"], "| 창:", meta["window"], "| 특징 버전:", meta["feature_version"])
print("검증 지표:", json.dumps(meta["metrics"]["cv"], ensure_ascii=False)[:300])"""),
    ("markdown", """## 6. 결과 저장 / 내려받기

`models/action_classifier.onnx` 와 `.json` **두 파일이 한 쌍**입니다. 둘 다 있어야 파이프라인이 모델을 씁니다."""),
    ("code", """import os, shutil
from google.colab import files

save_dir = "/content/drive/MyDrive/AIHub/export"
os.makedirs(save_dir, exist_ok=True)
for name in ("models/action_classifier.onnx", "models/action_classifier.json",
             "reports/action_model_report.md"):
    if os.path.exists(name):
        shutil.copy(name, save_dir)
        print("저장:", name, "→", save_dir)

shutil.make_archive("/content/HOMEONQ_action_model", "zip", root_dir=".",
                    base_dir="models")
files.download("/content/HOMEONQ_action_model.zip")"""),
    ("markdown", """## 7. 파이프라인에 연결하기 (다음 단계 체크리스트)

1. 내려받은 **두 파일**을 이름 그대로 `camera-analysis/models/` 에 넣습니다.
   ```
   camera-analysis/models/action_classifier.onnx
   camera-analysis/models/action_classifier.json
   ```
2. 연결 확인:
   ```bash
   cd camera-analysis
   pip install -r requirements.txt          # onnxruntime 포함
   python -m onview.cli model-check          # "✅ ONNX AI 모델 사용 중" 이 나오면 성공
   python -m onview.cli analyze --scenario fall
   ```
3. 시연: `python -m onview.cli demo --scenario all --server http://localhost:8000` → 앱 '분석 테스트'에서 확인
4. 실제 카메라(Tapo C225): `python -m onview.cli serve --source rtsp://...`
5. 모델을 빼고 규칙 기반으로 되돌리려면 파일 이름을 바꾸거나 `USE_ACTION_MODEL=off` 로 실행합니다.

> **주의**: 학습 데이터와 실제 설치 환경(카메라 높이·화각·조명)이 다르면 오탐이 늘 수 있습니다.
> 설치 후 1~2주는 `USE_ACTION_MODEL=auto` 상태에서 알림을 **보호자가 직접 확인**하며 임계값을 조정하세요.
"""),
]


def build() -> Path:
    cells = []
    for kind, source in CELLS:
        source = source.rstrip("\n")
        cells.append(new_markdown_cell(source) if kind == "markdown" else new_code_cell(source))
    notebook = new_notebook(cells=cells)
    notebook.metadata.update(
        {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
            "colab": {"provenance": [], "toc_visible": True},
        }
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, str(TARGET))
    return TARGET


def check(path: Path = TARGET) -> list[str]:
    """nbformat 검증 + 코드 셀 문법 검사. 셸 매직(!)은 IPython 전용이라 pass로 바꿔 검사한다."""
    problems: list[str] = []
    notebook = nbformat.read(str(path), as_version=4)
    nbformat.validate(notebook)
    for i, cell in enumerate(notebook.cells):
        if cell.cell_type != "code":
            continue
        lines: list[str] = []
        for line in cell.source.splitlines():
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            if stripped.startswith("!") or stripped.startswith("%"):
                lines.append(indent + "pass  # shell magic")
            else:
                lines.append(line)
        try:
            compile("\n".join(lines), f"<cell {i}>", "exec")
        except SyntaxError as exc:
            problems.append(f"cell {i}: {exc}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="기존 노트북만 검증")
    args = parser.parse_args()
    path = TARGET if args.check else build()
    problems = check(path)
    if problems:
        print("❌ 노트북 검증 실패")
        for problem in problems:
            print("  -", problem)
        return 1
    notebook = nbformat.read(str(path), as_version=4)
    print(f"✅ 노트북 검증 통과: {path} ({path.stat().st_size:,} bytes)")
    print(f"   셀 {len(notebook.cells)}개 "
          f"(markdown {sum(c.cell_type == 'markdown' for c in notebook.cells)}, "
          f"code {sum(c.cell_type == 'code' for c in notebook.cells)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
