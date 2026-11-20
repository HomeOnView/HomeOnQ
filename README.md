# 홈온큐(HOMEONQ) 통합 시연 프로젝트

> 부모님의 하루를 조용히 지켜보는 보호자 안심 리포트
> **링크 하나로 열리는 모바일 웹앱 + FastAPI 백엔드 + 자세·동작 분석 파이프라인**을 한 저장소로 묶었습니다.

- 웹앱·API·DB·분석 파이프라인이 **한 서버**에서 동작합니다. 서버를 켜고 `http://localhost:8000/` 을 열면 바로 시연됩니다.
- 웹앱의 **분석 테스트** 버튼을 누르면 `camera-analysis` 파이프라인이 샘플 관절좌표를 실제로 분석하고, 기기용 텔레메트리 API로 전송해 SQLite에 저장한 뒤, 보호자 리포트와 낙상 알림 화면이 갱신됩니다.
- Expo(React Native) 앱도 같은 API에 연결되어 있습니다(`mobile-app/`). 스토어 출시 없이 Expo Go로 확인할 수 있습니다.

```
┌─────────────────────────── http://localhost:8000 ───────────────────────────┐
│  mobile-webapp (/)            FastAPI (/api/v1)              SQLite/Postgres │
│  ├ 로그인 · 안심 리포트        ├ auth / guardians / seniors    ├ seniors      │
│  ├ 이벤트 · 낙상 알림          ├ device/behavior-events        ├ behavior_*  │
│  ├ 분석 테스트(시뮬레이션)  ◀──┤ device/fall-events            ├ fall_*      │
│  └ 설정 · 프로필 수정          ├ device/daily-reports           ├ daily_reports│
│                               ├ guardians/me/alerts            ├ notifications│
│                               └ demo/simulate ◀── camera-analysis (onview)   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. 3분 안에 실행하기 (로컬)

```bash
# 1) 백엔드 의존성 (Python 3.11+)
cd api-server
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) DB 마이그레이션 + 데모 데이터(보호자·어르신·카메라·기준선·오늘 리포트)
python scripts/dev_bootstrap.py

# 3) 서버 실행 (웹앱까지 같은 서버가 서빙)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

브라우저에서 **http://localhost:8000/** 을 엽니다. 데모 계정이 자동 입력되어 있습니다.

| 항목 | 값 |
|---|---|
| 보호자 이메일 | `demo@homeonq.kr` |
| 비밀번호 | `homeonq-demo-2026` |
| 어르신 | 강O순 어르신 (75세·여성) |
| 카메라 | `TAPO-C225-LIVING`, `DEMO-EDGE-01` (시뮬레이션용) |

휴대폰에서 보려면 PC와 같은 Wi-Fi에서 `http://<PC의 LAN IP>:8000/` 을 엽니다. (예: `http://192.168.0.12:8000/`)

### 한 줄 실행 스크립트

```bash
./scripts/run_local.sh          # venv 생성 → 설치 → 마이그레이션/시드 → 서버 실행
```

---

## 2. 시연 순서 (1R 심사용 촬영 추천)

1. **로그인 화면** → `데모 계정으로 바로 시작`
2. **리포트 홈**: 어르신 프로필, 안심 점수(70점·주의), AI 안심 리포트, 주요 이벤트 요약 확인
3. **분석 테스트** 탭 → `낙상 발생` 카드 클릭
   - ① 샘플 관절좌표 로드 → ② 낙상 감지(신뢰도 95%) → ③ `/api/v1/device/*` 전송 → ④ 리포트·알림 갱신
   - 결과 카드에 탐지 이유("골반 높이가 0.71/s 속도로 급격히 낮아지고 몸통 기울기가 89°…")와 점수 변화(45점·경계) 표시
4. **낙상 비상 알림 모달** 자동 표시 → `확인했습니다` 로 알림 처리
5. **이벤트** 탭: 낙상/행동 필터, 항목을 눌러 상세·오탐 처리
6. **설정**: 기기 상태, 서버/DB 상태, 프로필 수정
7. 다른 시나리오도 같은 방식: `정상 보행`(92점·안심), `장시간 무활동`(73점·주의), `야간 배회`(62점·주의)
8. `데모 초기화` 로 언제든 초기 상태로 복귀

> 점수 산식(`homeonq-score-poc-v1`)은 임상 검증 전 **시연용 규칙**입니다. 화면에도 "참고용 지표 · 의료 진단 아님"으로 표기됩니다.

---

## 3. 폴더 구조

```
homeonq-app/
├── api-server/                 FastAPI + SQLAlchemy 2.x + Alembic
│   ├── app/
│   │   ├── main.py             라우터 등록 + 웹앱 정적 서빙(/)
│   │   ├── api/routes/
│   │   │   ├── auth.py         회원가입·로그인·refresh(회전)·logout
│   │   │   ├── devices.py      기기 등록/회전/폐기·heartbeat(상태 저장)
│   │   │   ├── telemetry.py    behavior-events·baseline·fall-events·video-clips·알림
│   │   │   ├── guardian.py     프로필·일일 리포트·이벤트 타임라인·낙상 테스트·알림
│   │   │   ├── reports.py      device/daily-reports (파이프라인 리포트 수신)
│   │   │   └── demo.py         웹앱 시뮬레이션/초기화(개발 전용)
│   │   ├── models/             guardians, seniors, camera_devices, daily_reports …
│   │   ├── services/           scoring, report_text, events, reports, demo_seed
│   │   └── core/timeutil.py    UTC ISO 직렬화(SQLite naive 보정)
│   ├── migrations/versions/    초기 스키마 + 인증 + outbox + daily_reports/프로필
│   ├── webapp/                 ★ 모바일 웹앱(index.html, styles.css, app.js)
│   ├── scripts/dev_bootstrap.py
│   └── tests/                  20개 API/모델 테스트
├── camera-analysis/            자세·동작 분석 파이프라인 (Python)
│   ├── onview/
│   │   ├── detector.py         낙상·장시간 무활동·배회 규칙
│   │   ├── pose_analyzer.py    MediaPipe Pose(0.10 solutions / 1.x Tasks) + 자동 폴백
│   │   ├── video_input.py      RTSP/웹캠 스레드 + 지수 백오프 재연결
│   │   ├── health_monitor.py   HEALTHY/DEGRADED/CAMERA_OFFLINE/ANALYSIS_FAILED/REPORTING_FAILED
│   │   ├── reporter.py         텔레메트리 API 전송 + 실패 시 SQLite 큐
│   │   ├── local_queue.py      오프라인 이벤트 영구 큐
│   │   ├── report_generator.py Gemini 우선 · 규칙 기반 자동 폴백
│   │   ├── pipeline.py         분석→페이로드→전송
│   │   ├── simulation.py       웹앱 시뮬레이션용 진입점
│   │   └── cli.py              analyze / demo / mediapipe-check / serve
│   ├── samples/                정상 보행 · 낙상 · 무활동 · 배회 관절좌표(33관절)
│   ├── models/                 pose_landmarker_lite.task (5.8MB)
│   └── tests/                  33개 파이프라인 테스트
├── mobile-app/                 Expo SDK 54 보호자 앱 (talking-blue-cookies 발전형)
│   ├── App.js                  세션·탭·폴링·알림 상태
│   └── src/{api,screens,components,theme,config}
├── docs/                       API 명세 · 아키텍처 · 파이프라인 · 시연 가이드
├── render.yaml                 Render 무료 배포 정의(Blueprint)
└── scripts/                    run_local.sh · e2e_demo.py · render_smoke.py · verify_all.sh · 검증 스크립트
```

---

## 4. 백엔드 API 요약

Base path `/api/v1`. 기기 API는 `X-Device-Token`, 보호자 API는 `Authorization: Bearer <access_token>`.

| 구분 | Method · Path | 기능 |
|---|---|---|
| 인증 | `POST /auth/register` · `/auth/login` · `/auth/refresh` · `/auth/logout` · `GET /auth/me` | Argon2id + JWT(15분) + 회전 refresh(30일) |
| 보호자 | `GET /guardians/me/seniors` | 연결된 어르신 목록(프로필·기기 포함) |
| | `GET/PATCH /seniors/{id}` | 프로필 조회/수정(키·체중·병력·사진·응급연락처) |
| | `GET /seniors/{id}/daily-reports/latest` · `/daily-reports` | 최신/기간별 안심 리포트 |
| | `GET /seniors/{id}/events?days=7&kind=` | 행동+낙상 통합 타임라인 |
| | `GET /seniors/{id}/summary` | 낙상 건수·미확인 알림·최근 리포트 요약 |
| | `POST /seniors/{id}/test-fall` | 앱 '낙상 테스트' → 세션·이벤트·알림·Outbox 생성 |
| | `GET /seniors/{id}/fall-events` · `PATCH …/{event_id}` | 낙상 목록/확인·오탐 처리 |
| | `GET /guardians/me/alerts` · `POST /guardians/me/notifications/{id}/acknowledge` | 미확인 알림/확인 처리 |
| 기기 | `POST /device/behavior-events` | 행동 지표(멱등: 같은 ID·같은 페이로드 → duplicate) |
| | `POST /device/baseline-data` · `GET /seniors/{id}/baseline` | 기준선 수집/조회 |
| | `POST /device/fall-events` | 낙상 의심(트랜잭션으로 알림·Outbox 동시 저장) |
| | `POST /device/daily-reports` | 파이프라인 리포트 upsert |
| | `POST /device/heartbeat` | 기기 생존 + 파이프라인 상태(HEALTHY 등) 저장 |
| | `POST /device/video-clips` | 클립 메타데이터(PENDING) |
| 시연 | `POST /demo/simulate` · `POST /demo/reset` · `GET /demo/config` | `APP_ENV=production` 에서 자동 비활성 |
| 시스템 | `GET /health` | 상태·버전·DB 확인 |

전체 스펙과 오류 규칙은 [`docs/api-specification.md`](docs/api-specification.md).

---

## 5. 자세·동작 분석 파이프라인

### 규칙 (PoC v1)

| 이벤트 | 판정 근거 | 기본 임계값 |
|---|---|---|
| 낙상 | 골반 높이 급하강 속도 + 몸통 기울기 + 낮은 자세 유지 | 하강 ≥ 0.30/s, 기울기 ≥ 50°, 유지 ≥ 0.6s, 신뢰도 ≥ 0.55 |
| 장시간 무활동 | 주요 관절 이동량이 임계 이하로 지속 | 기본 240분(`INACTIVITY_MINUTES`) |
| 배회 | 몸통 중심 좌우 이동 반전 횟수 + 경과 시간 | 6회 이상 · 5분 이상 |

좌표는 MediaPipe Pose의 **정규화 이미지 좌표**이며 미터 단위가 아닙니다. 카메라 설치 높이·화각에 따라 현장 보정이 필요합니다(`docs/pipeline.md`).

### 실행

```bash
cd camera-analysis
python scripts/generate_samples.py                  # 샘플 재생성(이미 포함됨)
python -m onview.cli list
python -m onview.cli analyze --scenario fall        # 분석만
python -m onview.cli demo --server http://localhost:8000 \
       --device-token demo-edge-token-homeonq-0001  # 분석 → 실제 API 전송
python -m onview.cli mediapipe-check --image 사진.jpg  # MediaPipe 관절 추출 확인
python -m onview.cli serve --source 0               # 웹캠 상시 분석(개발용)
```

### Gemini 리포트

`GEMINI_API_KEY` 가 있으면 Gemini REST API(`gemini-2.0-flash` 기본)로 문장을 만들고, **키가 없거나 호출이 실패하면 한국어 규칙 기반 생성기로 자동 폴백**합니다. SDK 설치 없이 `httpx` 만 사용합니다.

```bash
export GEMINI_API_KEY=...        # 선택
export GEMINI_MODEL=gemini-2.0-flash
```

리포트에는 `source`(`pipeline-gemini` / `pipeline-rule`)와 `model_name` 이 함께 저장되어, 어느 경로로 생성됐는지 앱·DB에서 확인할 수 있습니다.

---

## 6. Expo 앱 (선택)

```bash
cd mobile-app
npm install
EXPO_PUBLIC_API_URL=http://localhost:8000 npm start   # 웹: w, Expo Go: QR
```

- 휴대폰 Expo Go에서는 `http://<PC LAN IP>:8000` 으로 지정합니다.
- 서버가 없으면 **데모 데이터로 자동 폴백**합니다.
- 화면: 로그인 → 리포트(점수·AI 리포트·요약·낙상 알림) / 이벤트(필터·상세·확인/오탐) / 설정(프로필 수정·기기·서버 상태)
- 정적 검증: `node scripts/mobile_app_check.mjs` (JSX 문법·import·의존성)

웹앱(`api-server/webapp`)이 같은 기능을 브라우저에서 제공하므로, **시연은 웹앱 링크 하나로 충분**합니다. Expo 앱은 현장 설치·배포 단계에서 이어 쓰는 경로입니다.

---

## 7. 검증 결과

| 항목 | 명령 | 결과 |
|---|---|---|
| 백엔드 API/모델 | `cd api-server && pytest` | **23 passed** |
| 파이프라인 | `cd camera-analysis && pytest` | **33 passed** |
| E2E (분석→HTTP→DB→조회) | `python scripts/e2e_demo.py` | **20/20 통과** |
| Render 배포 점검 (`APP_ENV=demo`) | `python scripts/render_smoke.py` | **15/15 통과** |
| 웹앱 런타임(jsdom) | `node scripts/webapp_smoke.test.mjs` | **20/20 통과** |
| Expo 정적 검증 | `node scripts/mobile_app_check.mjs` | **8/8 통과** |
| 마이그레이션 | `alembic upgrade head` / `downgrade -1` / `upgrade head` | SQLite에서 정상 |

전체를 한 번에: `./scripts/verify_all.sh`

E2E 스크립트는 임시 SQLite에 마이그레이션·시드를 적용하고 **실제 uvicorn 서버를 띄워** 파이프라인이 HTTP로 이벤트를 전송한 뒤, 보호자 API 응답과 DB 행 수를 확인하고 서버를 종료합니다. (상시 데몬을 남기지 않습니다.)

`scripts/render_smoke.py` 는 render.yaml의 시작 명령을 그대로 재현합니다: 부트스트랩 2회(슬립/재배포 멱등성) → `uvicorn --host 0.0.0.0 --port $PORT` → 웹앱·헬스·`/demo/config`·로그인·`/demo/simulate`(낙상)·알림·리포트·`/demo/reset` 확인.

---

## 8. 무료 배포: Render (링크 하나로 휴대폰에서 열기)

저장소 루트의 [`render.yaml`](render.yaml) 하나로 Render 무료 웹 서비스 설정이 끝납니다.

| 항목 | 값 |
|---|---|
| 서비스 이름 | `HOMEONQ` |
| 런타임 · 플랜 | Python 3.12 · **Free**(0.1 CPU / 512MB) · 싱가포르 |
| 빌드 | `cd api-server && pip install -r requirements.txt` |
| 시작 | `cd api-server && python scripts/dev_bootstrap.py && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| 환경변수 | `APP_ENV=demo`, `DATABASE_URL=sqlite:///./homeonq_dev.db`, `AUTO_CREATE_SCHEMA=true`, `JWT_SECRET`(Render가 자동 생성), `CORS_ORIGINS=["*"]` |
| 헬스체크 | `/api/v1/health` |

`APP_ENV=demo` 이므로 `production` 전용 차단(404)에 걸리지 않아 **웹앱의 `분석 테스트` 탭과 `/api/v1/demo/*` 가 그대로 동작**합니다.

### 배포 3단계

1. <https://render.com> 가입 → GitHub 계정 연결 (GitHub App 설치에서 `HomeOnView/HomeOnQ` 접근 허용)
2. Dashboard → **New → Blueprint** → 저장소 `HomeOnView/HomeOnQ`, 브랜치 **`app-demo`** 선택
3. **Apply** → 첫 배포 3~5분 → `https://homeonq.onrender.com` (이미 사용 중인 이름이면 뒤에 임의 문자열이 붙습니다)

> 저장소 이름을 `HOMEONQ`로 바꾸면 위 경로도 `HomeOnView/HOMEONQ` 가 됩니다(GitHub이 이전 리포 URL을 리다이렉트). 변경은 GitHub → Settings → Repository name 에서 직접 해야 합니다.
> GitHub Pages(`https://homeonview.github.io/HomeOnQ/`, `main`의 `index.html`)를 함께 쓰고 있다면, 이름 변경 후 Pages 주소가 `.../HOMEONQ/` 로 바뀌므로 공유 링크를 새 주소로 바꿔 주세요.

> Render가 서비스 이름에 소문자만 허용한다고 안내하면 `render.yaml`의 `name`을 `homeonq`로 바꿔 다시 Apply 하세요. 화면 표기는 HOMEONQ 그대로입니다.

### 무료 플랜에서 알아둘 점 (Render 문서 기준)

- **15분 무접속 시 슬립**: 다음 접속에서 약 1분 뒤 화면이 뜹니다. 링크(URL)는 그대로 살아 있습니다.
- **휘발성 파일시스템**: SQLite는 재시작·재배포·슬립 때 사라집니다. 대신 기동할 때마다 `dev_bootstrap.py`가 마이그레이션과 데모 데이터를 **멱등하게** 다시 만들어 항상 같은 초기 상태(70점·주의)로 돌아옵니다.
- **월 750 인스턴스 시간** 한도(서비스 1개 = 최대 744시간). 슬립 중에는 차감되지 않습니다.
- 늘 깨어 있게 하려면 UptimeRobot 같은 무료 모니터로 10분 간격 `GET /api/v1/health` 핑을 걸면 됩니다.
- 첫 접속 지연이 싫으면 유료 플랜(Starter 이상)으로 올리면 슬립이 없어집니다.

---

## 9. 실서비스로 옮길 때

1. **DB**: `DATABASE_URL=postgresql+psycopg://...` 로 바꾸고 `alembic upgrade head`. `APP_ENV=production`, `AUTO_CREATE_SCHEMA=false`.
2. **보안**: `JWT_SECRET`(32자 이상), `CORS_ORIGINS`를 실제 도메인으로 제한, HTTPS 뒤에 배치. 데모 API(`/demo/*`)는 production에서 자동 404.
3. **카메라**: Tapo C225의 RTSP 주소를 `CAMERA_SOURCE`에 넣고 `python -m onview.cli serve` 를 상시 실행(별도 미니PC/라즈베리파이 권장). 실시간 영상은 WebRTC/RTSP 프록시가 추가로 필요합니다.
4. **알림 전달**: 현재 `/guardians/me/alerts` 폴링(20초) 방식입니다. FCM/APNs 푸시는 Outbox 워커와 함께 붙이는 다음 단계입니다. (`outbox_messages` 테이블과 트랜잭션은 이미 준비됨)
5. **배포 링크**: 위 8장의 Render 무료 배포로 웹앱·API가 같은 링크에서 열립니다. 상시 운영은 PostgreSQL + 유료 플랜으로 옮기고, 데모 API(`/demo/*`)는 `APP_ENV=production` 으로 두면 자동 404가 됩니다.

---

## 10. 이번 범위에서 하지 않은 것

- 상시 클라우드 운영(서버·DB 프로비저닝), 도메인/HTTPS 설정
- 실제 카메라 영상 수집·녹화·클립 업로드(GCS), WebRTC 실시간 영상
- FCM/APNs 푸시, Outbox 재전송 워커
- 스토어 배포(EAS Build/심사), 계정 찾기·소셜 로그인
- 점수·낙상 임계값의 임상 검증

이 항목들은 시연에는 영향이 없고, 위 8장 순서로 이어가면 됩니다.
