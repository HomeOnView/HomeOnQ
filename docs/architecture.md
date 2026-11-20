# 홈온큐 아키텍처 (시연용 통합본)

## 1. 구성 요소

| 계층 | 기술 | 역할 |
|---|---|---|
| 모바일 웹앱 | HTML/CSS/Vanilla JS (빌드 없음) | 보호자 UI. FastAPI가 `/`에서 정적 서빙 |
| API 서버 | FastAPI 0.165, Pydantic 2 | 인증·프로필·리포트·이벤트·알림·기기 API |
| DB | SQLite(개발) / PostgreSQL(운영) | SQLAlchemy 2.x 모델 + Alembic 4개 리비전 |
| 분석 파이프라인 | Python 3.12, numpy, (선택) MediaPipe/OpenCV | 관절좌표 → 낙상·무활동·배회 → 리포트 |
| 리포트 생성 | Gemini REST(선택) + 규칙 기반 폴백 | 한국어 안심 리포트 문장 |
| Expo 앱 | Expo SDK 54 / RN 0.81 | 네이티브 경로(같은 API 사용) |

## 2. 요청 흐름

### 보호자 조회
```
웹앱 → GET /guardians/me/seniors → 프로필·기기
     → GET /seniors/{id}/daily-reports/latest → 점수·문장·요약
     → GET /seniors/{id}/events → 행동+낙상 타임라인
     → GET /guardians/me/alerts (20초 폴링) → 낙상 알림 모달
```

### 분석 → 저장 → 알림
```
POST /demo/simulate (웹앱)
  ├ onview.simulation.analyze_scenario(scenario)
  │    ├ samples/*.json 로드
  │    ├ detector: 낙상/무활동/배회 + 지표
  │    ├ scoring: 0~100 점수
  │    └ report_generator: Gemini 또는 규칙 문장
  └ httpx ASGITransport → POST /api/v1/device/behavior-events (×N)
                        → POST /api/v1/device/fall-events
                        → POST /api/v1/device/daily-reports
                        → POST /api/v1/device/heartbeat
  ⇒ 라우터·검증·트랜잭션을 실제와 동일하게 통과해 SQLite에 저장
  ⇒ 응답에 분석 요약을 담아 웹앱이 즉시 화면 갱신 + 알림 모달
```

실제 엣지 장비에서는 같은 페이로드를 `onview.cli demo/serve`가 **TCP HTTP**로 전송합니다(`scripts/e2e_demo.py`가 이 경로를 검증).

## 3. 데이터 모델(요약)

```
guardians ─< guardian_senior >─ seniors ─< camera_devices
                                  ├─< behavior_events
                                  ├─< daily_scores
                                  ├─< daily_reports (senior_id, report_date unique)
                                  ├─< senior_baselines
                                  └─< fall_sessions ─< fall_events ─< notifications
                                                       ├─< video_clips
                                                       └─ fall_learning_sequences
guardians ─< auth_sessions
outbox_messages  (알림 발송 트랜잭션 기록: fall.notification)
```

- 모든 시각은 UTC 저장. 응답 시 `iso_utc()` 로 `Z` 오프셋을 보장.
- 낙상 저장은 세션·이벤트·알림·Outbox를 한 트랜잭션으로 묶어, 알림 유실 없이 후속 워커가 처리할 수 있게 합니다.
- 행동 이벤트는 `event_id`(UUID) + `payload_hash` 로 멱등성을 보장합니다.

## 4. 보안 경계

| 항목 | 구현 |
|---|---|
| 비밀번호 | Argon2id |
| 보호자 토큰 | HS256 JWT 15분 + 회전 refresh 30일(해시 저장, 재사용 감지 시 전체 폐기) |
| 기기 토큰 | 384bit 랜덤, SHA-256 해시만 저장, 회전/폐기 API |
| 권한 | 모든 대상자 경로에서 `guardian_senior` 활성 관계 확인. 없으면 404(존재 숨김) |
| 운영 가드 | production에서 강한 JWT_SECRET·PostgreSQL·AUTO_CREATE_SCHEMA=false·CORS 와일드카드 금지 강제 |
| 데모 API | production에서 404 |
| PII | 앱은 필요한 필드만 노출. 사진 URL·메모는 보호자 수정 가능 |

## 5. 확장 지점

- **알림**: `outbox_messages` → FCM/APNs 워커, 실패 재시도(`retry_count`, `next_retry_at` 이미 존재)
- **영상**: `video_clips` → GCS 업로드·무결성 검증·보존기간, 앱에서 WebRTC/RTSP 프록시 재생
- **다가구**: `camera_devices.senior_id` 단위로 이미 분리되어 있어 수평 확장 가능
- **점수**: `policy_version`으로 산식 교체 이력 관리
