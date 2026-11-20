/* 웹앱 런타임 스모크 테스트 (jsdom)
 * 실제 index.html + app.js를 로드하고 fetch만 스텁으로 바꿔
 * 로그인 → 리포트 렌더 → 이벤트 탭 → 시뮬레이션 실행까지 확인한다.
 *
 *   node scripts/webapp_smoke.test.mjs
 * (jsdom이 설치되어 있어야 함: npm i jsdom)
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM, VirtualConsole } from 'jsdom';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEBAPP = path.resolve(__dirname, '../api-server/webapp');
const appJs = fs.readFileSync(path.join(WEBAPP, 'app.js'), 'utf8');
// jsdom은 외부 <script src>를 자동으로 불러오지 않으므로 인라인으로 주입한다.
const html = fs.readFileSync(path.join(WEBAPP, 'index.html'), 'utf8')
  // 주의: String.replace의 두 번째 인자에서 $$는 리터럴 $로 해석되므로 함수형 치환을 쓴다.
  .replace('<script src="./app.js"></script>', () => '<script>' + appJs + '</script>');

const senior = {
  id: 'senior-1', display_name: '강O순 어르신', birth_date: '1951-03-12', age: 75, gender: '여성',
  height_cm: 160, weight_kg: 52, medical_conditions: ['당뇨', '고혈압', '척추측만증'],
  photo_url: '', emergency_contact: '010-0000-0000', memo: '거실 카메라',
  devices: [{ device_id: 'TAPO-C225-LIVING', status: 'active', health_status: 'HEALTHY' }],
};
const report = {
  report_date: '2026-11-21', score: 70, risk_level: 'WATCH', risk_label: '주의', ui_color: '#A84D08',
  headline: '강O순 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다',
  narrative: '오늘은 걸음 수 3,215걸음, 야간 활동 55분이 확인되었습니다.\n\n이 리포트는 참고 자료입니다.',
  summary: { rows: [
    { key: 'steps', label: '보행', value: 3215, unit: '걸음', delta_percent: -22 },
    { key: 'night_activity', label: '야간 활동', value: 55, unit: '분' },
    { key: 'toilet', label: '화장실 이용', value: 8, unit: '회' },
    { key: 'bedroom', label: '침실 체류', value: 480, unit: '분' },
  ] },
  factors: { items: [{ label: '보행량 감소', detail: '평소보다 22% 적게 걸었습니다', delta: -8 }] },
  source: 'pipeline-rule', model_name: null, data_status: 'FINAL', generated_at: new Date().toISOString(),
};
const events = { items: [
  { kind: 'fall', event_id: 'sim-1', title: '낙상 의심', occurred_at: new Date().toISOString(), status: 'SUSPECTED', confidence: 0.85, risk_level: 'HIGH', detail: '급격한 자세 변화' },
  { kind: 'behavior', id: 'b1', title: '보행', value: 3215, unit: '걸음', occurred_at: new Date().toISOString(), status: 'ANALYZED', detail: '산책' },
] };
const alerts = { items: [{
  notification_id: 'note-1', alert_type: 'FALL_SUSPECTED', event_id: 'sim-1', senior_id: senior.id,
  senior_name: senior.display_name, occurred_at: new Date().toISOString(), confidence: 0.85,
  risk_level: 'HIGH', status: 'SUSPECTED', is_test: false, reasoning: '급격한 자세 변화',
}] };
const simulate = {
  scenario: 'fall', senior_id: senior.id, device_id: 'DEMO-EDGE-01',
  analysis: {
    label: '낙상 발생', duration_s: 9,
    events: [{ kind: 'fall', event_type: 'FALL', confidence: 0.85, reasoning: '골반 높이가 급격히 낮아졌습니다.' }],
    score: { score: 45, risk_level: 'ALERT', risk_label: '경계' },
  },
  sent: { behavior: 5, fall: 1, report: 1, errors: [] },
  report: { report_date: '2026-11-21', score: 45, risk_label: '경계' },
};

const calls = [];
function jsonResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(data), json: async () => data };
}

function route(url, options) {
  const method = (options && options.method) || 'GET';
  calls.push(method + ' ' + url);
  if (url.endsWith('/api/v1/demo/config')) return jsonResponse({ enabled: true, credentials: { email: 'demo@homeonq.kr', password: 'homeonq-demo-2026', senior_name: senior.display_name }, scenarios: ['normal', 'fall'] });
  if (url.endsWith('/api/v1/auth/login')) return jsonResponse({ access_token: 'test-token', refresh_token: 'r', expires_in: 900 });
  if (url.endsWith('/api/v1/auth/me')) return jsonResponse({ id: 'g1', email: 'demo@homeonq.kr', is_active: true });
  if (url.includes('/guardians/me/seniors')) return jsonResponse({ items: [senior] });
  if (url.includes('/daily-reports/latest')) return jsonResponse(report);
  if (url.includes('/events?')) return jsonResponse(events);
  if (url.endsWith('/guardians/me/alerts')) return jsonResponse(alerts);
  if (url.includes('/summary')) return jsonResponse({ fall_count: 1, latest_report: report });
  if (url.endsWith('/api/v1/health')) return jsonResponse({ status: 'ok', environment: 'development', version: '0.3.0', database: 'ok', webapp: true });
  if (url.endsWith('/demo/simulate')) return jsonResponse(simulate);
  if (url.includes('/notifications/') && url.endsWith('/acknowledge')) return jsonResponse({ id: 'note-1', acknowledged_at: new Date().toISOString() });
  if (url.includes('/daily-reports')) return jsonResponse(report);
  return jsonResponse({ detail: 'not stubbed ' + url }, 404);
}

const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', (e) => errors.push('jsdomError: ' + e.message));
virtualConsole.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

const dom = new JSDOM(html, {
  url: 'http://localhost:8000/',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  virtualConsole,
  beforeParse(window) {
    window.fetch = async (url, options) => route(String(url), options);
    window.confirm = () => true;
  },
});

const { window } = dom;
const doc = window.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(ok, name, detail = '') {
  results.push({ ok, name, detail });
  console.log((ok ? '  ✅ ' : '  ❌ ') + name + (detail ? ' — ' + detail : ''));
}

async function main() {
  await wait(120);
  // 로그인 화면
  check(!doc.querySelector('#screen-login').classList.contains('hidden'), '로그인 화면 표시');
  check(doc.querySelector('#login-email').value === 'demo@homeonq.kr', '데모 계정 자동 입력');

  // 로그인 실행
  doc.querySelector('#login-submit').click();
  await wait(400);
  check(!doc.querySelector('#screen-home').classList.contains('hidden'), '로그인 후 리포트 화면');
  check(doc.querySelector('#profile-card').textContent.includes('강O순'), '프로필 카드 렌더');
  check(doc.querySelector('#report-card').textContent.includes('살펴봐'), 'AI 리포트 문장 렌더');
  check(doc.querySelectorAll('#summary-card .summary-row').length === 4, '주요 이벤트 요약 4행');
  check(doc.querySelectorAll('#event-list .event-item').length === 2, '이벤트 목록 렌더');
  check(doc.querySelector('#home-alert-card').textContent.includes('낙상'), '미확인 알림 카드');
  check(doc.querySelector('#conn-badge').textContent.includes('연결됨'), '연결 상태 배지');

  // 점수 애니메이션 종료 대기
  await wait(900);
  const gauge = doc.querySelector('#gauge-number');
  check(!!gauge && gauge.textContent.startsWith('70'), '안심 점수 표시', gauge ? gauge.textContent : 'none');

  // 낙상 알림 모달 열기
  doc.querySelector('#alert-open').click();
  await wait(120);
  check(doc.querySelector('.fall-sheet') !== null, '낙상 알림 모달');
  doc.querySelector('.modal-backdrop').click();

  // 이벤트 탭 + 필터
  doc.querySelector('#tabbar button[data-view="events"]').click();
  await wait(80);
  check(!doc.querySelector('#screen-events').classList.contains('hidden'), '이벤트 탭 전환');
  doc.querySelector('#event-filter button[data-kind="fall"]').click();
  await wait(60);
  check(doc.querySelectorAll('#event-list .event-item').length === 1, '낙상 필터 적용');
  doc.querySelector('#event-list .event-item').click();
  await wait(80);
  check(doc.querySelector('.sheet h2') !== null && doc.querySelector('.detail-grid') !== null, '이벤트 상세 시트');
  doc.querySelector('.modal-backdrop').click();

  // 시뮬레이션
  doc.querySelector('#tabbar button[data-view="sim"]').click();
  await wait(80);
  check(doc.querySelectorAll('.scenario').length === 4, '시나리오 4종 표시');
  doc.querySelector('.scenario[data-scenario="fall"]').click();
  await wait(1600);
  const result = doc.querySelector('#sim-result').textContent;
  check(result.includes('분석 완료'), '시뮬레이션 실행 완료');
  check(result.includes('45점') || result.includes('경계'), '시뮬레이션 점수 반영', result.slice(0, 60).replace(/\s+/g, ' '));
  check(calls.some((c) => c.includes('POST /api/v1/demo/simulate')), '실제 API 호출 발생');

  // 설정
  doc.querySelector('#tabbar button[data-view="settings"]').click();
  await wait(80);
  check(doc.querySelector('#settings-server').textContent.includes('0.3.0'), '설정에 서버 버전 표시');

  check(errors.length === 0, '런타임 오류 없음', errors.slice(0, 2).join(' | '));

  const passed = results.filter((r) => r.ok).length;
  console.log(`\n결과: ${passed}/${results.length} 통과`);
  process.exitCode = passed === results.length ? 0 : 1;
  window.close();
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
