# 홈온큐 자세·동작 분석 파이프라인

`camera-analysis/` 는 드라이브의 `OnView_Pipeline_Draft.md`, `OnView_Stability_Pipeline_Draft.md` 설계를
실제 실행 가능한 코드로 옮긴 것입니다. 카메라가 없어도 샘플 관절좌표로 전체 흐름을 검증할 수 있습니다.

## 1. 데이터 흐름

```
CameraStream(RTSP/파일/웹캠)  ──프레임──▶  PoseAnalyzer(MediaPipe)
        │ 실패 시 지수 백오프 재연결              │ 33관절 (x,y,z,visibility)
        ▼                                        ▼
   HealthMetrics  ◀── 상태 갱신 ──  Detector(낙상·무활동·배회 규칙)
        │                                        │ DetectionEvent + 일일 지표
        ▼                                        ▼
   HealthMonitor ──60초 하트비트──▶  ReportGenerator(Gemini → 규칙 폴백)
        │                                        │
        ▼                                        ▼
   EventReporter ──HTTP──▶ /api/v1/device/{behavior-events,fall-events,daily-reports,heartbeat}
        │ 실패
        ▼
   LocalEventQueue(SQLite) ──복구 후 중복 없이 재전송──▶ EventReporter
```

## 2. 관절 좌표 규약

- MediaPipe Pose 33 landmark, **정규화 이미지 좌표**: `x,y ∈ [0,1]` (y는 아래로 증가), `z`는 상대 깊이, `visibility ∈ [0,1]`
- 미터 단위가 아니므로 낙상 속도 임계값은 "정규화 좌표/초"입니다. 설치 높이·화각이 다르면 현장에서 보정해야 합니다.
- `z`(상대 깊이)를 실제 거리로 해석하지 않습니다.
- 샘플 파일 형식(`samples/*.json`):

```json
{
  "scenario": "fall",
  "label": "낙상 발생",
  "description": "걷던 중 2.5초에 넘어져 바닥에 누운 9초 구간",
  "coordinate_system": "mediapipe_pose_33_normalized_image",
  "fps": 15,
  "time_scale": 1.0,
  "night": false,
  "daily_context": {"steps": 2980, "night_activity_minutes": 75, "...": "..."},
  "frames": [[[0.5, 0.33, 0.0, 0.9], "…33개…"], "…"]
}
```

`time_scale`은 긴 시간 시나리오를 짧은 클립으로 시연하기 위한 배속입니다. 예: 무활동 샘플 9.6초 × 1800 = 4.8시간.

## 3. 규칙 (PoC v1)

| 이벤트 | 계산 | 임계값(기본) | 산출물 |
|---|---|---|---|
| **낙상** | `drop_speed = Δ(골반 y)/Δt`, `torso_angle = atan2(|dx|,|dy|)`(직립 0°, 누움 90°), 누운 자세 유지 시간, 낙상 후 움직임 | 하강 ≥ 0.30/s · 기울기 ≥ 50° · 유지 ≥ 0.6s · 신뢰도 ≥ 0.55 | confidence, drop_speed, torso_angle, lying_seconds |
| **장시간 무활동** | 주요 관절(어깨·골반·손목·무릎·발목) 평균 이동량이 `MOTION_THRESHOLD` 미만인 최장 구간 | 240분 | 지속 시간, 비활동 비율 |
| **배회** | 몸통 중심 x의 평균 대비 좌우 반전 횟수·경과 시간 | 6회 · 5분 | 반전 횟수, 분 |

신뢰도는 규칙 기반 휴리스틱입니다(0.45 + 하강 속도 + 누운 시간 + 기울기 + 저운동). **임상 검증 값이 아닙니다.**

보조 지표: 걸음 수(양 발목 상하 교대), 보행 시간, 야간 활동, 화장실 이용, 침실 체류, 자세 안정성.

## 4. 일일 리포트 생성

1. 시퀀스 지표 + 샘플의 `daily_context`(시연용 하루 가정, `summary.projection`에 표시)로 하루 지표 구성
2. `scoring.py` 규칙으로 0~100 안심 점수와 요인 산출 — 서버 `app/services/scoring.py`와 동일 규칙(테스트로 일치 확인)
3. `report_generator.py`
   - `GEMINI_API_KEY` 있음 → REST `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
   - 키 없음/오류/응답 40자 미만 → **한국어 규칙 기반 문장**으로 자동 폴백 (`source=pipeline-rule`, `fallback_reason` 기록)
4. `POST /api/v1/device/daily-reports` 로 upsert

프롬프트는 "따뜻하고 차분한 존댓말 3문단, 500자 이내, 진단 금지, 참고 자료 명시, 이모지·마크다운 금지"를 요구합니다.

## 5. 안정성 모듈

| 모듈 | 동작 |
|---|---|
| `CameraStream` | 별도 스레드, 프레임 큐 30개, 실패 시 1s→2s→4s… 최대 30s 지수 백오프 |
| `HealthMonitor` | 1초 주기 판정, 60초 하트비트. 상태: `HEALTHY` / `DEGRADED`(fps<5) / `CAMERA_OFFLINE`(30s) / `ANALYSIS_FAILED`(60s) / `REPORTING_FAILED`(180s) |
| `LocalEventQueue` | SQLite WAL. 엔드포인트·페이로드·재시도 횟수 보존, 복구 시 순서대로 재전송 후 삭제 |
| `EventReporter` | `MOCK`(로그만) / `HTTP`. 실패 시 큐 적재, heartbeat로 파이프라인 상태 전송 |

파이프라인 상태는 백엔드 `camera_devices.health_status` 에 저장되어 앱 '설정' 화면에서 확인할 수 있습니다.

## 6. MediaPipe 설정

```bash
pip install mediapipe opencv-python-headless
python scripts/download_models.py     # pose_landmarker_lite.task (5.8MB, 저장소에도 포함)
python -m onview.cli mediapipe-check --image 사람사진.jpg
```

- MediaPipe 0.10.x: `mp.solutions.pose` 경로
- MediaPipe 1.x: Tasks API(`PoseLandmarker`) + `.task` 모델
- 초기화 실패(모델 없음, 네이티브 런타임 불가 등) 시 **Mock 경량 추정기로 자동 전환**하고 `PoseAnalyzer.fallback_reason`에 사유를 남깁니다.
- 일부 컨테이너 환경은 `/sys/devices/system/cpu`가 없어 MediaPipe 네이티브 라이브러리가 중단되므로, 이를 미리 감지해 우회합니다.

> 이번 작업 환경에서는 MediaPipe 패키지 설치와 모델 다운로드는 확인했지만, 샌드박스에 CPU 정보(`/sys/devices/system/cpu`)가 없어 네이티브 런타임이 뜨지 않았습니다. 실제 PC/라즈베리파이에서는 `mediapipe-check`로 검증하세요.

## 7. 알려진 한계

- 규칙 임계값은 거실 1대·정면 시점 기준의 초기값입니다. 다인 가구, 반려동물, 가구 가림에 대한 오탐 억제는 다음 단계입니다.
- 여러 사람이 등장하는 경우 첫 번째 자세만 사용합니다(`num_poses=1`).
- 영상 저장·클립 업로드는 메타데이터만 등록하며 실제 GCS 업로드/검증은 구현하지 않았습니다.
