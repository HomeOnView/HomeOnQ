"""HOMEONQ 행동 데이터 학습 파이프라인.

| 모듈 | 역할 |
|---|---|
| `labels` | 라벨 파일(CSV/JSON)·AI 허브 라벨 폴더 → 표준 4클래스(`normal`/`fall`/`inactivity`/`wandering`) |
| `dataset` | 33관절 시퀀스(`.npz`)·매니페스트 로더, 창(window) 자르기 |
| `augment` | 잡음·좌우반전·시간왜곡·이동/확대 증강 |
| `extract_landmarks` | 영상 → 33관절 시퀀스(`.npz`) + 매니페스트 |
| `evaluate` | 혼동행렬·정밀도·재현율·오탐률 리포트 |
| `numpy_model` | 경량 MLP 학습 + ONNX 내보내기(무거운 의존성 없음) |
| `train_action_model` | 위 모듈을 묶은 학습 CLI(교차검증 → ONNX/메타데이터/리포트) |

실행 예시는 `camera-analysis/docs/ai-training.md` 참고.
"""
