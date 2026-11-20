# 홈온큐 API 명세 (v0.3.0)

Base path: `/api/v1` · 인증: 보호자 `Authorization: Bearer <access_token>`, 기기 `X-Device-Token: <device_token>`
응답의 모든 시각은 **UTC ISO-8601(`...Z`)** 입니다. (SQLite의 naive 값도 서버에서 UTC로 보정)

## 1. 인증

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| POST | `/auth/register` | 없음 | 이메일/비밀번호(12자 이상) 가입 |
| POST | `/auth/login` | 없음 | access(15분) + refresh(30일) 발급 |
| POST | `/auth/refresh` | body.refresh_token | refresh 회전. 재사용 감지 시 해당 계정 세션 전체 폐기 |
| POST | `/auth/logout` | Bearer | 본인 refresh 세션 폐기 (204) |
| GET | `/auth/me` | Bearer | 현재 보호자 |

```json
// POST /auth/login
{"email":"demo@homeonq.kr","password":"homeonq-demo-2026"}
// 200
{"access_token":"...","refresh_token":"...","token_type":"bearer","expires_in":900}
```

## 2. 보호자 · 어르신

| Method | Path | 설명 |
|---|---|---|
| GET | `/guardians/me/seniors` | 연결된 어르신 목록(프로필 + 기기) |
| GET | `/seniors/{senior_id}` | 프로필 상세 |
| PATCH | `/seniors/{senior_id}` | 프로필 수정 |
| GET | `/seniors/{senior_id}/daily-reports/latest?report_date=` | 최신(또는 지정일) 안심 리포트 |
| GET | `/seniors/{senior_id}/daily-reports?start=&end=&page=&page_size=` | 리포트 이력 |
| GET | `/seniors/{senior_id}/events?days=7&kind=fall\|behavior&limit=` | 행동+낙상 통합 타임라인 |
| GET | `/seniors/{senior_id}/summary?days=7` | 낙상 건수·미확인 알림·최근 리포트 |
| POST | `/seniors/{senior_id}/test-fall` | 낙상 테스트 알림 생성(201) |
| GET | `/seniors/{senior_id}/fall-events?page=&page_size=` | 낙상 이벤트 목록 |
| GET | `/seniors/{senior_id}/fall-events/{event_id}` | 낙상 상세 |
| PATCH | `/seniors/{senior_id}/fall-events/{event_id}` | `{"status":"CONFIRMED\|DISMISSED\|SUSPECTED"}` |
| GET | `/seniors/{senior_id}/baseline` | 기준선 상태·평균 |
| GET | `/seniors/{senior_id}/daily-score` · `/daily-scores` | (기존) 점수 테이블 조회 |
| GET | `/seniors/{senior_id}/video-clips` | 클립 메타데이터 |
| POST | `/seniors/{senior_id}/score-preview` | 점수 산식 확인(시연) |

### 프로필 수정 (PATCH)

```json
{
  "display_name": "강O순 어르신",
  "birth_date": "1951-03-12",
  "gender": "여성",
  "height_cm": 159.5,
  "weight_kg": 52,
  "medical_conditions": ["당뇨", "고혈압", "척추측만증", "관절염"],
  "photo_url": "https://...",
  "emergency_contact": "010-0000-0000",
  "memo": "거실 카메라로 관찰 중"
}
```
- 보낸 필드만 갱신합니다. `gender`는 `여성/남성/기타/미입력`, `height_cm` 50~250, `weight_kg` 20~250, `photo_url`은 http(s)만 허용.
- 검증 실패는 `422`.

### 일일 리포트 응답

```json
{
  "senior_id": "...",
  "report_date": "2026-11-21",
  "score": 45,
  "risk_level": "ALERT",
  "risk_label": "경계",
  "ui_color": "#B42318",
  "headline": "강O순 어르신 댁에서 낙상 의심 신호가 감지되었습니다",
  "narrative": "11월 21일 ... (문단)",
  "summary": {
    "metrics": {"steps": 2980, "night_activity_minutes": 75, "toilet_visits": 9,
                 "bedroom_minutes": 420, "inactivity_minutes": 265},
    "baseline": {"steps": 4100},
    "rows": [{"key": "steps", "label": "보행", "value": 2980, "unit": "걸음", "delta_percent": -27}],
    "fall_count": 1,
    "segment_metrics": {"steps": 5, "torso_angle_max": 88.8},
    "projection": "daily_context"
  },
  "factors": {"policy_version": "homeonq-score-poc-v1", "items": [
      {"code": "FALL_RECENT", "label": "낙상 의심", "delta": -20, "detail": "낙상 의심 이벤트가 1건 있습니다"}
  ]},
  "data_status": "FINAL",
  "source": "pipeline-rule",
  "model_name": null,
  "event_count": 6,
  "generated_at": "2026-11-21T00:43:12.345Z",
  "policy_version": "homeonq-score-poc-v1"
}
```

### 이벤트 타임라인 항목

```json
{"kind":"fall","id":"...","event_id":"sim-...","title":"낙상 의심","detail":"...",
 "occurred_at":"2026-11-21T00:43:10Z","status":"SUSPECTED","risk_level":"HIGH",
 "confidence":0.95,"is_test":false}
{"kind":"behavior","id":"...","event_id":"...","title":"보행","detail":"...",
 "occurred_at":"2026-11-20T21:43:00Z","status":"ANALYZED","confidence":0.92,
 "value":2980,"unit":"걸음","activity_type":"WALKING"}
```

## 3. 기기(카메라 엣지)

| Method | Path | 설명 |
|---|---|---|
| POST | `/guardians/me/devices` | 기기 등록 → `device_token` **최초 1회만** 반환 |
| GET | `/guardians/me/devices` | 내 기기 목록 |
| POST | `/guardians/me/devices/{device_id}/rotate-key` · `/revoke` | 토큰 회전 / 폐기 |
| GET | `/device/me` | 인증된 기기 정보 |
| POST | `/device/heartbeat` | `{"status":"HEALTHY","metrics":{...}}` (본문 생략 가능) |
| POST | `/device/behavior-events` | 행동 지표 (멱등) |
| POST | `/device/baseline-data` | 기준선 샘플 |
| POST | `/device/fall-events` | 낙상 의심 |
| POST | `/device/daily-reports` | 안심 리포트 upsert |
| POST | `/device/video-clips` | 클립 메타데이터 |

### behavior-events

```json
{
  "event_id": "uuid(≤36)",
  "captured_at": "2026-11-21T00:40:00Z",
  "activity_type": "WALKING",
  "event_value": 3380,
  "unit": "걸음",
  "walking_steps": 3380,
  "confidence": 0.9,
  "data_quality": 0.92,
  "feature_version": "onview-pipeline-v1",
  "metadata": {"scenario":"normal","coordinate_system":"mediapipe_pose_33_normalized_image"}
}
```
- `event_id`가 같고 페이로드가 같으면 `200 {"status":"duplicate"}`, 다르면 `409`.
- `captured_at`에 시간대가 없으면 `422`.
- `event_value`/`unit`이 있으면 그 값이 이벤트 값으로 저장되고, 없으면 `walking_steps → movement_level → 0` 순으로 환산합니다.

### fall-events

```json
{
  "event_id": "sim-...",
  "detected_at": "2026-11-21T00:43:10Z",
  "fall_suspected": true,
  "confidence": 0.95,
  "risk_level": "HIGH",
  "reasoning": "골반 높이가 0.71/s 속도로 급격히 낮아지고 ...",
  "feature_summary": {"drop_speed":0.71,"torso_angle_deg":88.8,"lying_seconds":4.0},
  "metadata": {"source":"camera-analysis","scenario":"fall"}
}
```
- `fall_suspected:false`는 `422` (의심 이벤트만 수용).
- 성공 시 `FallSession` + `FallEvent` + 보호자별 `Notification` + `OutboxMessage`가 **한 트랜잭션**으로 생성됩니다.

### daily-reports

```json
{"report_date":"2026-11-21","score":45,"risk_level":"ALERT","risk_label":"경계",
 "ui_color":"#B42318","headline":"...","narrative":"...",
 "summary":{...},"factors":{...},"data_status":"FINAL","source":"pipeline-gemini",
 "model_name":"gemini-2.0-flash","event_count":6,"generated_at":"..."}
```
- `(senior_id, report_date)` 유니크. 같은 날짜 재전송은 `201 {"status":"updated"}`.

## 4. 데모(개발 전용)

| Method | Path | 설명 |
|---|---|---|
| GET | `/demo/config` | 데모 활성 여부·계정·시나리오 목록 |
| POST | `/demo/simulate` | `{"scenario":"normal\|fall\|inactive\|wandering","senior_id":"..."}` → 파이프라인 분석 후 기기 API로 재전송 |
| POST | `/demo/reset` | 데모 활동/낙상/리포트 초기화 후 재시드 |

`APP_ENV=production` 이면 세 경로 모두 `404` 입니다.

## 5. 오류 규칙

| 코드 | 의미 |
|---|---|
| 401 | 토큰 없음/만료, 기기 토큰 불일치 |
| 404 | 대상자/이벤트 비노출(권한 없는 대상자도 404로 응답해 존재 여부를 숨김) |
| 409 | 이메일/기기 중복, 같은 ID 다른 페이로드, 카메라 없는 낙상 테스트 |
| 422 | 입력 검증 실패(시간대 누락, confidence 범위 등) |

CORS는 `CORS_ORIGINS`(기본 Expo web/로컬) + 개발 환경에서 사설망(LAN) 정규식을 허용합니다. 운영에서는 와일드카드가 금지됩니다.
