/* 홈온큐 보호자 안심 리포트 — 시연용 모바일 웹앱
 * 같은 서버의 /api/v1 을 그대로 사용한다. 서버가 없으면 데모 데이터로 표시한다.
 */
(function () {
  'use strict';

  const API = '/api/v1';
  const LS_TOKEN = 'homeonq.token';
  const LS_EMAIL = 'homeonq.email';
  const SOS_NUMBER = '01000000000';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const pad = (n) => String(n).padStart(2, '0');

  const TZ = 'Asia/Seoul';
  const STATUS_LABEL = {
    ANALYZED: '분석 완료', RECEIVED: '수신됨', SUSPECTED: '의심', CONFIRMED: '확인됨',
    DISMISSED: '오탐', SENT: '전송됨', PENDING: '대기', FINAL: '확정',
    DATA_INSUFFICIENT: '데이터 부족', UNKNOWN: '확인 필요',
  };
  const RISK_LABEL = { HIGH: '높음', MEDIUM: '보통', LOW: '낮음', UNKNOWN: '미확인' };
  const ACTIVITY_ICON = {
    WALKING: '🚶', STEPS: '🚶', NIGHT_ACTIVITY: '🌙', TOILET_VISIT: '🚻',
    BEDROOM_STAY: '🛏', INACTIVE: '⏳', WANDERING: '↔️', POSTURE: '🧍',
  };

  const state = {
    token: null,
    guardian: null,
    senior: null,
    report: null,
    events: [],
    alerts: [],
    summary: null,
    health: null,
    view: 'home',
    filter: 'all',
    demo: false,
    demoConfig: null,
    simRunning: false,
    lastAlertKey: null,
    pollTimer: null,
  };

  /* -------------------------------------------------- API */
  class ApiError extends Error {
    constructor(status, detail) {
      super(typeof detail === 'string' ? detail : '요청을 처리하지 못했습니다.');
      this.status = status;
      this.detail = detail;
    }
  }

  async function request(path, options) {
    const opts = options || {};
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), opts.timeout || 15000);
    const headers = { 'Content-Type': 'application/json' };
    if (opts.auth !== false && state.token) headers.Authorization = 'Bearer ' + state.token;
    try {
      const res = await fetch(API + path, {
        method: opts.method || 'GET',
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal: controller.signal,
      });
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
      if (!res.ok) {
        const detail = data && data.detail ? data.detail : data;
        if (res.status === 401 && opts.auth !== false) {
          // 토큰 만료 → 로그인 화면으로
          clearSession();
        }
        throw new ApiError(res.status, detail);
      }
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  const api = {
    demoConfig: () => request('/demo/config', { auth: false }),
    login: (email, password) => request('/auth/login', { method: 'POST', auth: false, body: { email, password } }),
    health: () => request('/health', { auth: false }),
    seniors: () => request('/guardians/me/seniors'),
    senior: (id) => request('/seniors/' + id),
    patchSenior: (id, body) => request('/seniors/' + id, { method: 'PATCH', body }),
    latestReport: (id) => request('/seniors/' + id + '/daily-reports/latest'),
    events: (id, days) => request('/seniors/' + id + '/events?days=' + (days || 7)),
    summary: (id) => request('/seniors/' + id + '/summary'),
    alerts: () => request('/guardians/me/alerts'),
    testFall: (id) => request('/seniors/' + id + '/test-fall', { method: 'POST' }),
    patchFall: (id, eventId, status) => request('/seniors/' + id + '/fall-events/' + encodeURIComponent(eventId), { method: 'PATCH', body: { status } }),
    acknowledge: (notificationId) => request('/guardians/me/notifications/' + notificationId + '/acknowledge', { method: 'POST' }),
    simulate: (scenario, seniorId) => request('/demo/simulate', { method: 'POST', body: { scenario, senior_id: seniorId }, timeout: 60000 }),
    reset: () => request('/demo/reset', { method: 'POST', timeout: 30000 }),
  };

  /* -------------------------------------------------- 데모 폴백 데이터 */
  const DEMO = {
    senior: {
      id: 'demo-senior',
      display_name: '강O순 어르신',
      birth_date: '1951-03-12',
      age: 75,
      gender: '여성',
      height_cm: 160,
      weight_kg: 52,
      medical_conditions: ['당뇨', '고혈압', '척추측만증'],
      photo_url: '',
      emergency_contact: '010-0000-0000',
      memo: '분당 자택 거실 카메라(Tapo C225)로 관찰 중',
      devices: [{ device_id: 'TAPO-C225-LIVING', status: 'active', health_status: 'HEALTHY' }],
    },
    report: {
      report_date: new Date().toISOString().slice(0, 10),
      score: 70,
      risk_level: 'WATCH',
      risk_label: '주의',
      ui_color: '#A84D08',
      headline: '강O순 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다',
      narrative:
        '11월 21일 강O순 어르신의 하루를 정리했습니다.\n\n오늘은 걸음 수 3,215걸음, 야간 활동 55분, 화장실 이용 8회, 침실 체류 480분이 확인되었습니다.\n\n평소와 비교해 주의할 점이 있습니다. 평소보다 22% 적게 걸었습니다, 야간 활동이 55분 감지되었습니다, 5.0시간 동안 움직임이 적었습니다. 다음 날 활동이 이어지는지 함께 살펴봐 주세요.\n\n이 리포트는 카메라 관절 좌표 분석을 바탕으로 만든 참고 자료이며, 진단을 대신하지 않습니다.',
      summary: {
        rows: [
          { key: 'steps', label: '보행', value: 3215, unit: '걸음', delta_percent: -22 },
          { key: 'night_activity', label: '야간 활동', value: 55, unit: '분' },
          { key: 'toilet', label: '화장실 이용', value: 8, unit: '회' },
          { key: 'bedroom', label: '침실 체류', value: 480, unit: '분' },
        ],
      },
      factors: { items: [] },
      source: 'demo-data',
      data_status: 'FINAL',
      generated_at: new Date().toISOString(),
    },
    events: [
      { kind: 'behavior', id: 'd1', title: '보행', value: 3215, unit: '걸음', occurred_at: new Date(Date.now() - 3 * 3600e3).toISOString(), status: 'ANALYZED', detail: '오전 산책과 집 안 이동' },
      { kind: 'behavior', id: 'd2', title: '야간 활동', value: 55, unit: '분', occurred_at: new Date(Date.now() - 9 * 3600e3).toISOString(), status: 'ANALYZED', detail: '새벽 화장실 이동 포함' },
      { kind: 'behavior', id: 'd3', title: '화장실 이용', value: 8, unit: '회', occurred_at: new Date(Date.now() - 6 * 3600e3).toISOString(), status: 'ANALYZED', detail: '하루 화장실 이용 8회' },
      { kind: 'fall', id: 'd4', event_id: 'demo-past-fall-001', title: '낙상 의심', occurred_at: new Date(Date.now() - 2 * 86400e3).toISOString(), status: 'CONFIRMED', confidence: 0.81, risk_level: 'MEDIUM', detail: '거실에서 앉은 자세로 낮아진 뒤 20초간 움직임이 없었습니다.' },
    ],
    alerts: [],
  };

  /* -------------------------------------------------- 세션 */
  function saveSession(token, email) {
    state.token = token;
    try {
      localStorage.setItem(LS_TOKEN, token);
      if (email) localStorage.setItem(LS_EMAIL, email);
    } catch (e) { /* 사생활 보호 모드 등 */ }
  }
  function clearSession() {
    state.token = null;
    state.guardian = null;
    try { localStorage.removeItem(LS_TOKEN); } catch (e) { /* noop */ }
  }
  function savedToken() {
    try { return localStorage.getItem(LS_TOKEN); } catch (e) { return null; }
  }

  /* -------------------------------------------------- UI helpers */
  function toast(message, kind) {
    const node = $('#toast');
    node.textContent = message;
    node.className = 'toast show' + (kind === 'error' ? ' error' : '');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { node.className = 'toast'; }, 2600);
  }

  function openModal(html, opts) {
    const root = $('#modal-root');
    root.innerHTML = '<div class="modal-backdrop"></div>' + html;
    root.classList.add('open');
    const backdrop = $('.modal-backdrop', root);
    const close = () => closeModal();
    backdrop.addEventListener('click', close);
    $$('[data-close]', root).forEach((b) => b.addEventListener('click', close));
    if (opts && opts.onMount) opts.onMount(root);
    return root;
  }
  function closeModal() {
    const root = $('#modal-root');
    root.classList.remove('open');
    root.innerHTML = '';
  }

  function parseDate(iso) {
    if (!iso) return null;
    let text = String(iso);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += 'T00:00:00+09:00';
    else if (!/(Z|[+-]\d{2}:?\d{2})$/.test(text)) text += 'Z'; // 오프셋 없는 값은 서버 규칙상 UTC
    const d = new Date(text);
    return isNaN(d) ? null : d;
  }
  function fmtDate(iso) {
    const d = parseDate(iso);
    if (!d) return '-';
    return d.toLocaleDateString('ko-KR', { timeZone: TZ, month: 'long', day: 'numeric' });
  }
  function fmtDateTime(iso) {
    const d = parseDate(iso);
    if (!d) return '-';
    const todayKst = new Date().toLocaleDateString('en-CA', { timeZone: TZ });
    const dayKst = d.toLocaleDateString('en-CA', { timeZone: TZ });
    const time = d.toLocaleTimeString('ko-KR', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false });
    return (sameDay(dayKst, todayKst) ? '오늘 ' : fmtDate(iso) + ' ') + time;
  }
  function sameDay(a, b) { return a === b; }
  function relTime(iso) {
    const d = parseDate(iso);
    if (!d) return '';
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 0) return '방금 전';
    if (diff < 60) return '방금 전';
    if (diff < 3600) return Math.round(diff / 60) + '분 전';
    if (diff < 86400) return Math.round(diff / 3600) + '시간 전';
    return Math.round(diff / 86400) + '일 전';
  }
  function fmtNumber(v) {
    if (v == null) return '-';
    return Number(v).toLocaleString('ko-KR');
  }
  function ageGender(s) {
    const parts = [];
    if (s.age) parts.push(s.age + '세');
    else if (s.birth_date) parts.push(new Date(s.birth_date).getFullYear() + '년생');
    if (s.gender) parts.push(s.gender);
    return parts.join('·');
  }
  function riskStyle(level) {
    return {
      SAFE: { color: '#1E7B4C', bg: '#E6F2EC', label: '안심' },
      WATCH: { color: '#A84D08', bg: '#FDF0E2', label: '주의' },
      ALERT: { color: '#B42318', bg: '#FDECEA', label: '경계' },
      UNKNOWN: { color: '#566079', bg: '#EFF2F7', label: '확인 필요' },
    }[level] || { color: '#566079', bg: '#EFF2F7', label: '확인 필요' };
  }

  /* -------------------------------------------------- 렌더 */
  function activeSenior() { return state.senior || DEMO.senior; }
  function activeReport() {
    if (state.report && state.report.report_date) return state.report;
    return state.demo ? DEMO.report : null;
  }

  function renderProfile() {
    const s = activeSenior();
    const tags = (s.medical_conditions || []).map((t) => '<span class="tag warn">' + esc(t) + '</span>').join('');
    const photo = s.photo_url
      ? '<img class="avatar" alt="" src="' + esc(s.photo_url) + '" onerror="this.outerHTML=\'<div class=&quot;avatar-fallback&quot;>' + esc((s.display_name || '?').replace(/ .*/, '').slice(0, 1)) + '</div>\'" />'
      : '<div class="avatar-fallback">' + esc((s.display_name || '?').replace(/ .*/, '').slice(0, 1)) + '</div>';
    const detailBits = [];
    if (s.height_cm) detailBits.push(s.height_cm + 'cm');
    if (s.weight_kg) detailBits.push(s.weight_kg + 'kg');
    $('#profile-card').innerHTML =
      '<div class="profile-top">' + photo +
        '<div class="profile-main">' +
          '<div class="profile-name-row"><span class="profile-name">' + esc(s.display_name) + '</span></div>' +
          '<div class="profile-meta">' + esc(ageGender(s)) + (detailBits.length ? '  |  ' + esc(detailBits.join('  |  ')) : '') + '</div>' +
          '<div class="tag-row">' + tags + '</div>' +
        '</div>' +
        '<div class="profile-actions"><button class="link-btn" id="btn-edit-profile" type="button">수정</button></div>' +
      '</div>' +
      (s.memo ? '<div class="profile-meta" style="margin-top:-2px">' + esc(s.memo) + '</div>' : '');
    const edit = $('#btn-edit-profile');
    if (edit) edit.addEventListener('click', openProfileEdit);
  }

  function renderScore() {
    const r = activeReport();
    const card = $('#score-card');
    if (!r || r.score == null) {
      card.innerHTML = '<div class="score-side"><div class="score-title">오늘의 안심 점수</div>' +
        '<div class="report-empty" style="margin-top:6px">카메라 분석이 시작되면 점수가 표시됩니다.</div></div>';
      return;
    }
    const style = riskStyle(r.risk_level);
    const pct = Math.max(0, Math.min(100, r.score));
    const circumference = 2 * Math.PI * 44;
    const offset = circumference * (1 - pct / 100);
    const factors = ((r.factors && r.factors.items) || []).slice(0, 3)
      .map((f) => '<li>' + esc(f.detail || f.label) + '</li>').join('');
    card.innerHTML =
      '<div class="gauge">' +
        '<svg width="104" height="104" viewBox="0 0 104 104">' +
          '<circle class="gauge-track" cx="52" cy="52" r="44" fill="none" stroke-width="9"></circle>' +
          '<circle class="gauge-fill" cx="52" cy="52" r="44" fill="none" stroke-width="9" stroke="' + style.color + '" ' +
            'stroke-dasharray="' + circumference.toFixed(1) + '" stroke-dashoffset="' + circumference.toFixed(1) + '"></circle>' +
        '</svg>' +
        '<div class="gauge-center"><span class="gauge-score" id="gauge-number">0<small>/100</small></span><span class="gauge-caption">안심 점수</span></div>' +
      '</div>' +
      '<div class="score-side">' +
        '<div class="score-title">오늘의 안심 점수 (위험도 분석)</div>' +
        '<span class="risk-badge" style="color:' + style.color + ';background:' + style.bg + '"><i></i>' + esc(r.risk_label || style.label) + ' 단계</span>' +
        (factors ? '<ul class="risk-factors">' + factors + '</ul>' : '<ul class="risk-factors"><li>평소와 비슷한 하루였습니다</li></ul>') +
        '<div class="score-updated">' + (r.generated_at ? relTime(r.generated_at) + ' 갱신' : '') + ' · 참고용 지표</div>' +
      '</div>';
    const fill = $('.gauge-fill', card);
    const num = $('#gauge-number', card);
    requestAnimationFrame(() => { fill.style.strokeDashoffset = String(offset); });
    let current = 0;
    const step = Math.max(1, Math.round(pct / 24));
    const tick = () => {
      current = Math.min(pct, current + step);
      if (num) num.innerHTML = current + '<small>/100</small>';
      if (current < pct) setTimeout(tick, 24);
    };
    setTimeout(tick, 120);
  }

  function renderReport() {
    const r = activeReport();
    const card = $('#report-card');
    if (!r) {
      card.innerHTML = '<div class="report-head"><div class="report-eyebrow"><span class="spark">✦</span> AI 안심 리포트</div></div>' +
        '<p class="report-empty">아직 오늘의 리포트가 도착하지 않았습니다. 분석이 시작되면 이곳에 하루가 정리됩니다.</p>';
      return;
    }
    const sourceLabel = { 'pipeline-gemini': 'Gemini 생성', 'pipeline-rule': '규칙 기반', 'demo-data': '데모', 'demo-seed': '시연 데이터' }[r.source] || (r.source || '');
    const narrative = r.narrative || '';
    const long = narrative.length > 260;
    card.innerHTML =
      '<div class="report-head">' +
        '<div class="report-eyebrow"><span class="spark">✦</span> AI 안심 리포트</div>' +
        (sourceLabel ? '<span class="report-source">' + esc(sourceLabel) + (r.model_name ? ' · ' + esc(r.model_name) : '') + '</span>' : '') +
      '</div>' +
      '<h3 class="report-headline">' + esc(r.headline || '오늘의 리포트') + '</h3>' +
      '<p class="report-body' + (long ? ' clamped' : '') + '" id="report-body">' + esc(narrative) + '</p>' +
      (long ? '<button class="link-btn report-more" id="report-more" type="button">전체 읽기</button>' : '');
    const more = $('#report-more');
    if (more) more.addEventListener('click', () => {
      const body = $('#report-body');
      body.classList.toggle('clamped');
      more.textContent = body.classList.contains('clamped') ? '전체 읽기' : '접기';
    });
  }

  const ICONS = { steps: '🚶', night_activity: '🌙', toilet: '🚻', bedroom: '🛏', inactivity: '⏳', wandering: '↔️' };

  function renderSummary() {
    const r = activeReport();
    const rows = (r && r.summary && r.summary.rows) || [];
    const card = $('#summary-card');
    if (!rows.length) {
      card.innerHTML = '<div class="card-title"><h3>주요 이벤트 요약</h3></div><div class="report-empty">오늘 집계된 활동이 아직 없습니다.</div>';
      return;
    }
    card.innerHTML =
      '<div class="card-title"><h3>주요 이벤트 요약</h3><span>' + fmtDate(r.report_date) + ' 기준</span></div>' +
      rows.map((row) => {
        let delta = '';
        if (row.delta_percent != null) {
          const cls = row.delta_percent < 0 ? 'down' : row.delta_percent > 0 ? 'up' : 'flat';
          const sign = row.delta_percent > 0 ? '+' : '';
          delta = '<span class="summary-delta ' + cls + '">' + sign + row.delta_percent + '%</span>';
        }
        return '<div class="summary-row">' +
          '<span class="summary-label"><span class="summary-icon">' + (ICONS[row.key] || '•') + '</span>' + esc(row.label) + '</span>' +
          '<span class="summary-value">' + esc(fmtNumber(row.value)) + esc(row.unit || '') + delta + '</span>' +
        '</div>';
      }).join('');
  }

  function renderHomeAlert() {
    const card = $('#home-alert-card');
    const alert = (state.alerts || [])[0];
    if (!alert || state.demo) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    card.innerHTML =
      '<h3>⚠️ 확인하지 않은 알림</h3>' +
      '<p><b>' + esc(alert.senior_name) + '</b> · 낙상 의심 · ' + esc(fmtDateTime(alert.occurred_at)) + '</p>' +
      '<div class="alert-actions">' +
        '<button class="btn tiny danger" id="alert-open" type="button">내용 보기</button>' +
        '<button class="btn tiny ghost" id="alert-ack" type="button">확인 처리</button>' +
      '</div>';
    $('#alert-open').addEventListener('click', () => openFallAlert(alert));
    $('#alert-ack').addEventListener('click', () => acknowledgeAlert(alert));
  }

  function filteredEvents() {
    if (state.demo) return DEMO.events.filter((e) => state.filter === 'all' || e.kind === state.filter);
    return (state.events || []).filter((e) => state.filter === 'all' || e.kind === state.filter);
  }

  function renderEvents() {
    const list = $('#event-list');
    const events = filteredEvents();
    if (!events.length) {
      list.innerHTML = '<div class="empty-state"><span class="big">🌿</span>이 기간에는 특별한 이벤트가 없습니다.<br/>분석 테스트에서 낙상·무활동을 실행해 보세요.</div>';
      return;
    }
    list.innerHTML = events.map((e, idx) => {
      const isFall = e.kind === 'fall';
      const conf = e.confidence != null ? '신뢰도 ' + Math.round(e.confidence * 100) + '%' : '';
      const statusPill = isFall
        ? { SUSPECTED: '<span class="pill red">의심</span>', CONFIRMED: '<span class="pill green">확인됨</span>', DISMISSED: '<span class="pill">오탐</span>' }[e.status] || ''
        : '<span class="pill">' + esc(STATUS_LABEL[e.status] || e.status || '') + '</span>';
      const value = (!isFall && e.value != null) ? fmtNumber(e.value) + esc(e.unit || '') : '';
      return '<button class="event-item" data-idx="' + idx + '" type="button">' +
        '<span class="event-icon ' + (isFall ? 'fall' : 'behavior') + '">' + (isFall ? '⚠️' : (ACTIVITY_ICON[e.activity_type] || '•')) + '</span>' +
        '<span class="event-body">' +
          '<span class="event-title">' + esc(e.title || e.event_type) + (e.is_test ? '<span class="pill">테스트</span>' : '') + statusPill + '</span>' +
          '<span class="event-desc">' + esc(e.detail || (value ? value + ' 감지' : '')) + '</span>' +
          '<span class="event-meta"><span>' + esc(fmtDateTime(e.occurred_at)) + '</span>' + (conf ? '<span>' + conf + '</span>' : '') + (value ? '<span>' + value + '</span>' : '') + '</span>' +
        '</span>' +
      '</button>';
    }).join('');
    $$('.event-item', list).forEach((btn) => {
      btn.addEventListener('click', () => {
        const e = filteredEvents()[Number(btn.dataset.idx)];
        openEventDetail(e);
      });
    });
  }

  function openEventDetail(e) {
    if (!e) return;
    const isFall = e.kind === 'fall';
    const statusText = e.status === 'DISMISSED' ? '오탐 처리' : (STATUS_LABEL[e.status] || e.status || '-');
    const cells = isFall
      ? '<div class="detail-cell"><span>발생 시각</span><b>' + esc(fmtDateTime(e.occurred_at)) + '</b></div>' +
        '<div class="detail-cell"><span>신뢰도</span><b>' + (e.confidence != null ? Math.round(e.confidence * 100) + '%' : '-') + '</b></div>' +
        '<div class="detail-cell"><span>위험도</span><b>' + esc(RISK_LABEL[e.risk_level] || e.risk_level || '-') + '</b></div>' +
        '<div class="detail-cell"><span>처리 상태</span><b>' + esc(statusText) + '</b></div>'
      : '<div class="detail-cell"><span>발생 시각</span><b>' + esc(fmtDateTime(e.occurred_at)) + '</b></div>' +
        '<div class="detail-cell"><span>측정값</span><b>' + esc(fmtNumber(e.value)) + esc(e.unit || '') + '</b></div>' +
        '<div class="detail-cell"><span>분석 상태</span><b>' + esc(STATUS_LABEL[e.status] || e.status || '-') + '</b></div>' +
        '<div class="detail-cell"><span>신뢰도</span><b>' + (e.confidence != null ? Math.round(e.confidence * 100) + '%' : '-') + '</b></div>';
    const actions = isFall && !state.demo
      ? '<div class="sheet-actions">' +
          '<button class="btn ghost" data-close type="button">닫기</button>' +
          '<button class="btn navy" id="fall-dismiss" type="button">오탐 처리</button>' +
          '<button class="btn primary" id="fall-confirm" type="button">확인 완료</button>' +
        '</div>'
      : '<div class="sheet-actions"><button class="btn ghost block" data-close type="button">닫기</button></div>';
    openModal(
      '<div class="sheet" role="dialog" aria-modal="true">' +
        '<div class="sheet-handle"></div>' +
        (e.is_test ? '<span class="test-chip">테스트 알림</span>' : '') +
        '<h2>' + esc(e.title || e.event_type) + '</h2>' +
        '<p class="sheet-sub">' + esc(isFall ? '카메라 관절 분석에서 감지된 낙상 의심 이벤트입니다.' : '일일 활동 분석에서 집계된 이벤트입니다.') + '</p>' +
        '<div class="detail-grid">' + cells + '</div>' +
        '<div class="detail-reason">' + esc(e.detail || '상세 설명이 없습니다.') + '</div>' +
        actions +
      '</div>', {
        onMount(root) {
          const confirm = $('#fall-confirm', root);
          const dismiss = $('#fall-dismiss', root);
          if (confirm) confirm.addEventListener('click', () => updateFallStatus(e, 'CONFIRMED'));
          if (dismiss) dismiss.addEventListener('click', () => updateFallStatus(e, 'DISMISSED'));
        },
      }
    );
  }

  async function updateFallStatus(e, status) {
    try {
      await api.patchFall(activeSenior().id, e.event_id, status);
      toast(status === 'CONFIRMED' ? '확인 완료로 표시했습니다.' : '오탐으로 처리했습니다.');
      closeModal();
      await loadData();
      renderAll();
    } catch (err) {
      toast(err.message || '상태를 바꾸지 못했습니다.', 'error');
    }
  }

  function renderSettings() {
    const s = activeSenior();
    const account = $('#settings-account');
    const devices = (state.senior && state.senior.devices) || (state.demo ? DEMO.senior.devices : []);
    const health = state.health;
    account.innerHTML =
      '<div class="card-title"><h3>계정</h3></div>' +
      '<div class="setting-row"><span>보호자</span><b>' + esc(state.guardian ? state.guardian.email : '데모 모드') + '</b></div>' +
      '<div class="setting-row"><span>어르신</span><b>' + esc(s.display_name) + '</b><span class="muted">' + esc(s.id.slice(0, 8)) + '</span></div>' +
      '<div class="setting-row"><span>응급 연락처</span><b>' + esc(s.emergency_contact || '-') + '</b></div>';
    $('#settings-devices').innerHTML =
      '<div class="card-title"><h3>카메라 · 기기</h3><span>' + devices.length + '대</span></div>' +
      (devices.length
        ? devices.map((d) => '<div class="setting-row"><span>' + esc(d.device_id) + '<br/><span class="muted">' + esc(d.health_status || d.status || '-') + (d.last_seen_at ? ' · ' + esc(relTime(d.last_seen_at)) : '') + '</span></span><span class="status-chip ' + (d.status === 'active' ? '' : 'warn') + '">' + esc(d.status === 'active' ? '정상' : d.status) + '</span></div>').join('')
        : '<div class="setting-row"><span>등록된 카메라가 없습니다</span></div>');
    $('#settings-server').innerHTML =
      '<div class="card-title"><h3>서버 · 버전</h3></div>' +
      '<div class="setting-row"><span>API</span><b>' + esc(location.origin + '/api/v1') + '</b></div>' +
      '<div class="setting-row"><span>상태</span><b>' + esc(health ? health.status + ' · ' + health.environment : (state.demo ? '오프라인(데모)' : '-')) + '</b></div>' +
      '<div class="setting-row"><span>버전</span><b>' + esc(health ? health.version : '0.3.0') + '</b></div>' +
      '<div class="setting-row"><span>DB</span><b>' + esc(health ? health.database : '-') + '</b></div>' +
      '<div class="setting-row"><span>데모 계정</span><span class="muted">' + esc(state.demoConfig ? state.demoConfig.credentials.email : 'demo@homeonq.kr') + '</span></div>';
    $('#app-version').textContent = 'v' + (health ? health.version : '0.3.0');
  }

  function renderScenarios() {
    const grid = $('#scenario-grid');
    if (grid.dataset.ready) return;
    const items = [
      { key: 'normal', emoji: '🚶', title: '정상 보행', desc: '10초 보행 클립 · 특이 이벤트 없음' },
      { key: 'fall', emoji: '⚠️', title: '낙상 발생', desc: '걷다가 넘어져 바닥에 누운 상황' },
      { key: 'inactive', emoji: '⏳', title: '장시간 무활동', desc: '소파에서 4시간 이상 정지' },
      { key: 'wandering', emoji: '🌙', title: '야간 배회', desc: '밤에 좌우로 반복 이동' },
    ];
    grid.innerHTML = items.map((it) =>
      '<button class="scenario" data-scenario="' + it.key + '" type="button">' +
        '<span class="emoji">' + it.emoji + '</span>' +
        '<strong>' + it.title + '</strong>' +
        '<span>' + it.desc + '</span>' +
      '</button>').join('');
    grid.dataset.ready = '1';
    $$('.scenario', grid).forEach((btn) => btn.addEventListener('click', () => runScenario(btn.dataset.scenario, btn)));
  }

  function renderAll() {
    renderProfile();
    renderScore();
    renderReport();
    renderSummary();
    renderHomeAlert();
    renderEvents();
    renderSettings();
    renderScenarios();
    $('#home-date').textContent = fmtDate((activeReport() || {}).report_date || new Date().toISOString());
    $('#home-greeting').textContent = state.demo ? '오늘의 안심 리포트 (데모)' : '오늘의 안심 리포트';
    $('#offline-banner').classList.toggle('hidden', !state.demo);
  }

  /* -------------------------------------------------- 화면 전환 */
  function showScreen(view) {
    state.view = view;
    ['login', 'home', 'events', 'sim', 'settings'].forEach((name) => {
      const node = $('#screen-' + name);
      if (node) node.classList.toggle('hidden', name !== view);
    });
    const loggedIn = view !== 'login';
    $('#tabbar').classList.toggle('hidden', !loggedIn);
    // 로그인 전에는 보호자용 액션(낙상 테스트·새로고침·연결 배지)을 숨긴다.
    ['#btn-test-fall', '#btn-refresh', '#conn-badge'].forEach((sel) => {
      const node = $(sel);
      if (node) node.style.display = loggedIn ? '' : 'none';
    });
    $$('#tabbar button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
    $('#main').scrollTop = 0;
    if (view === 'sim') renderScenarios();
  }

  /* -------------------------------------------------- 데이터 로드 */
  async function loadData() {
    const seniors = await api.seniors();
    if (!seniors.items || !seniors.items.length) throw new ApiError(404, '연결된 어르신이 없습니다. 서버에서 데모 데이터를 먼저 생성하세요.');
    state.senior = seniors.items[0];
    const sid = state.senior.id;
    const results = await Promise.all([
      api.latestReport(sid).catch(() => null),
      api.events(sid, 7).catch(() => ({ items: [] })),
      api.alerts().catch(() => ({ items: [] })),
      api.summary(sid).catch(() => null),
      api.health().catch(() => null),
    ]);
    state.report = results[0];
    state.events = (results[1] && results[1].items) || [];
    state.alerts = (results[2] && results[2].items) || [];
    state.summary = results[3];
    state.health = results[4];
    setConnection(true);
  }

  function setConnection(online) {
    const badge = $('#conn-badge');
    badge.className = 'conn-badge ' + (online ? 'online' : 'offline');
    $('span', badge).textContent = online ? '연결됨' : '데모';
    $('#offline-banner').classList.toggle('hidden', online && !state.demo);
  }

  async function refreshAll() {
    if (state.demo) { renderAll(); return; }
    try {
      await loadData();
      renderAll();
      toast('최신 상태로 갱신했습니다.');
    } catch (err) {
      toast(err.message || '새로고침에 실패했습니다.', 'error');
    }
  }

  /* -------------------------------------------------- 로그인 */
  async function doLogin(email, password) {
    const btn = $('#login-submit');
    btn.disabled = true;
    btn.textContent = '로그인 중…';
    try {
      const tokens = await api.login(email, password);
      saveSession(tokens.access_token, email);
      state.demo = false;
      state.guardian = await request('/auth/me').catch(() => ({ email }));
      await loadData();
      showScreen('home');
      renderAll();
      startPolling();
      toast('로그인되었습니다. 오늘의 리포트를 확인하세요.');
    } catch (err) {
      if (err instanceof ApiError) {
        const message = err.status >= 500
          ? '서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'
          : (err.status === 401 || err.status === 403)
            ? '이메일 또는 비밀번호가 맞지 않습니다.'
            : '로그인에 실패했습니다.';
        toast(message, 'error');
      } else {
        // 네트워크 실패 → 데모 모드
        enterDemoMode('서버에 연결할 수 없어 데모 데이터로 시작합니다.');
      }
    } finally {
      btn.disabled = false;
      btn.textContent = '로그인';
    }
  }

  function enterDemoMode(message) {
    state.demo = true;
    state.guardian = { email: 'demo@homeonq.kr' };
    state.senior = DEMO.senior;
    state.report = DEMO.report;
    state.events = [];
    state.alerts = [];
    setConnection(false);
    showScreen('home');
    renderAll();
    if (message) toast(message);
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(async () => {
      if (state.demo || !state.token) return;
      try {
        const res = await api.alerts();
        const items = (res && res.items) || [];
        const newest = items[0];
        state.alerts = items;
        renderHomeAlert();
        if (newest) {
          const key = newest.notification_id;
          if (key && key !== state.lastAlertKey) {
            state.lastAlertKey = key;
            openFallAlert(newest);
            await loadData();
            renderAll();
          }
        }
      } catch (e) { /* 폴링 실패는 조용히 무시 */ }
    }, 20000);
  }
  function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  /* -------------------------------------------------- 낙상 알림 */
  function openFallAlert(alert) {
    if (!alert) return;
    state.lastAlertKey = alert.notification_id || state.lastAlertKey;
    openModal(
      '<div class="sheet fall-sheet" role="alertdialog" aria-modal="true">' +
        '<div class="sheet-handle"></div>' +
        '<div class="fall-visual">⚠️</div>' +
        (alert.is_test ? '<span class="test-chip">테스트 알림</span>' : '') +
        '<h2>낙상 비상 상황 발생</h2>' +
        '<div class="fall-name">' + esc(alert.senior_name || activeSenior().display_name) + '</div>' +
        '<div class="fall-detail">' +
          '<b>' + esc(fmtDateTime(alert.occurred_at)) + '</b> · 신뢰도 ' + Math.round((alert.confidence || 0) * 100) + '%<br/>' +
          esc(alert.reasoning || '카메라 관절 분석에서 낙상이 의심되는 자세 변화가 감지되었습니다.') +
        '</div>' +
        '<div class="fall-meta"><span>위험도 ' + esc(RISK_LABEL[alert.risk_level] || alert.risk_level || '-') + '</span><span>상태 ' + esc(STATUS_LABEL[alert.status] || '의심') + '</span></div>' +
        '<div class="sheet-actions">' +
          '<a class="btn ghost" href="tel:' + SOS_NUMBER + '">SOS 전화</a>' +
          '<button class="btn primary" id="fall-ack" type="button">확인했습니다</button>' +
        '</div>' +
        '<div class="sheet-actions"><button class="btn ghost block" data-close type="button">나중에</button></div>' +
      '</div>', {
        onMount(root) {
          $('#fall-ack', root).addEventListener('click', () => acknowledgeAlert(alert));
        },
      }
    );
  }

  async function acknowledgeAlert(alert) {
    if (state.demo) { closeModal(); toast('데모 모드에서는 저장되지 않습니다.'); return; }
    try {
      await api.acknowledge(alert.notification_id);
      closeModal();
      toast('알림을 확인 처리했습니다.');
      await loadData();
      renderAll();
    } catch (err) {
      toast(err.message || '확인 처리에 실패했습니다.', 'error');
    }
  }

  /* -------------------------------------------------- 프로필 수정 */
  function openProfileEdit() {
    const s = activeSenior();
    const conditions = (s.medical_conditions || []).join(', ');
    openModal(
      '<div class="sheet" role="dialog" aria-modal="true">' +
        '<div class="sheet-handle"></div>' +
        '<h2>어르신 프로필 수정</h2>' +
        '<p class="sheet-sub">수정한 내용은 서버에 저장되고 리포트 카드에 바로 반영됩니다.</p>' +
        '<form id="profile-form" class="form-grid">' +
          '<label class="field span2"><span>성함</span><input name="display_name" value="' + esc(s.display_name || '') + '" required /></label>' +
          '<label class="field"><span>생년월일</span><input name="birth_date" type="date" value="' + esc(s.birth_date || '') + '" /></label>' +
          '<label class="field"><span>성별</span><select name="gender">' +
            ['여성', '남성', '기타', '미입력'].map((g) => '<option ' + (s.gender === g ? 'selected' : '') + '>' + g + '</option>').join('') +
          '</select></label>' +
          '<label class="field"><span>키 (cm)</span><input name="height_cm" type="number" step="0.1" value="' + esc(s.height_cm || '') + '" /></label>' +
          '<label class="field"><span>체중 (kg)</span><input name="weight_kg" type="number" step="0.1" value="' + esc(s.weight_kg || '') + '" /></label>' +
          '<label class="field span2"><span>병력/질환 (쉼표로 구분)</span><input name="medical_conditions" value="' + esc(conditions) + '" /></label>' +
          '<label class="field span2"><span>응급 연락처</span><input name="emergency_contact" value="' + esc(s.emergency_contact || '') + '" /></label>' +
          '<label class="field span2"><span>프로필 사진 URL</span><input name="photo_url" value="' + esc(s.photo_url || '') + '" placeholder="https://" /></label>' +
          '<label class="field span2"><span>메모</span><textarea name="memo" rows="2">' + esc(s.memo || '') + '</textarea></label>' +
        '</form>' +
        '<div class="sheet-actions">' +
          '<button class="btn ghost" data-close type="button">취소</button>' +
          '<button class="btn primary" id="profile-save" type="button">저장하기</button>' +
        '</div>' +
      '</div>', {
        onMount(root) {
          $('#profile-save', root).addEventListener('click', () => saveProfile(root));
        },
      }
    );
  }

  async function saveProfile(root) {
    const form = $('#profile-form', root);
    const data = new FormData(form);
    const body = {};
    const text = (k) => (data.get(k) || '').toString().trim();
    if (text('display_name')) body.display_name = text('display_name');
    if (text('birth_date')) body.birth_date = text('birth_date');
    if (text('gender')) body.gender = text('gender');
    if (text('height_cm')) body.height_cm = Number(text('height_cm'));
    if (text('weight_kg')) body.weight_kg = Number(text('weight_kg'));
    body.medical_conditions = text('medical_conditions') ? text('medical_conditions').split(',').map((x) => x.trim()).filter(Boolean) : [];
    body.emergency_contact = text('emergency_contact') || null;
    body.photo_url = text('photo_url') || null;
    body.memo = text('memo') || null;

    if (state.demo) {
      Object.assign(DEMO.senior, body);
      state.senior = DEMO.senior;
      closeModal();
      renderAll();
      toast('데모 모드에서 화면에만 반영했습니다.');
      return;
    }
    try {
      const updated = await api.patchSenior(activeSenior().id, body);
      state.senior = updated;
      closeModal();
      renderAll();
      toast('프로필을 저장했습니다.');
    } catch (err) {
      toast(err.message || '저장에 실패했습니다.', 'error');
    }
  }

  /* -------------------------------------------------- 시뮬레이션 */
  const STEP_LABELS = [
    '샘플 관절좌표(33관절) 로드',
    '자세·동작 분석 (낙상/무활동/배회)',
    '텔레메트리 API 전송',
    '리포트·알림 화면 갱신',
  ];

  function simStepsHtml(activeIndex, doneCount) {
    return '<ul class="sim-steps">' + STEP_LABELS.map((label, i) => {
      const cls = i < doneCount ? 'done' : i === activeIndex ? 'running' : '';
      const bullet = i < doneCount ? '✓' : String(i + 1);
      return '<li class="' + cls + '"><span class="bullet">' + bullet + '</span>' + esc(label) + '</li>';
    }).join('') + '</ul>';
  }

  async function runScenario(key, btn) {
    if (state.simRunning) return;
    state.simRunning = true;
    $$('.scenario').forEach((b) => { b.disabled = true; });
    $$('.scenario').forEach((b) => b.classList.toggle('selected', b === btn));
    const resultCard = $('#sim-result');
    resultCard.classList.remove('hidden');
    resultCard.innerHTML = '<div class="card-title"><h3>분석 실행 중…</h3></div>' + simStepsHtml(0, 0);

    const started = Date.now();
    try {
      resultCard.innerHTML = '<div class="card-title"><h3>분석 실행 중…</h3></div>' + simStepsHtml(0, 0);
      await sleep(320);
      resultCard.innerHTML = '<div class="card-title"><h3>분석 실행 중…</h3></div>' + simStepsHtml(1, 1);

      if (state.demo) {
        await sleep(600);
        resultCard.innerHTML = '<div class="card-title"><h3>데모 모드</h3></div>' +
          '<div class="report-empty">서버에 연결되면 이 버튼이 실제 파이프라인을 실행합니다.<br/>지금은 화면 시연만 가능합니다.</div>';
        return;
      }

      const res = await api.simulate(key, activeSenior().id);
      resultCard.innerHTML = '<div class="card-title"><h3>분석 완료</h3><span>' + ((Date.now() - started) / 1000).toFixed(1) + '초</span></div>' +
        simStepsHtml(4, 4);
      const analysis = res.analysis || {};
      const events = analysis.events || [];
      const score = analysis.score || {};
      const sent = res.sent || {};
      const style = riskStyle(score.risk_level);
      const eventLines = events.length
        ? events.map((e) => '<li>' + esc(({ fall: '낙상 의심', inactivity: '장시간 무활동', wandering: '배회' }[e.kind] || e.kind)) +
            ' · 신뢰도 ' + Math.round((e.confidence || 0) * 100) + '%<br/><span style="color:#8b98b1">' + esc(e.reasoning) + '</span></li>').join('')
        : '<li>특이 이벤트가 감지되지 않았습니다.</li>';
      resultCard.insertAdjacentHTML('beforeend',
        '<div class="sim-outcome">' +
          '<div><b>' + esc(analysis.label || key) + '</b> · 분석 구간 ' + (analysis.duration_s || 0) + '초</div>' +
          '<div style="margin-top:6px"><b>탐지 이벤트</b><ul style="margin:6px 0 0;padding-left:18px;line-height:1.6">' + eventLines + '</ul></div>' +
          '<div style="margin-top:8px">전송 결과 · 행동 <b>' + (sent.behavior || 0) + '건</b>, 낙상 <b>' + (sent.fall || 0) + '건</b>, 리포트 <b>' + (sent.report || 0) + '건</b></div>' +
          '<div style="margin-top:6px">오늘 안심 점수 <b style="color:' + style.color + '">' + (score.score != null ? score.score + '점 · ' + score.risk_label : '-') + '</b></div>' +
          (sent.errors && sent.errors.length ? '<div style="margin-top:8px;color:#B42318">전송 오류: ' + esc(sent.errors.join(' / ')) + '</div>' : '') +
        '</div>');
      await loadData();
      renderAll();
      toast(analysis.label + ' 시나리오가 저장되었습니다.');
      if ((state.alerts || []).length) {
        setTimeout(() => openFallAlert(state.alerts[0]), 500);
      }
    } catch (err) {
      resultCard.innerHTML = '<div class="card-title"><h3>실행 실패</h3></div>' +
        '<div class="report-empty">' + esc(err.message || '시뮬레이션을 실행하지 못했습니다.') + '</div>';
      toast(err.message || '시뮬레이션 실패', 'error');
    } finally {
      state.simRunning = false;
      $$('.scenario').forEach((b) => { b.disabled = false; });
    }
  }

  async function resetDemo() {
    if (state.demo) { enterDemoMode('데모 모드입니다. 서버 연결 후 초기화할 수 있습니다.'); return; }
    if (!confirm('데모 활동·낙상·리포트 데이터를 초기 상태로 되돌릴까요?')) return;
    try {
      await api.reset();
      await loadData();
      renderAll();
      toast('데모 데이터를 초기화했습니다.');
    } catch (err) {
      toast(err.message || '초기화에 실패했습니다.', 'error');
    }
  }

  /* -------------------------------------------------- 낙상 테스트 */
  async function runTestFall() {
    if (state.demo) { toast('서버 연결 후 사용할 수 있습니다.', 'error'); return; }
    const btn = $('#btn-test-fall');
    btn.disabled = true;
    try {
      const res = await api.testFall(activeSenior().id);
      await loadData();
      renderAll();
      toast('낙상 테스트 알림을 생성했습니다.');
      if (state.alerts && state.alerts.length) openFallAlert(state.alerts[0]);
      else toast('알림을 찾지 못했습니다. 새로고침 해보세요.', 'error');
      return res;
    } catch (err) {
      toast(err.message || '테스트 알림 생성에 실패했습니다.', 'error');
    } finally {
      btn.disabled = false;
    }
  }

  /* -------------------------------------------------- 초기화 */
  function bindEvents() {
    $('#login-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      doLogin($('#login-email').value.trim(), $('#login-password').value);
    });
    $('#login-demo').addEventListener('click', () => {
      const cfg = state.demoConfig && state.demoConfig.credentials;
      $('#login-email').value = (cfg && cfg.email) || 'demo@homeonq.kr';
      $('#login-password').value = (cfg && cfg.password) || 'homeonq-demo-2026';
      doLogin($('#login-email').value, $('#login-password').value);
    });
    $$('#tabbar button').forEach((b) => b.addEventListener('click', () => showScreen(b.dataset.view)));
    $$('#event-filter button').forEach((b) => b.addEventListener('click', () => {
      state.filter = b.dataset.kind;
      $$('#event-filter button').forEach((x) => x.classList.toggle('active', x === b));
      renderEvents();
    }));
    $('#btn-refresh').addEventListener('click', refreshAll);
    $('#btn-test-fall').addEventListener('click', runTestFall);
    $('#btn-demo-reset').addEventListener('click', resetDemo);
    $('#btn-logout').addEventListener('click', async () => {
      try { await request('/auth/logout', { method: 'POST', body: {} }); } catch (e) { /* noop */ }
      stopPolling();
      clearSession();
      state.demo = false;
      state.report = null;
      state.events = [];
      state.alerts = [];
      showScreen('login');
      toast('로그아웃했습니다.');
    });
    $('#btn-live').addEventListener('click', () => {
      const dev = (state.senior && state.senior.devices && state.senior.devices[0]) || { device_id: 'TAPO-C225-LIVING' };
      openModal('<div class="sheet" role="dialog" aria-modal="true"><div class="sheet-handle"></div>' +
        '<h2>실시간 영상</h2>' +
        '<p class="sheet-sub">Tapo C225 스트림은 RTSP 주소와 계정 정보가 필요합니다. 이 시연 웹앱에서는 실시간 영상 대신 기기 상태를 보여드립니다.</p>' +
        '<div class="detail-grid">' +
          '<div class="detail-cell"><span>카메라</span><b>' + esc(dev.device_id) + '</b></div>' +
          '<div class="detail-cell"><span>상태</span><b>' + esc(dev.health_status || dev.status || 'active') + '</b></div>' +
          '<div class="detail-cell"><span>마지막 통신</span><b>' + esc(dev.last_seen_at ? relTime(dev.last_seen_at) : '-') + '</b></div>' +
          '<div class="detail-cell"><span>분석</span><b>33관절 좌표</b></div>' +
        '</div>' +
        '<div class="sim-note">실서비스에서는 <b>RTSP → MediaPipe → 텔레메트리</b> 파이프라인이 상시 동작하고, 앱에서는 WebRTC/RTSP 프록시로 영상을 봅니다. 지금은 카메라 없는 환경에서 분석·알림 흐름을 검증하는 단계입니다.</div>' +
        '<div class="sheet-actions"><button class="btn ghost block" data-close type="button">닫기</button></div></div>');
    });
  }

  function tickClock() {
    const now = new Date();
    $('#clock').textContent = pad(now.getHours()) + ':' + pad(now.getMinutes());
  }

  async function boot() {
    bindEvents();
    tickClock();
    setInterval(tickClock, 30000);
    try {
      state.demoConfig = await api.demoConfig();
      const cred = state.demoConfig.credentials || {};
      $('#login-email').value = cred.email || 'demo@homeonq.kr';
      $('#login-password').value = cred.password || 'homeonq-demo-2026';
      $('#login-hint').textContent = '시연용 계정 ' + (cred.email || 'demo@homeonq.kr') + ' · 로그인 후 바로 확인할 수 있습니다.';
    } catch (e) {
      $('#login-hint').textContent = '서버에 연결되지 않아 데모 데이터로 볼 수 있습니다.';
    }

    const token = savedToken();
    if (token) {
      state.token = token;
      try {
        state.guardian = await request('/auth/me');
        await loadData();
        showScreen('home');
        renderAll();
        startPolling();
        return;
      } catch (err) {
        clearSession();
      }
    }
    showScreen('login');
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
