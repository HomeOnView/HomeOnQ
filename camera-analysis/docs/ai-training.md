# HOMEONQ AI 행동 모델 학습·연동 가이드

이 문서는 **"AI 허브 시니어 이상행동 500시간 데이터(또는 시니어 보행/낙상 영상)"로 낙상·배회·무활동
판정 모델을 학습해 파이프라인에 끼우는 방법**을 순서대로 정리한 실행 문서입니다.

```
[1단계] 영상 → 33관절 (MediaPipe, 학습 불필요)
        training/extract_landmarks.py
                        │  .npz + manifest.json
                        ▼
[2단계] 33관절 시계열 → 행동 확률 (여기가 새로 학습하는 부분)
        training/train_action_model.py  →  action_classifier.onnx + .json
                        │
                        ▼
[3단계] 실시간 파이프라인: onview/inference.py 가 모델을 읽어 규칙과 함께 판정
        models/action_classifier.onnx 가 없으면 → 기존 규칙 기반으로 자동 폴백
```

- 서버(`api-server`)·웹앱·모바일 앱 코드는 **바뀌지 않습니다.** 모델 파일 두 개(ONNX + JSON)만 추가됩니다.
- 무거운 학습 의존성은 `requirements-train.txt` 로 분리되어 Render 무료 플랜(512MB)에는 설치되지 않습니다.

---

## 1. 준비물

| 항목 | 내용 |
|---|---|
| Python | 3.10~3.12 (Colab 기본) |
| 학습 패키지 | `pip install -r requirements-train.txt` (numpy·onnx·onnxruntime·mediapipe·opencv) |
| 데이터 | AI 허브 승인 후 내려받은 원천데이터(영상) + 라벨링데이터(JSON), 또는 라벨 CSV |
| 위치 | `camera-analysis` 폴더에서 실행 (Colab은 `HOMEONQ_AIHub_Training.ipynb` 사용) |

```bash
cd camera-analysis
python -m venv .venv-train && source .venv-train/bin/activate     # Windows: .venv-train\Scripts\activate
pip install -r requirements-train.txt
```

---

## 2. 1단계: 영상 → 33관절 시계열

### (a) 영상 없이 뼈대부터 확인 (2분)

```bash
python -m training.extract_landmarks --samples --out data/samples
python -m training.train_action_model --demo --out models/demo_action_classifier.onnx --report-dir reports/demo
python -m onview.cli model-check --model models/demo_action_classifier.onnx
```

저장소의 합성 33관절 샘플(정상·낙상·무활동·배회)을 4가지 길이로 늘려 학습합니다.
**구조 검증용**이며 성능 지표가 아닙니다(리포트에도 경고가 남습니다).

### (b) 라벨 CSV/JSON + 영상 폴더

```csv
video_path,label,start,end
videos/2024-01-03_cam1.mp4,낙상,2.4,11.0
videos/2024-01-03_cam2.mp4,배회,,
```

```bash
python -m training.extract_landmarks --labels labels.csv --video-root . \
    --out data/dataset --fps 15 --max-seconds 30
```

- 열 이름은 자동 인식합니다: 경로(`path`·`file`·`video`·`video_path`·`source`…), 라벨(`label`·`class`·`behavior`·`action`…), 구간(`start`·`end`).
- `start/end` 는 **라벨 구간**으로 해석하고, 그 앞 구간은 `normal`(배경)로 둡니다. 추출 범위는 영상 전체입니다(긴 영상은 `--max-seconds`).
- 라벨 이름은 한국어·영어 별칭을 폭넓게 인식합니다(`낙상/쓰러짐/fall`, `배회/서성/wandering`, `무활동/미동작/inactivity`, `정상/보행/normal`).

### (c) AI 허브 라벨 폴더

```bash
# 1) 먼저 인식률만 확인(추출 안 함)
python -m training.extract_landmarks --aihub-root ./AIHub/라벨링데이터 \
    --video-root ./AIHub/원천데이터 --out data/aihub --limit 20 --dry-run

# 2) 전체 추출
python -m training.extract_landmarks --aihub-root ./AIHub/라벨링데이터 \
    --video-root ./AIHub/원천데이터 --out data/aihub --fps 15 --max-seconds 30

# 3) 나눠서 이어 붙이기(중간에 끊겨도 안전)
python -m training.extract_landmarks ... --limit 500 --append
```

> **AI 허브 JSON 키 이름은 데이터셋·연도마다 다릅니다.** 그래서 어댑터는 특정 스키마를 가정하지 않고
> 라벨 후보 키(`label`·`behavior`·`action`·`category`·`type`…)와 영상 경로 후보 키
> (`video_path`·`file_name`·`source_file`…)를 넓게 탐색합니다. 그래도 인식하지 못한 파일은
> `manifest.json` 의 `unmatched` 에 사유와 함께 남습니다. 그 목록을 보고
> - 라벨 이름이 낯설면 → `label_map.json` 작성 후 `--label-map` 으로 전달
> - 영상 경로가 안 잡히면 → `--video-root` 를 실제 영상 폴더로 지정(파일명 기준 매칭)
>
> ```json
> {"낙상": "fall", "쓰러짐": "fall", "배회": "wandering", "장시간 미동작": "inactivity", "일상": "normal"}
> ```

### 산출물

```
data/dataset/
├── manifest.json        클립 목록(라벨·길이·구간·포즈 검출률)
├── normal_0001.npz      frames (n, 33, 4) float32 + fps
└── ...
```

- 포즈 검출률이 `--min-coverage`(기본 0.5)보다 낮은 클립은 건너뜁니다.
- 검출 실패 프레임은 이웃 프레임 선형 보간으로 채워 **시간축(fps)을 유지**합니다.

---

## 3. 2단계: 학습·평가·ONNX 내보내기

```bash
python -m training.train_action_model --dataset data/aihub \
    --out models/action_classifier.onnx --report-dir reports \
    --window 30 --folds 5 --epochs 300 --augment 2
```

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--window` | 30 | 창 길이(프레임). 15fps 기준 2초 |
| `--stride` | window/2 | 창 이동 간격 |
| `--folds` | 5 | **클립 단위** 교차검증 폴드 수 |
| `--augment` | 0 | 클립당 증강 사본 수(잡음·반전·시간왜곡·이동/확대) |
| `--hidden` | 64,32 | MLP 은닉층 |
| `--epochs` | 300 | 최대 학습 epoch(조기 종료 적용) |
| `--min-coverage` | 0.3 | 창 안 관절 가시성 하한 |

### 모델

- 구조: 표준화 → Linear(64) → ReLU → Linear(32) → ReLU → Linear(4) → Softmax (약 6천 파라미터, 수십 KB)
- 입력: 창 하나의 **97차원 특징**(채널 18개의 mean/std/max/min/변화량 + 좌우 반전 횟수·이동 폭·누움 비율·정지 비율 등)
- 특징 정의는 `onview/features.py` 한 곳에 있고 학습·추론이 **같은 코드**를 씁니다.
- 학습은 CPU로 수 분, GPU가 없어도 Colab 무료 런타임에서 충분합니다.
- 시계열 CNN(LSTM/1D-CNN)으로 바꾸려면 `train_action_model.py` 에 백엔드를 추가하면 됩니다.
  추론기는 `input_kind`(vector/sequence)만 보고 동작하므로 서버·앱은 그대로입니다.

### 평가 지표 읽는 법

`reports/action_model_report.md` 에 다음이 남습니다.

- 혼동행렬(행=실제, 열=예측)
- 클래스별 **정밀도 / 재현율 / F1 / 오탐률(FPR)** / 표본 수
- 클립 단위 교차검증 요약(정확도·매크로 F1)
- 자동 선택된 확률 임계값(0.5~0.9, **0.5 미만으로는 내리지 않음** — 오탐 억제)
- ONNX 실행 검증(NumPy 결과와 최대 오차)

낙상 모델에서 우선 볼 숫자:

| 지표 | 의미 | 목표 |
|---|---|---|
| 재현율(recall) | 실제 낙상을 놓치지 않은 비율 | 높게 |
| 오탐률(FPR) | 정상 상황을 낙상이라 한 비율 | 낮게 |
| 지연 | 낙상 발생 → 알림까지 | 창 길이(2초) + 추론(수 ms) |

> 같은 낙상 영상의 창이 학습·검증에 나뉘어 들어가면 성능이 실제보다 좋게 나옵니다.
> 이 파이프라인은 **클립 단위**로 폴드(그룹)를 나누고, 증강 사본도 원본과 같은 폴드에 묶어 누설을 막습니다.

---

## 4. 3단계: 파이프라인 연결

```bash
cp <학습결과>/action_classifier.onnx camera-analysis/models/
cp <학습결과>/action_classifier.json camera-analysis/models/

cd camera-analysis && pip install -r requirements.txt   # onnxruntime 포함
python -m onview.cli model-check      # ✅ ONNX AI 모델 사용 중
python -m onview.cli analyze --scenario fall
python -m onview.cli demo --scenario all --server http://localhost:8000
```

동작 규칙(`onview/inference.py` + `detector.analyze_sequence`):

1. 규칙 기반 감지는 **항상** 돕니다(안전망).
2. 모델이 있으면 창마다 4클래스 확률을 계산합니다.
3. 모델이 규칙이 놓친 낙상·무활동·배회를 찾으면 **이벤트를 추가**하고,
   같은 종류를 이미 규칙이 찾았으면 그 이벤트에 `model_probability` 를 덧붙입니다.
4. 다음 경우에는 **자동으로 규칙 기반만** 사용하고 `metrics.detector = "rule"` 로 남깁니다.
   - 모델 파일 또는 메타데이터(`.json`) 없음
   - `onnxruntime`·`numpy` 미설치
   - `USE_ACTION_MODEL=off`
   - 메타데이터의 `feature_version` 이 코드와 불일치(특징 정의가 바뀐 모델)
   - 추론 중 예외(손상된 파일, 입출력 차원 불일치 등)

리포트/앱에는 `summary.detector`(`rule` / `rule+onnx`)와 `summary.ai_model`(모델명·버전·평균 확률)이
함께 저장됩니다.

### 임계값 조정

| 환경변수 | 기본 | 의미 |
|---|---|---|
| `ACTION_MODEL_PATH` | `models/action_classifier.onnx` | 모델 경로(같은 이름 `.json` 자동 인식) |
| `USE_ACTION_MODEL` | `auto` | `off` 면 규칙만 사용 |
| `MODEL_FALL_THRESHOLD` | 0.60 | 낙상 확률 임계값 |
| `MODEL_INACTIVITY_THRESHOLD` | 0.60 | 무활동 임계값 |
| `MODEL_WANDERING_THRESHOLD` | 0.60 | 배회 임계값 |
| `MODEL_INACTIVITY_MIN_WINDOWS` | 3 | 무활동으로 인정할 연속 창 수 |
| `MODEL_WANDERING_MIN_WINDOWS` | 2 | 배회로 인정할 최소 창 수 |
| `MODEL_WANDERING_MIN_SECONDS` | 5 | 배회 최소 지속(초, 클립 시간) |

메타데이터의 `thresholds` 가 환경변수보다 우선합니다(학습 시 검증 데이터로 고른 값).

---

## 5. 학습한 모델 파일의 정체

`action_classifier.onnx` 옆의 `action_classifier.json`:

```json
{
  "format": "HOMEONQ-action-model/1",
  "model_name": "HOMEONQ-ActionNet",
  "version": "v1",
  "input_kind": "vector",
  "window": 30,
  "fps": 15.0,
  "feature_version": "HOMEONQ-FEAT-v1",
  "classes": ["normal", "fall", "inactivity", "wandering"],
  "thresholds": {"fall": 0.75, "inactivity": 0.65, "wandering": 0.7},
  "dataset": {"clips": 128, "windows": 9032, "class_counts": {...}},
  "metrics": {"cv": {...}, "cv_per_class": {...}, "onnx": {"matches_numpy": true}}
}
```

이 JSON이 없거나 `feature_version` 이 다르면 추론기는 모델을 **쓰지 않습니다**(규칙 기반). 모델만 복사하고
JSON을 빠뜨리는 실수를 막기 위한 장치입니다.

---

## 6. 문제 해결

| 증상 | 원인/해결 |
|---|---|
| `MediaPipe Pose를 사용할 수 없습니다` | `pip install mediapipe opencv-python-headless` 후 `python scripts/download_models.py`. 일부 컨테이너는 `/sys/devices/system/cpu` 가 없어 네이티브 런타임을 못 씁니다(로컬 PC·Colab 사용) |
| `AI 허브 라벨: 0개 인식` | `--dry-run` 으로 `unmatched` 목록 확인 → `label_map.json` 또는 `--video-root` 수정 |
| `포즈 검출률 낮음` 으로 전부 건너뜀 | 카메라가 너무 멀거나 밤 영상. `--min-coverage 0.3` 로 완화하되, 검출률 낮은 데이터는 학습 품질이 떨어집니다 |
| ONNX 검증 생략(onnxruntime 없음) | `pip install onnxruntime` 후 재실행. 학습 산출물은 정상 저장됩니다 |
| `특징 버전 불일치` | 코드의 특징 정의가 바뀐 경우. 모델을 다시 학습하거나 `feature_version` 을 맞춥니다 |
| 모델을 넣었는데 계속 규칙 기반 | `python -m onview.cli model-check` 로 사유 확인(파일명·JSON 짝·onnxruntime) |
| 오탐이 많음 | `MODEL_FALL_THRESHOLD` 를 0.7~0.85로 올리고, 실제 설치 환경 영상으로 소량 재학습(파인튜닝) |

---

## 7. 이 파이프라인의 한계(솔직한 메모)

- **실제 AI 허브 500시간 학습은 이 저장소에 포함되어 있지 않습니다.** 데이터 승인·다운로드와 실행은
  본인 계정/PC(또는 Colab)에서 해야 합니다. 여기 있는 것은 그 실행을 위한 **전처리·학습·추론 코드와 검증된 뼈대**입니다.
- 기본 모델은 **97차원 특징 위의 MLP**입니다. 시계열 CNN보다 표현력이 낮지만, 수천 시간 규모에서도
  CPU로 수 분 내 학습되고 해석·배포가 쉽습니다. 성능이 부족하면 시퀀스 모델로 교체하세요(구조는 준비됨).
- 라벨이 **클립 단위**뿐이면 낙상 전 정상 구간도 낙상으로 학습될 수 있습니다. 가능하면 구간 라벨(`start/end`)을 쓰세요.
- 카메라 설치 높이·화각이 학습 데이터와 다르면 성능이 떨어집니다. 설치 후 1~2주는 보호자가 알림을 직접 확인하세요.
- **임상 진단 도구가 아닙니다.** 낙상·이상행동 알림은 보호자 확인을 돕는 참고 신호입니다.
