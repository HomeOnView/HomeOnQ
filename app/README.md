# HOMEONQ 테스트 웹앱 (GitHub Pages 정적 배포)

- 주소: <https://homeonview.github.io/HomeOnQ/app/>
- 기존 소개 랜딩페이지(`/index.html`)는 건드리지 않고, `app/` 폴더만 정적 웹앱으로 배포한다.
- 아이폰 Safari에서 열고 **공유 → 홈 화면에 추가**를 하면 브라우저 바 없이 앱처럼 실행된다.

## 폴더 구성

| 파일 | 역할 |
| --- | --- |
| `index.html` | 앱 화면(로그인·리포트 홈·이벤트·분석 테스트·설정) + 아이폰 홈 화면 추가용 메타 |
| `styles.css` | 모바일 화면 비율 UI 스타일 |
| `app.js` | 화면 렌더링·이벤트 처리. API 호출은 `request()` 한 곳을 거친다 |
| `demo-engine.js` | **브라우저 내장 데모 엔진** — 서버 없이 `/api/v1` 응답을 재현 |
| `manifest.json`, `icon-*.png` | 홈 화면 아이콘·앱 이름 |

## 동작 방식

1. 실제 FastAPI 서버(로컬 `uvicorn`, Render)에서 열면 `app.js`가 그대로 `/api/v1` 실제 API를 쓴다.
2. `github.io` 같은 정적 호스팅이거나, API가 JSON 대신 HTML 404를 돌려주거나, 네트워크가 끊기면
   자동으로 `demo-engine.js`로 전환한다. 사용자가 따로 설정할 것은 없다.
3. 데모 엔진은 서버 규약을 그대로 흉내 낸다.
   - 로그인: `demo@homeonq.kr` / `homeonq-demo-2026` (자동 입력됨)
   - 리포트 홈: 초기 **70점 · 주의**, 행동/낙상/안심지수 카드
   - 분석 테스트: 정상 / 낙상 / 장시간 무활동 / 야간 배회 → 점수·알림·리포트가 즉시 갱신
   - 알림·SOS: 데모 전화번호 `010-0000-0000`
   - 설정: 프로필 수정, 데모 초기화
4. 상태는 브라우저 `localStorage`(`homeonq.demo.state.v1`)에 남는다. 새로고침해도 유지되고,
   **분석 테스트 → 데모 초기화**로 처음 상태로 되돌린다.

## 수치의 근거

`demo-engine.js`는 서버·엣지 파이프라인의 규칙을 그대로 옮긴 것이다.

- 점수 산식: `api-server/app/services/scoring.py` (동일 입력 → 동일 점수)
- 리포트 문장: `report_text.compose_narrative`(시드) / `camera-analysis/onview/report_generator.py`(분석 결과)
- 시나리오 지표·검출 신뢰도: `camera-analysis/samples/*.json`을 실제 파이프라인에 통과시킨 결과

| 시나리오 | 점수 | 단계 | 전송 건수(행동/낙상) |
| --- | --- | --- | --- |
| 정상 보행 | 92 | 안심 | 5 / 0 |
| 낙상 발생 | 45 | 경계 | 5 / 1 |
| 장시간 무활동 | 73 | 주의 | 5 / 0 |
| 야간 배회 | 62 | 주의 | 6 / 0 |

## 원본과의 관계

원본 웹앱은 `app-demo` 브랜치의 `api-server/webapp/`에 있다(서버와 함께 배포되는 버전).
`app/`은 그 화면·스타일에 데모 엔진을 붙인 **정적 배포용 사본**이다.

`app-demo`의 웹앱을 수정했다면 `index.html`·`styles.css`를 이 폴더로 복사하고,
`app.js`는 `request()` 데모 라우팅 부분(`state.useDemo`, `demoEngine`)을 유지한 채 반영한다.
