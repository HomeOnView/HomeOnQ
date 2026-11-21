/* HOMEONQ 보호자 안심 리포트 — 시연용 모바일 웹앱
 *
 * · 같은 서버(FastAPI)에서 열면 /api/v1 실제 API를 쓴다.
 * · GitHub Pages 같은 정적 호스팅에서는 backend가 없으므로, demo-engine.js의
 *   브라우저 내장 데모 엔진으로 자동 전환해 모든 화면·버튼이 실제처럼 동작한다.
 *   (실서버가 응답하지 않아도 같은 폴백이 걸린다.)
 */
(function () {
  'use strict';

  const API = '/api/v1';
  const LS_TOKEN = 'homeonq.token';
  const LS_EMAIL = 'homeonq.email';
  const SOS_NUMBER = '01000000000';
  /* 등록된 어르신 프로필 사진(저해상도·픽셀 처리) — 설정 탭 아바타·홈 프로필 공용 */
  const DEFAULT_PHOTO = './assets/senior-profile.jpg';

  /* 내장 데모 엔진 (정적 배포용) */
  const DEMO = window.HOMEONQ_DEMO || null;
  const demoEngine = (function () {
    if (!DEMO) return null;
    try { return DEMO.createEngine({}); } catch (e) { return null; }
  })();
  const STATIC_HOST = (function () {
    const host = (location.hostname || '').toLowerCase();
    if (location.protocol === 'file:') return true;
    return /(^|\.)(github\.io|githubusercontent\.com|gitlab\.io|netlify\.app|vercel\.app|pages\.dev|surge\.sh)$/.test(host);
  })();

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
    useDemo: !!(demoEngine && STATIC_HOST),
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

  async function httpRequest(path, options) {
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
        const error = new ApiError(res.status, detail);
        // 정적 호스팅(404 HTML 등)은 백엔드가 없다는 신호 → 데모 엔진으로 전환
        error.nonJson = typeof data === 'string' && /^\s*</.test(data);
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timer);
    }
  }

  function isStaticBackendFailure(err) {
    if (!(err instanceof ApiError)) return err instanceof TypeError; // fetch 자체 실패(오프라인)
    if (err.nonJson) return true;
    return err.status === 405 || err.status === 501 || err.status === 502 || err.status === 503;
  }

  /* 모든 API 호출의 단일 통로: 실제 서버 → 없으면 내장 데모 엔진 */
  async function request(path, options) {
    if (state.useDemo && demoEngine) {
      try {
        return await demoEngine.request(path, Object.assign({}, options, { token: state.token }));
      } catch (err) {
        if (err && err.isDemoApiError) throw new ApiError(err.status, err.detail);
        throw err;
      }
    }
    try {
      return await httpRequest(path, options);
    } catch (err) {
      if (demoEngine && isStaticBackendFailure(err)) {
        state.useDemo = true;
        setConnection(false);
        return request(path, options);
      }
      throw err;
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

  /* 로그인 화면에서 쓰는 표시용 기본값(데이터는 서버 또는 내장 데모 엔진에서 온다) */
  const PLACEHOLDER_SENIOR = {
    id: 'demo-senior',
    display_name: '강O순 어르신',
    birth_date: '1951-03-12',
    age: 75,
    gender: '여성',
    height_cm: 160,
    weight_kg: 52,
    medical_conditions: [],
    photo_url: '',
    emergency_contact: '010-0000-0000',
    memo: '',
    devices: [],
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
    alarmStopAll(); // 알람 시연 중이었다면 경보음·타이머를 반드시 멈춘다
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
  function activeSenior() { return state.senior || PLACEHOLDER_SENIOR; }
  function activeReport() {
    const r = state.report;
    return r && r.report_date && r.score !== null && r.score !== undefined ? r : null;
  }

  function renderProfile() {
    const s = activeSenior();
    const tags = (s.medical_conditions || []).map((t) => '<span class="tag warn">' + esc(t) + '</span>').join('');
    const photo = '<img class="avatar" alt="" src="' + esc(photoSrc(s)) + '" onerror="this.outerHTML=\'<div class=&quot;avatar-fallback&quot;>' + esc((s.display_name || '?').replace(/ .*/, '').slice(0, 1)) + '</div>\'" />';
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

  function photoSrc(s) {
    const url = s && s.photo_url ? String(s.photo_url).trim() : '';
    return url || DEFAULT_PHOTO;
  }

  function shortName(name) {
    return String(name || '').replace(/\s*어르신\s*$/, '') || '어르신';
  }

  /* 이벤트 탭 하단 — 최근 상태·핵심 포인트 2~3줄 요약 */
  function renderEventSummary() {
    const card = $('#event-summary-card');
    if (!card) return;
    const r = activeReport();
    const s = activeSenior();
    const rows = (r && r.summary && r.summary.rows) || [];
    const fallEvents = (state.events || []).filter((e) => e.kind === 'fall');
    const factors = ((r && r.factors && r.factors.items) || []).filter((f) => f && (f.detail || f.label));
    const lines = [];

    if (r && r.score != null) {
      const style = riskStyle(r.risk_level);
      lines.push(
        '<p class="es-line es-head">' +
          '<span class="es-badge" style="color:' + style.color + ';background:' + style.bg + '">' + esc(r.risk_label || style.label) + '</span>' +
          '<b>' + esc(r.score) + '점</b>' +
          '<span class="es-sub">오늘 안심 점수</span>' +
        '</p>'
      );
    } else {
      lines.push('<p class="es-line es-head"><span class="es-sub">오늘 안심 점수</span><b>-</b></p>');
    }

    if (rows.length) {
      lines.push('<p class="es-line">' + rows.slice(0, 3).map((row) =>
        '<span class="es-chip">' + (ICONS[row.key] || '•') + ' ' + esc(row.label) + ' <b>' + esc(fmtNumber(row.value)) + esc(row.unit || '') + '</b></span>'
      ).join('') + '</p>');
    } else {
      lines.push('<p class="es-line"><span class="es-chip">오늘 집계된 활동이 아직 없습니다</span></p>');
    }

    if (fallEvents.length) {
      lines.push('<p class="es-line es-warn">⚠️ 최근 7일 낙상 의심 <b>' + fallEvents.length + '건</b> · 최근 ' + esc(relTime(fallEvents[0].occurred_at)) + '</p>');
    } else if (factors.length) {
      lines.push('<p class="es-line es-warn">💡 ' + esc(factors[0].detail || factors[0].label) + '</p>');
    } else {
      lines.push('<p class="es-line es-ok">🌿 최근 7일 낙상 없이 지냈습니다</p>');
    }

    card.innerHTML =
      '<div class="card-title"><h3>' + esc(shortName(s.display_name)) + ' 최근 상태</h3><span>' + (r && r.report_date ? fmtDate(r.report_date) + ' 기준' : '방금') + '</span></div>' +
      lines.join('');
  }

  /* 설정 탭 상단 — 어르신 프로필(등록된 사진) */
  function renderSettingsProfile() {
    const card = $('#settings-profile');
    if (!card) return;
    const s = activeSenior();
    const fallback = esc((s.display_name || '?').replace(/ .*/, '').slice(0, 1));
    card.innerHTML =
      '<div class="profile-hero-top">' +
        '<img class="avatar-round" alt="어르신 프로필 사진" src="' + esc(photoSrc(s)) + '" />' +
        '<div class="profile-hero-main">' +
          '<span class="profile-hero-label">어르신 프로필</span>' +
          '<strong class="profile-hero-name">' + esc(s.display_name) + '</strong>' +
          '<span class="profile-hero-meta">' + esc(ageGender(s) || '정보 없음') + '</span>' +
        '</div>' +
        '<button class="link-btn" id="settings-photo-edit" type="button">수정</button>' +
      '</div>' +
      '<div class="profile-hero-foot">' +
        '<span>🔒 얼굴이 식별되지 않도록 저해상도(픽셀) 처리한 사진입니다</span>' +
      '</div>';
    const edit = $('#settings-photo-edit');
    if (edit) edit.addEventListener('click', openProfileEdit);
    const round = $('.avatar-round', card);
    if (round && round.tagName === 'IMG') {
      round.addEventListener('error', () => {
        round.outerHTML = '<div class="avatar-round avatar-fallback">' + fallback + '</div>';
      }, { once: true });
    }
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
    if (!alert) { card.classList.add('hidden'); return; }
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
    const actions = isFall
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
    const devices = (state.senior && state.senior.devices) || [];
    const health = state.health;
    account.innerHTML =
      '<div class="card-title"><h3>계정</h3></div>' +
      '<div class="setting-row"><span>보호자</span><b>' + esc(state.guardian ? state.guardian.email : '데모 모드') + '</b></div>' +
      '<div class="setting-row"><span>어르신</span><b>' + esc(s.display_name) + '</b><span class="muted">' + esc((s.id || '').slice(0, 8)) + '</span></div>' +
      '<div class="setting-row"><span>응급 연락처</span><b>' + esc(s.emergency_contact || '-') + '</b></div>';
    $('#settings-devices').innerHTML =
      '<div class="card-title"><h3>카메라 · 기기</h3><span>' + devices.length + '대</span></div>' +
      (devices.length
        ? devices.map((d) => '<div class="setting-row"><span>' + esc(d.device_id) + '<br/><span class="muted">' + esc(d.health_status || d.status || '-') + (d.last_seen_at ? ' · ' + esc(relTime(d.last_seen_at)) : '') + '</span></span><span class="status-chip ' + (d.status === 'active' ? '' : 'warn') + '">' + esc(d.status === 'active' ? '정상' : d.status) + '</span></div>').join('')
        : '<div class="setting-row"><span>등록된 카메라가 없습니다</span></div>');
    $('#settings-server').innerHTML =
      '<div class="card-title"><h3>서버 · 버전</h3></div>' +
      '<div class="setting-row"><span>API</span><b>' + esc(state.useDemo ? '브라우저 내장 데모 엔진' : location.origin + '/api/v1') + '</b></div>' +
      '<div class="setting-row"><span>상태</span><b>' + esc(health ? health.status + ' · ' + health.environment : '-') + '</b></div>' +
      '<div class="setting-row"><span>버전</span><b>' + esc(health ? health.version : '0.3.0') + '</b></div>' +
      '<div class="setting-row"><span>DB</span><b>' + esc(health ? (health.database === 'localStorage' ? 'localStorage (브라우저)' : health.database) : '-') + '</b></div>' +
      '<div class="setting-row"><span>데모 계정</span><span class="muted">' + esc(state.demoConfig && state.demoConfig.credentials ? state.demoConfig.credentials.email : 'demo@homeonq.kr') + '</span></div>' +
      '<div class="setting-row"><span>홈 화면 추가</span><span class="muted">Safari 공유 → 홈 화면에 추가</span></div>';
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
    renderSummary();
    renderHomeAlert();
    renderEvents();
    renderEventSummary();
    renderSettings();
    renderSettingsProfile();
    renderScenarios();
    $('#home-date').textContent = fmtDate((activeReport() || {}).report_date || new Date().toISOString());
    $('#home-greeting').textContent = '오늘의 안심 리포트';
    $('#offline-banner').classList.add('hidden');
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
    $('span', badge).textContent = state.useDemo ? '데모 엔진' : (online ? '연결됨' : '오프라인');
  }

  async function refreshAll() {
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
      state.guardian = await request('/auth/me').catch(() => ({ email }));
      await loadData();
      showScreen('home');
      renderAll();
      startPolling();
      toast(state.useDemo ? '데모 엔진으로 로그인했습니다. 모든 화면이 실제처럼 동작합니다.' : '로그인되었습니다. 오늘의 리포트를 확인하세요.');
    } catch (err) {
      if (err instanceof ApiError) {
        const message = err.status >= 500
          ? '서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'
          : (err.status === 401 || err.status === 403)
            ? '이메일 또는 비밀번호가 맞지 않습니다. (데모 계정: demo@homeonq.kr / homeonq-demo-2026)'
            : '로그인에 실패했습니다.';
        toast(message, 'error');
      } else {
        toast('로그인하지 못했습니다. 잠시 후 다시 시도해 주세요.', 'error');
      }
    } finally {
      btn.disabled = false;
      btn.textContent = '로그인';
    }
  }

  function startPolling() {
    stopPolling();
    if (state.useDemo) return; // 내장 데모 엔진은 화면 안에서 바로 갱신된다.
    state.pollTimer = setInterval(async () => {
      if (!state.token) return;
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
        '<p class="sheet-sub">수정한 내용은 저장되고 리포트 카드에 바로 반영됩니다.</p>' +
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

  function durationLabel(sec) {
    const n = Number(sec) || 0;
    if (n < 600) return (Math.round(n * 10) / 10) + '초';
    if (n < 3600) return (Math.round(n / 6) / 10) + '분';
    return (Math.round(n / 360) / 10) + '시간';
  }

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
      await sleep(120);
      resultCard.innerHTML = '<div class="card-title"><h3>분석 실행 중…</h3></div>' + simStepsHtml(2, 2);

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
          '<div><b>' + esc(analysis.label || key) + '</b> · 분석 구간 ' + durationLabel(analysis.duration_s) + '</div>' +
          '<div style="margin-top:6px"><b>탐지 이벤트</b><ul style="margin:6px 0 0;padding-left:18px;line-height:1.6">' + eventLines + '</ul></div>' +
          '<div style="margin-top:8px">' + (state.useDemo ? '저장 결과' : '전송 결과') + ' · 행동 <b>' + (sent.behavior || 0) + '건</b>, 낙상 <b>' + (sent.fall || 0) + '건</b>, 리포트 <b>' + (sent.report || 0) + '건</b></div>' +
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

  /* -------------------------------------------------- 낙상 3단계 에스컬레이션 알람 */
  const ALARM = {
    stage: 0,        // 0 설정 · 1 보호자 알림 · 2 앱 알람 · 3 자동 전화 · 4 종료
    waitSec: 3,
    ringSec: 12,
    left: 0,
    phone: '010-0000-0000',
    calling: false,
    soundOn: true,
    timers: [],
    tick: null,
    siren: null,
    root: null,
  };

  const ALARM_STEPS = [
    { n: 1, title: '보호자 1차 알림', sub: '낙상 3분 무움직임' },
    { n: 2, title: '어르신 앱 알람', sub: '소리·진동 알람' },
    { n: 3, title: '보호자 자동 전화', sub: '원터치 연결' },
  ];

  function alarmStepsHtml(stage) {
    return ALARM_STEPS.map((s) => {
      const cls = stage > s.n ? 'done' : stage === s.n ? 'active' : '';
      return '<li class="' + cls + '">' +
        '<span class="alarm-step-num">' + (stage > s.n ? '✓' : s.n) + '</span>' +
        '<span class="alarm-step-text"><b>' + s.title + '</b><i>' + s.sub + '</i></span>' +
      '</li>';
    }).join('');
  }

  let audioCtx = null;
  function getAudioContext() {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return null;
    if (!audioCtx) {
      try { audioCtx = new C(); } catch (e) { return null; }
    }
    if (audioCtx.state === 'suspended') { try { audioCtx.resume(); } catch (e) { /* noop */ } }
    return audioCtx;
  }

  function startSiren() {
    const ctx = getAudioContext();
    if (!ctx) return false;
    stopSiren();
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.connect(ctx.destination);
    const osc = ctx.createOscillator();
    osc.type = 'square';
    const t0 = ctx.currentTime;
    // 0.5초마다 660↔880Hz 를 오가는 경보음 (약 60초)
    for (let i = 0; i < 120; i += 1) osc.frequency.setValueAtTime(i % 2 ? 660 : 880, t0 + i * 0.5);
    osc.connect(gain);
    osc.start(t0);
    gain.gain.exponentialRampToValueAtTime(0.05, t0 + 0.08);
    ALARM.siren = { osc, gain };
    if (navigator.vibrate) { try { navigator.vibrate([420, 180, 420, 180, 420]); } catch (e) { /* noop */ } }
    return true;
  }

  function stopSiren() {
    if (navigator.vibrate) { try { navigator.vibrate(0); } catch (e) { /* noop */ } }
    if (!ALARM.siren) return;
    try {
      const t = audioCtx ? audioCtx.currentTime : 0;
      ALARM.siren.gain.gain.cancelScheduledValues(t);
      ALARM.siren.gain.gain.setValueAtTime(0.0001, t);
      ALARM.siren.osc.stop(t + 0.06);
    } catch (e) { /* noop */ }
    ALARM.siren = null;
  }

  function alarmClearTimers() {
    ALARM.timers.forEach((t) => clearTimeout(t));
    ALARM.timers = [];
    if (ALARM.tick) { clearInterval(ALARM.tick); ALARM.tick = null; }
  }

  function alarmStopAll() {
    alarmClearTimers();
    stopSiren();
    ALARM.stage = 0;
    ALARM.calling = false;
    ALARM.root = null;
  }

  function alarmLater(fn, ms) {
    const t = setTimeout(fn, ms);
    ALARM.timers.push(t);
    return t;
  }

  function phoneHref() { return 'tel:' + String(ALARM.phone || '').replace(/[^0-9+]/g, ''); }

  function openAlarmDemo() {
    alarmStopAll();
    ALARM.stage = 0;
    openModal(
      '<div class="sheet alarm-sheet" role="dialog" aria-modal="true">' +
        '<div class="sheet-handle"></div>' +
        '<h2>🔔 낙상 3단계 알람</h2>' +
        '<p class="sheet-sub">낙상 뒤 <b>3분(180초)</b> 동안 움직임이 없으면 보호자 1차 알림, 계속 무움직임이면 어르신 앱 알람, 알람에도 응답이 없으면 보호자에게 자동 전화로 이어집니다.</p>' +
        '<ol class="alarm-steps" id="alarm-steps">' + alarmStepsHtml(0) + '</ol>' +
        '<div id="alarm-body"></div>' +
        '<div class="sheet-actions"><button class="btn ghost block" data-close type="button">닫기</button></div>' +
      '</div>',
      { onMount(root) { ALARM.root = root; renderAlarmBody(); } }
    );
  }

  function renderAlarmBody() {
    const root = ALARM.root;
    if (!root) return;
    const body = $('#alarm-body', root);
    if (!body) return;
    const steps = $('#alarm-steps', root);
    if (steps) steps.innerHTML = alarmStepsHtml(ALARM.stage);
    const sheet = $('.alarm-sheet', root);
    if (sheet) sheet.classList.toggle('ringing', ALARM.stage === 2);

    if (ALARM.stage === 0) body.innerHTML = alarmSetupHtml();
    else if (ALARM.stage === 1) body.innerHTML = alarmStage1Html();
    else if (ALARM.stage === 2) body.innerHTML = alarmStage2Html();
    else if (ALARM.stage === 3) body.innerHTML = ALARM.calling ? alarmCallScreenHtml() : alarmStage3Html();
    else body.innerHTML = alarmDoneHtml();
    bindAlarmBody();
  }

  function alarmSetupHtml() {
    return '<div class="alarm-setup">' +
      '<div class="alarm-basis"><b class="basis-tag">실제 서비스 기준</b>' +
        '<span>낙상 후 <b>3분(180초)</b> 무움직임 → 보호자 1차 알림 · 어르신 알람 <b>1분</b> 미응답 → 보호자 자동 전화</span></div>' +
      '<div class="form-grid">' +
        '<label class="field"><span>1단계 대기 시간</span>' +
          '<select id="alarm-wait">' +
            '<option value="3">3초 (시연용)</option>' +
            '<option value="10">10초</option>' +
            '<option value="30">30초</option>' +
            '<option value="180">180초 (실제 기준 · 3분)</option>' +
          '</select></label>' +
        '<label class="field"><span>2단계 알람 미응답 판정</span>' +
          '<select id="alarm-ring">' +
            '<option value="6">6초 (시연용)</option>' +
            '<option value="12" selected>12초</option>' +
            '<option value="30">30초</option>' +
            '<option value="60">60초 (실제 기준 · 1분)</option>' +
          '</select></label>' +
        '<label class="field span2"><span>3단계 연결 번호 (보호자)</span>' +
          '<input id="alarm-phone" type="tel" inputmode="tel" value="010-0000-0000" /></label>' +
      '</div>' +
      '<button class="btn primary block" id="alarm-start" type="button">3단계 알람 시작</button>' +
      '<p class="alarm-note">시연에서는 대기 시간을 3초로 줄여 바로 체험할 수 있습니다. 실제 서비스 기준은 <b>3분(180초)</b>입니다.</p>' +
    '</div>';
  }

  function alarmStage1Html() {
    return '<div class="alarm-panel">' +
      '<div class="alarm-ring"><b id="alarm-count">' + ALARM.waitSec + '</b><small>초</small></div>' +
      '<p class="alarm-title">낙상 후 <b>무움직임</b> 확인 중</p>' +
      '<p class="alarm-sub">' + ALARM.waitSec + '초 동안 움직임이 없으면 보호자에게 1차 알림을 보냅니다.</p>' +
      '<div class="alarm-bar"><span id="alarm-progress"></span></div>' +
      '<div class="alarm-log">' +
        '<div class="ok">✓ 낙상 의심 감지 · 거실 카메라 관절 분석</div>' +
        '<div id="alarm-stage1-status">보호자 1차 알림 대기 중…</div>' +
      '</div>' +
    '</div>';
  }

  function alarmStage2Html() {
    return '<div class="alarm-panel alarm-ringing">' +
      '<div class="alarm-bell">🔔</div>' +
      '<p class="alarm-title">어르신 앱 알람이 울리고 있어요</p>' +
      '<p class="alarm-sub">보호자 알림에도 움직임이 없어 앱 알람이 켜졌습니다. 동그라미를 <b>오른쪽 끝까지 밀면</b> 알람이 꺼집니다.</p>' +
      '<div class="slide-track" id="slide-track" role="slider" tabindex="0" aria-label="밀어서 알람 끄기" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">' +
        '<span class="slide-fill" id="slide-fill"></span>' +
        '<span class="slide-label">밀어서 알람 끄기</span>' +
        '<span class="slide-knob" id="slide-knob">→</span>' +
      '</div>' +
      '<button class="btn tiny ghost" id="alarm-sound" type="button">🔊 소리 다시 켜기 / 테스트</button>' +
      '<p class="alarm-note" id="alarm-sound-state">' + (ALARM.soundOn ? '경보음과 진동이 함께 울립니다.' : '소리가 꺼져 있습니다. 위 버튼을 눌러 켜 주세요.') +
        ' (아이폰 무음 모드에서는 소리가 나지 않을 수 있어요)</p>' +
      '<div class="alarm-ring-timer">응답이 없으면 <b id="alarm-ring-left">' + ALARM.ringSec + '</b>초 뒤 3단계 · 보호자 자동 전화</div>' +
      '<button class="link-btn" id="alarm-skip" type="button">응답이 없는 상황으로 시연 →</button>' +
    '</div>';
  }

  function alarmStage3Html() {
    return '<div class="alarm-panel">' +
      '<div class="alarm-bell alarm-bell-call">📞</div>' +
      '<p class="alarm-title">3단계 · 보호자에게 자동 연결합니다</p>' +
      '<p class="alarm-sub">알람에도 응답이 없어 보호자 <b>' + esc(ALARM.phone) + '</b> 님에게 전화를 겁니다.</p>' +
      '<div class="alarm-ring"><b id="alarm-call-left">5</b><small>초</small></div>' +
      '<a class="btn danger block" id="alarm-call-now" href="' + esc(phoneHref()) + '">📞 지금 바로 전화하기</a>' +
      '<div class="alarm-log"><div class="ok">✓ 어르신 앱 알람 미응답</div><div>보호자 자동 연결 대기 중…</div></div>' +
    '</div>';
  }

  function alarmCallScreenHtml() {
    return '<div class="alarm-panel alarm-call">' +
      '<div class="alarm-call-avatar">📞</div>' +
      '<p class="alarm-call-label">긴급 연결</p>' +
      '<h3 class="alarm-call-name">보호자 ' + esc(ALARM.phone) + '</h3>' +
      '<p class="alarm-sub">브라우저 보안 정책상 자동 발신은 막혀 있습니다. 아래 큰 버튼을 한 번 누르면 바로 연결됩니다.</p>' +
      '<a class="btn danger block call-big" id="alarm-call-now" href="' + esc(phoneHref()) + '">📞 전화 연결</a>' +
      '<button class="btn ghost block" id="alarm-cancel" type="button">연결 취소</button>' +
    '</div>';
  }

  function alarmDoneHtml() {
    return '<div class="alarm-panel">' +
      '<div class="alarm-bell alarm-bell-ok">✓</div>' +
      '<p class="alarm-title">알람을 껐습니다</p>' +
      '<p class="alarm-sub">보호자에게 <b>안심 응답</b>을 보냈습니다. 3단계 자동 전화는 진행되지 않습니다.</p>' +
      '<div class="alarm-log">' +
        '<div class="ok">✓ 어르신이 밀어서 알람을 껐습니다</div>' +
        '<div class="ok">✓ 보호자에게 안심 응답 전송</div>' +
      '</div>' +
      '<button class="btn navy block" id="alarm-retry" type="button">다시 시연하기</button>' +
    '</div>';
  }

  function bindAlarmBody() {
    const root = ALARM.root;
    if (!root) return;

    const startBtn = $('#alarm-start', root);
    if (startBtn) startBtn.addEventListener('click', () => {
      // 버튼 클릭(사용자 제스처) 안에서 오디오 컨텍스트를 열어 iOS Safari 자동재생 제한을 피한다.
      getAudioContext();
      const waitSel = $('#alarm-wait', root);
      const ringSel = $('#alarm-ring', root);
      const phoneInput = $('#alarm-phone', root);
      ALARM.waitSec = Math.max(1, Number(waitSel && waitSel.value) || 3);
      ALARM.ringSec = Math.max(3, Number(ringSel && ringSel.value) || 12);
      ALARM.phone = ((phoneInput && phoneInput.value) || '010-0000-0000').trim();
      ALARM.soundOn = true;
      ALARM.calling = false;
      startStage1();
    });

    const soundBtn = $('#alarm-sound', root);
    if (soundBtn) soundBtn.addEventListener('click', () => {
      ALARM.soundOn = true;
      const ok = startSiren();
      const state = $('#alarm-sound-state', root);
      if (state) state.textContent = ok ? '경보음과 진동이 함께 울립니다.' : '이 브라우저에서는 경보음을 재생할 수 없습니다.';
    });

    const skip = $('#alarm-skip', root);
    if (skip) skip.addEventListener('click', () => goStage3());

    const cancel = $('#alarm-cancel', root);
    if (cancel) cancel.addEventListener('click', () => {
      alarmClearTimers();
      stopSiren();
      ALARM.calling = false;
      ALARM.stage = 4;
      renderAlarmBody();
    });

    const retry = $('#alarm-retry', root);
    if (retry) retry.addEventListener('click', () => {
      alarmClearTimers(); stopSiren();
      ALARM.stage = 0; ALARM.calling = false;
      renderAlarmBody();
    });

    if (ALARM.stage === 2) initSlideToDismiss();
  }

  function startStage1() {
    alarmClearTimers();
    ALARM.stage = 1;
    ALARM.left = ALARM.waitSec;
    renderAlarmBody();
    ALARM.tick = setInterval(() => {
      if (ALARM.stage !== 1) { clearInterval(ALARM.tick); ALARM.tick = null; return; }
      ALARM.left = Math.max(0, ALARM.left - 1);
      const num = $('#alarm-count', ALARM.root);
      if (num) num.textContent = String(ALARM.left);
      const bar = $('#alarm-progress', ALARM.root);
      if (bar) bar.style.width = Math.round((1 - ALARM.left / ALARM.waitSec) * 100) + '%';
      if (ALARM.left <= 0) {
        clearInterval(ALARM.tick);
        ALARM.tick = null;
        finishStage1();
      }
    }, 1000);
  }

  function finishStage1() {
    if (ALARM.stage !== 1) return;
    const status = $('#alarm-stage1-status', ALARM.root);
    const bar = $('#alarm-progress', ALARM.root);
    if (bar) bar.style.width = '100%';
    if (status) { status.className = 'ok'; status.innerHTML = '✓ 보호자에게 1차 알림을 발송했습니다'; }
    alarmLater(() => {
      ALARM.stage = 2;
      ALARM.left = ALARM.ringSec;
      renderAlarmBody();
      startStage2();
    }, 1500);
  }

  function startStage2() {
    if (ALARM.soundOn && !ALARM.siren) {
      const ok = startSiren();
      const state = $('#alarm-sound-state', ALARM.root);
      if (!ok && state) state.textContent = '이 브라우저에서는 경보음을 바로 틀 수 없습니다. 위 버튼을 눌러 주세요.';
    }
    ALARM.tick = setInterval(() => {
      if (ALARM.stage !== 2) { clearInterval(ALARM.tick); ALARM.tick = null; return; }
      ALARM.left = Math.max(0, ALARM.left - 1);
      const num = $('#alarm-ring-left', ALARM.root);
      if (num) num.textContent = String(ALARM.left);
      if (ALARM.left <= 0) {
        clearInterval(ALARM.tick);
        ALARM.tick = null;
        goStage3();
      }
    }, 1000);
  }

  function goStage3() {
    if (ALARM.stage !== 2) return;
    alarmClearTimers();
    stopSiren();
    ALARM.stage = 3;
    ALARM.calling = false;
    ALARM.left = 5;
    renderAlarmBody();
    ALARM.tick = setInterval(() => {
      if (ALARM.stage !== 3 || ALARM.calling) { clearInterval(ALARM.tick); ALARM.tick = null; return; }
      ALARM.left = Math.max(0, ALARM.left - 1);
      const num = $('#alarm-call-left', ALARM.root);
      if (num) num.textContent = String(ALARM.left);
      if (ALARM.left <= 0) {
        clearInterval(ALARM.tick);
        ALARM.tick = null;
        ALARM.calling = true;
        renderAlarmBody();
      }
    }, 1000);
  }

  function dismissAlarm() {
    if (ALARM.stage !== 2) return;
    alarmClearTimers();
    stopSiren();
    ALARM.stage = 4;
    renderAlarmBody();
    toast('알람을 껐습니다. 보호자에게 안심 응답을 보냈습니다.');
  }

  function initSlideToDismiss() {
    const root = ALARM.root;
    if (!root) return;
    const track = $('#slide-track', root);
    const knob = $('#slide-knob', root);
    const fill = $('#slide-fill', root);
    if (!track || !knob) return;

    let dragging = false;
    let startX = 0;
    let max = 0;

    const setPos = (dx) => {
      const x = Math.max(0, Math.min(max, dx));
      knob.style.transform = 'translateX(' + x + 'px)';
      if (fill) fill.style.width = (x + 34) + 'px';
      const pct = max > 0 ? Math.round((x / max) * 100) : 0;
      track.setAttribute('aria-valuenow', String(pct));
      track.classList.toggle('ready', pct >= 82);
      return x;
    };
    const reset = () => {
      knob.style.transition = 'transform .18s ease-out';
      setPos(0);
      setTimeout(() => { knob.style.transition = ''; }, 200);
      track.classList.remove('ready');
    };
    const begin = (ev) => {
      dragging = true;
      max = Math.max(1, track.clientWidth - knob.offsetWidth - 8);
      startX = ev.clientX;
      knob.style.transition = 'none';
      try { knob.setPointerCapture(ev.pointerId); } catch (e) { /* noop */ }
      ev.preventDefault();
    };
    const move = (ev) => {
      if (!dragging) return;
      const x = setPos(ev.clientX - startX);
      if (max > 0 && x >= max - 1) {
        dragging = false;
        dismissAlarm();
      }
    };
    const end = () => {
      if (!dragging) return;
      dragging = false;
      const moved = track.getAttribute('aria-valuenow');
      if (Number(moved) >= 82) dismissAlarm();
      else reset();
    };

    knob.addEventListener('pointerdown', begin);
    knob.addEventListener('pointermove', move);
    track.addEventListener('pointermove', move);
    knob.addEventListener('pointerup', end);
    knob.addEventListener('pointercancel', end);
    track.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'ArrowRight') {
        ev.preventDefault();
        dismissAlarm();
      }
    });
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
    const alarmBtn = $('#btn-alarm-demo');
    if (alarmBtn) alarmBtn.addEventListener('click', openAlarmDemo);
    $('#btn-demo-reset').addEventListener('click', resetDemo);
    $('#btn-logout').addEventListener('click', async () => {
      try { await request('/auth/logout', { method: 'POST', body: {} }); } catch (e) { /* noop */ }
      stopPolling();
      clearSession();
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

  /* 정적 배포(데모 엔진)에서는 화면 문구만 실제 환경에 맞춰 바꾼다. */
  function applyDemoCopy() {
    if (!state.useDemo) return;
    const desc = $('#sim-desc');
    if (desc) {
      desc.innerHTML = '샘플 관절좌표를 <b>실제 분석 파이프라인</b>과 같은 규칙으로 처리한 뒤, 가상 기기로 전송하는 과정을 브라우저 안에서 재현합니다. 끝나면 리포트와 알림이 바로 갱신됩니다.';
    }
    const note = $('#sim-flow');
    if (note) {
      note.innerHTML =
        '<strong>시연 흐름</strong>' +
        '<ol>' +
          '<li>샘플 관절좌표(33관절 시퀀스) 로드</li>' +
          '<li>규칙 기반 낙상·무활동·배회 감지</li>' +
          '<li>가상 기기 <code>POST /api/v1/device/*</code> 저장 (브라우저 localStorage)</li>' +
          '<li>보호자 리포트·낙상 알림 화면 갱신</li>' +
        '</ol>';
    }
    STEP_LABELS[2] = '기기 텔레메트리 반영';
  }

  async function boot() {
    bindEvents();
    tickClock();
    setInterval(tickClock, 30000);
    applyDemoCopy();
    try {
      state.demoConfig = await api.demoConfig();
      const cred = state.demoConfig.credentials || {};
      $('#login-email').value = cred.email || 'demo@homeonq.kr';
      $('#login-password').value = cred.password || 'homeonq-demo-2026';
      $('#login-hint').textContent = state.useDemo
        ? '시연용 계정 ' + (cred.email || 'demo@homeonq.kr') + ' · 비밀번호까지 채워져 있어요. [로그인]만 누르면 바로 시작합니다.'
        : '시연용 계정 ' + (cred.email || 'demo@homeonq.kr') + ' · 로그인 후 바로 확인할 수 있습니다.';
    } catch (e) {
      $('#login-hint').textContent = '서버에 연결되지 않았습니다. 잠시 후 다시 시도해 주세요.';
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
