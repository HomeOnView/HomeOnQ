/* HOMEONQ 보호자 안심 리포트 — 브라우저 내장 데모 엔진
 *
 * GitHub Pages처럼 백엔드(FastAPI) 없이 정적 파일만 올라가는 환경에서도
 * 로그인·리포트 홈·분석 테스트·낙상 알림·프로필 수정·초기화가 모두 실제처럼
 * 동작하도록, 서버의 응답 규약(/api/v1/...)을 브라우저 안에서 재현한다.
 *
 * · 저장소: localStorage (없으면 메모리) — 새로고침해도 상태가 유지된다.
 * · 점수·리포트 문장: 서버 `api-server/app/services/scoring.py`, `report_text.py`,
 *   `camera-analysis/onview/report_generator.py`와 같은 규칙을 그대로 옮겼다.
 * · 분석 테스트: `camera-analysis/samples/*.json` 샘플 시퀀스를 실제 파이프라인에
 *   통과시켜 얻은 검출 결과(낙상 0.95 / 무활동 0.95 / 배회 0.80, 구간 지표)를
 *   시나리오 사실(facts)로 담고, 하루 지표 → 점수 → 리포트 → 이벤트·알림을
 *   브라우저에서 계산한다.
 *
 * 서버가 있는 환경(로컬 uvicorn, Render)에서는 이 엔진을 쓰지 않고 실제 API를 쓴다.
 */
(function (global) {
  'use strict';

  const STORE_KEY = 'homeonq.demo.state.v1';
  const APP_VERSION = '0.3.0';
  const KST_OFFSET_MIN = 9 * 60;

  const CREDENTIALS = {
    email: 'demo@homeonq.kr',
    password: 'homeonq-demo-2026',
    senior_name: '강O순 어르신',
  };

  const BASELINE = { steps: 4100, walking_minutes: 62, night_activity_minutes: 18 };
  const SEED_METRICS = {
    steps: 3215,
    night_activity_minutes: 55,
    toilet_visits: 8,
    bedroom_minutes: 480,
    inactivity_minutes: 300,
    walking_minutes: 48,
  };

  const RISK_STYLES = {
    SAFE: { label: '안심', color: '#1E7B4C' },
    WATCH: { label: '주의', color: '#A84D08' },
    ALERT: { label: '경계', color: '#B42318' },
    UNKNOWN: { label: '확인 필요', color: '#566079' },
  };

  const ACTIVITY_LABELS = {
    WALKING: ['보행', '걸음'],
    STEPS: ['보행', '걸음'],
    NIGHT_ACTIVITY: ['야간 활동', '분'],
    TOILET_VISIT: ['화장실 이용', '회'],
    BEDROOM_STAY: ['침실 체류', '분'],
    INACTIVE: ['장시간 무활동', '분'],
    WANDERING: ['배회', '분'],
    POSTURE: ['자세', ''],
    ACTIVITY: ['활동', '분'],
  };

  const SEED_SENIOR = {
    id: 'demo-senior-0001',
    display_name: '강O순 어르신',
    birth_date: '1951-03-12',
    gender: '여성',
    height_cm: 160,
    weight_kg: 52,
    medical_conditions: ['당뇨', '고혈압', '척추측만증'],
    photo_url: '',
    emergency_contact: '010-0000-0000',
    memo: '분당 자택 거실 카메라(Tapo C225)로 관찰 중',
  };

  const DEVICE_SEED = [
    { device_id: 'TAPO-C225-LIVING', status: 'active', health_status: 'HEALTHY' },
    { device_id: 'DEMO-EDGE-01', status: 'active', health_status: 'HEALTHY' },
  ];

  /* 분석 테스트 시나리오 — 실제 파이프라인으로 samples/*.json을 분석한 결과 */
  const SCENARIOS = {
    normal: {
      label: '정상 보행',
      description: '거실을 천천히 걷는 10초 구간(정상 보행)',
      duration_s: 10.0,
      clip_seconds: 10.0,
      frame_count: 150,
      gait_stability: 0.92,
      torso_angle_max: 0.5,
      events: [],
      metrics: {
        steps: 3380, night_activity_minutes: 18, toilet_visits: 6,
        bedroom_minutes: 470, inactivity_minutes: 90, walking_minutes: 55,
      },
    },
    fall: {
      label: '낙상 발생',
      description: '걷던 중 2.5초에 넘어져 바닥에 누운 9초 구간',
      duration_s: 9.0,
      clip_seconds: 9.0,
      frame_count: 135,
      gait_stability: 0.92,
      torso_angle_max: 89.1,
      events: [
        {
          kind: 'fall', event_type: 'FALL', confidence: 0.95, duration_s: 4.0, frame_index: 43,
          reasoning: '골반 높이가 0.71/s 속도로 급격히 낮아지고 몸통 기울기가 89°까지 커진 뒤 4.0초간 낮은 자세가 유지되었습니다.',
          features: { drop_speed: 0.713, torso_angle_deg: 89.1, lying_seconds: 4.0, low_motion_after: 0.48 },
        },
      ],
      metrics: {
        steps: 2980, night_activity_minutes: 75, toilet_visits: 9,
        bedroom_minutes: 420, inactivity_minutes: 265, walking_minutes: 32,
      },
    },
    inactive: {
      label: '장시간 무활동',
      description: '소파에 앉아 10초 동안 거의 움직이지 않은 구간(시간 배속 1800배 = 약 4.8시간)',
      duration_s: 17280.0,
      clip_seconds: 9.6,
      frame_count: 48,
      gait_stability: 0.99,
      torso_angle_max: 7.9,
      events: [
        {
          kind: 'inactivity', event_type: 'INACTIVE', confidence: 0.95, duration_s: 16920.0, frame_index: 1,
          reasoning: '4.7시간 동안 관절 움직임이 기준 이하로 유지되었습니다.',
          features: { inactive_seconds: 16920, threshold: 14400.0 },
        },
      ],
      metrics: {
        steps: 640, night_activity_minutes: 25, toilet_visits: 5,
        bedroom_minutes: 510, inactivity_minutes: 380, walking_minutes: 9,
      },
    },
    wandering: {
      label: '야간 배회',
      description: '야간 거실 좌우 이동 반복 구간(시간 배속 30배 = 약 12분)',
      duration_s: 720.0,
      clip_seconds: 24.0,
      frame_count: 240,
      gait_stability: 0.59,
      torso_angle_max: 0.6,
      events: [
        {
          kind: 'wandering', event_type: 'WANDERING', confidence: 0.8, duration_s: 720.0, frame_index: 0,
          reasoning: '12분 동안 좌우 이동이 10회 반복되어 배회 패턴으로 판단했습니다.',
          features: { crossings: 10, minutes: 12.0 },
        },
      ],
      metrics: {
        steps: 1500, night_activity_minutes: 65, toilet_visits: 9,
        bedroom_minutes: 390, inactivity_minutes: 130, wandering_minutes: 12, walking_minutes: 26,
      },
    },
  };

  /* 지표 → 텔레메트리 전송 시각 오프셋(시연용, pipeline.py와 동일) */
  const TIME_OFFSETS_MS = {
    WALKING: 6 * 3600e3,
    NIGHT_ACTIVITY: 2 * 3600e3,
    TOILET_VISIT: 1.5 * 3600e3,
    BEDROOM_STAY: 40 * 60e3,
    INACTIVE: 3 * 3600e3,
    WANDERING: 1 * 3600e3,
  };

  const BEHAVIOR_SPECS = [
    ['WALKING', 'steps', '걸음'],
    ['NIGHT_ACTIVITY', 'night_activity_minutes', '분'],
    ['TOILET_VISIT', 'toilet_visits', '회'],
    ['BEDROOM_STAY', 'bedroom_minutes', '분'],
    ['INACTIVE', 'inactivity_minutes', '분'],
    ['WANDERING', 'wandering_minutes', '분'],
  ];

  /* ------------------------------------------------------------ utilities */
  const pad = (n) => String(n).padStart(2, '0');

  function kstParts(ms) {
    const d = new Date(ms + KST_OFFSET_MIN * 60e3);
    return {
      y: d.getUTCFullYear(), m: d.getUTCMonth() + 1, d: d.getUTCDate(),
      h: d.getUTCHours(), mi: d.getUTCMinutes(),
    };
  }
  function kstDate(ms) {
    const p = kstParts(ms);
    return p.y + '-' + pad(p.m) + '-' + pad(p.d);
  }
  function kstMidnight(ms) {
    const p = kstParts(ms);
    return Date.UTC(p.y, p.m - 1, p.d) - KST_OFFSET_MIN * 60e3;
  }
  function isoUtc(ms) {
    return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
  }
  function group(n) {
    const rounded = String(Math.round(n));
    return rounded.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }
  function fmtNum(value, unit) {
    if (value === null || value === undefined) return '-';
    const n = Number(value);
    if (!isFinite(n)) return '-';
    if (Number.isInteger(n)) return group(n) + (unit || '');
    return (Math.round(n * 10) / 10).toFixed(1) + (unit || '');
  }
  function riskStyle(level) {
    return RISK_STYLES[level] || RISK_STYLES.UNKNOWN;
  }

  /* --------------------------------------------------- 점수 산정 (scoring.py) */
  function computeDailyScore(metrics, baseline, fallCount) {
    let score = 100;
    const items = [];
    const apply = (code, label, delta, detail) => {
      if (!delta) return;
      score += delta;
      items.push({ code, label, delta, detail });
    };
    const m = metrics || {};
    const b = baseline || {};

    const steps = m.steps;
    const baseSteps = b.steps;
    if (steps !== null && steps !== undefined && baseSteps) {
      const change = ((steps - baseSteps) / baseSteps) * 100;
      if (change <= -30) {
        apply('STEPS_DROP', '보행량 감소', -15, '평소보다 ' + Math.round(Math.abs(change)) + '% 적게 걸었습니다');
      } else if (change <= -15) {
        apply('STEPS_DROP', '보행량 감소', -8, '평소보다 ' + Math.round(Math.abs(change)) + '% 적게 걸었습니다');
      } else if (change >= 40) {
        apply('STEPS_RISE', '보행량 증가', 2, '평소보다 ' + Math.round(change) + '% 많이 걸었습니다');
      }
    }

    const night = m.night_activity_minutes;
    if (night !== null && night !== undefined) {
      if (night >= 60) apply('NIGHT_ACTIVITY', '야간 활동 증가', -10, '야간 활동이 ' + fmtNum(night) + '분 감지되었습니다');
      else if (night >= 30) apply('NIGHT_ACTIVITY', '야간 활동 증가', -5, '야간 활동이 ' + fmtNum(night) + '분 감지되었습니다');
    }

    const inactivity = m.inactivity_minutes;
    if (inactivity !== null && inactivity !== undefined && inactivity >= 240) {
      apply('LONG_INACTIVITY', '장시간 무활동', -12, (inactivity / 60).toFixed(1) + '시간 동안 움직임이 적었습니다');
    }

    const wandering = m.wandering_minutes;
    if (wandering !== null && wandering !== undefined && wandering >= 10) {
      apply('WANDERING', '배회 패턴', -8, '배회로 보이는 이동이 ' + fmtNum(wandering) + '분 있었습니다');
    }

    if (fallCount >= 2) {
      apply('FALL_RECENT', '낙상 의심 반복', -35, '낙상 의심 이벤트가 ' + fallCount + '건 있습니다');
    } else if (fallCount === 1) {
      apply('FALL_RECENT', '낙상 의심', -20, '낙상 의심 이벤트가 1건 있습니다');
    }

    const toilet = m.toilet_visits;
    if (toilet !== null && toilet !== undefined && toilet >= 8) {
      apply('TOILET_FREQUENT', '화장실 이용 증가', -5, '화장실 이용이 ' + fmtNum(toilet) + '회 감지되었습니다');
    }

    score = Math.max(0, Math.min(100, Math.round(score)));
    const level = score >= 80 ? 'SAFE' : score >= 60 ? 'WATCH' : 'ALERT';
    const style = riskStyle(level);
    return {
      score,
      risk_level: level,
      risk_label: style.label,
      ui_color: style.color,
      factors: { policy_version: 'homeonq-score-poc-v1', items },
    };
  }

  /* ------------------------------------------- 요약 행 (build_summary_rows / compose_summary) */
  function buildSummaryRows(metrics, baseline) {
    const m = metrics || {};
    const b = baseline || {};
    const rows = [];
    if (m.steps !== undefined && m.steps !== null) {
      const delta = b.steps ? Math.round(((m.steps - b.steps) / b.steps) * 100) : null;
      rows.push({ key: 'steps', label: '보행', value: m.steps, unit: '걸음', delta_percent: delta });
    }
    if (m.night_activity_minutes !== undefined && m.night_activity_minutes !== null) {
      rows.push({
        key: 'night_activity', label: '야간 활동', value: m.night_activity_minutes,
        unit: '분', delta_percent: null, detail: '야간 시간대 감지',
      });
    }
    if (m.toilet_visits !== undefined && m.toilet_visits !== null) {
      rows.push({ key: 'toilet', label: '화장실 이용', value: m.toilet_visits, unit: '회' });
    }
    if (m.bedroom_minutes !== undefined && m.bedroom_minutes !== null) {
      rows.push({ key: 'bedroom', label: '침실 체류', value: m.bedroom_minutes, unit: '분' });
    }
    if (m.inactivity_minutes !== undefined && m.inactivity_minutes !== null) {
      rows.push({ key: 'inactivity', label: '최장 무활동', value: m.inactivity_minutes, unit: '분' });
    }
    if (m.wandering_minutes) {
      rows.push({ key: 'wandering', label: '배회', value: m.wandering_minutes, unit: '분' });
    }
    return rows;
  }

  /* --------------------------------------------------- 리포트 문장 (규칙 기반) */
  function ruleHeadline(seniorName, factors, fallCount, riskLevel) {
    const name = String(seniorName || '').replace(' 어르신', '');
    const scored = ((factors && factors.items) || []).filter((f) => f.delta < 0);
    if (fallCount) return name + ' 어르신 댁에서 낙상 의심 신호가 감지되었습니다';
    if (scored.some((f) => f.code === 'LONG_INACTIVITY')) return name + ' 어르신, 오랜 시간 움직임이 적었습니다';
    if (scored.some((f) => f.code === 'WANDERING')) return name + ' 어르신, 야간 배회가 조금 있었습니다';
    if (riskLevel === 'SAFE') return name + ' 어르신, 오늘도 평안한 하루를 보내셨습니다';
    if (scored.length) return name + ' 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다';
    return name + ' 어르신, 오늘도 평안한 하루를 보내셨습니다';
  }

  function ruleNarrative(seniorName, day, metrics, factors, events, fallCount) {
    const name = String(seniorName || '').replace(' 어르신', '');
    const p = String(day).split('-');
    const m = metrics || {};
    const evs = events || [];
    const lines = [Number(p[1]) + '월 ' + Number(p[2]) + '일 ' + name + ' 어르신의 하루를 정리했습니다.'];

    const parts = [];
    if (m.steps !== undefined && m.steps !== null) parts.push('걸음 수 ' + fmtNum(m.steps, '걸음'));
    if (m.night_activity_minutes !== undefined && m.night_activity_minutes !== null) parts.push('야간 활동 ' + fmtNum(m.night_activity_minutes, '분'));
    if (m.toilet_visits !== undefined && m.toilet_visits !== null) parts.push('화장실 이용 ' + fmtNum(m.toilet_visits, '회'));
    if (m.bedroom_minutes !== undefined && m.bedroom_minutes !== null) parts.push('침실 체류 ' + fmtNum(m.bedroom_minutes, '분'));
    if (parts.length) lines.push('오늘은 ' + parts.join(', ') + '이 확인되었습니다.');

    const fallEvents = evs.filter((e) => e.kind === 'fall');
    if (fallEvents.length || fallCount) {
      const detail = fallEvents.length ? (fallEvents[0].reasoning || '') : '';
      lines.push(
        '낙상 의심 이벤트가 감지되어 보호자 알림을 보냈습니다. ' + (detail ? detail + ' ' : '') +
        "어르신의 상태를 직접 확인해 주시고, 괜찮으시면 알림을 '확인'으로 바꿔 주세요."
      );
    }
    if (evs.some((e) => e.kind === 'inactivity')) {
      const minutes = m.inactivity_minutes || 0;
      lines.push('오랜 시간 움직임이 적었습니다(약 ' + (minutes / 60).toFixed(1) + '시간). 식사와 수분 섭취를 권해 주세요.');
    }
    if (evs.some((e) => e.kind === 'wandering')) {
      lines.push('밤 시간대 좌우로 오가는 이동이 반복되었습니다. 수면 환경과 화장실 동선을 살펴봐 주세요.');
    }

    const scored = ((factors && factors.items) || []).filter((f) => f.delta < 0);
    if (scored.length && !fallEvents.length) {
      lines.push('평소와 비교해 주의할 점이 있습니다. ' + scored.slice(0, 3).map((f) => f.detail).join(', ') + '.');
      lines.push('다음 날 활동이 이어지는지 함께 살펴봐 주세요.');
    } else if (!scored.length && !fallEvents.length) {
      lines.push('평소와 크게 다르지 않은 하루였습니다. 특별히 걱정하실 부분은 없습니다.');
    }

    lines.push('이 리포트는 카메라 관절 좌표 분석을 바탕으로 만든 참고 자료이며, 진단을 대신하지 않습니다.');
    return lines.join('\n\n');
  }

  /* 시연 시드 문장 (api-server/services/report_text.compose_narrative와 동일) */
  function seedNarrative(seniorName, day, metrics, factors, fallCount) {
    const name = String(seniorName || '').replace(' 어르신', '');
    const p = String(day).split('-');
    const m = metrics || {};
    const scored = ((factors && factors.items) || []).filter((f) => f.delta < 0);
    const lines = [Number(p[1]) + '월 ' + Number(p[2]) + '일 ' + name + ' 어르신의 하루를 정리했습니다.'];
    const parts = [];
    if (m.steps !== undefined && m.steps !== null) parts.push('걸음 수 ' + fmtNum(m.steps, '걸음'));
    if (m.night_activity_minutes !== undefined && m.night_activity_minutes !== null) parts.push('야간 활동 ' + fmtNum(m.night_activity_minutes, '분'));
    if (m.toilet_visits !== undefined && m.toilet_visits !== null) parts.push('화장실 이용 ' + fmtNum(m.toilet_visits, '회'));
    if (m.bedroom_minutes !== undefined && m.bedroom_minutes !== null) parts.push('침실 체류 ' + fmtNum(m.bedroom_minutes, '분'));
    if (parts.length) lines.push('오늘은 ' + parts.join(', ') + '이 확인되었습니다.');
    if (fallCount) {
      lines.push(
        '낙상 의심 이벤트가 ' + fallCount + "건 감지되어 알림을 보냈습니다. 어르신의 상태를 직접 확인해 주시고, 괜찮으시면 알림을 '확인'으로 바꿔 주세요."
      );
    } else if (scored.length) {
      lines.push('평소와 비교해 주의할 점이 있습니다. ' + scored.slice(0, 3).map((f) => f.detail).join(', ') + '.');
      lines.push('식사와 수분 섭취를 권하고, 다음 날 활동이 이어지는지 함께 살펴봐 주세요.');
    } else {
      lines.push('평소와 크게 다르지 않은 하루였습니다. 특별히 걱정하실 부분은 없습니다.');
    }
    lines.push('이 리포트는 카메라 관절 좌표 분석을 바탕으로 만든 참고 자료이며, 진단을 대신하지 않습니다.');
    return lines.join('\n\n');
  }

  function seedHeadline(seniorName, factors, fallCount) {
    const name = String(seniorName || '').replace(' 어르신', '');
    const scored = ((factors && factors.items) || []).filter((f) => f.delta < 0);
    if (fallCount) return name + ' 어르신 댁에서 낙상 의심 신호가 감지되었습니다';
    if (scored.length) return name + ' 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다';
    return name + ' 어르신, 오늘도 평안한 하루를 보내셨습니다';
  }

  /* ------------------------------------------------------------ 에러 */
  function ApiError(status, detail) {
    const err = new Error(typeof detail === 'string' ? detail : '요청을 처리하지 못했습니다.');
    err.name = 'DemoApiError';
    err.isDemoApiError = true;
    err.status = status;
    err.detail = detail;
    return err;
  }

  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /* ------------------------------------------------------------ 엔진 */
  function createEngine(options) {
    const opts = options || {};
    const nowFn = opts.now || (() => Date.now());
    let memory = null;
    const storage = opts.storage !== undefined ? opts.storage : safeStorage();

    function safeStorage() {
      try {
        const key = '__homeonq_probe__';
        global.localStorage.setItem(key, '1');
        global.localStorage.removeItem(key);
        return global.localStorage;
      } catch (e) {
        return null;
      }
    }

    function readRaw() {
      if (!storage) return memory;
      try {
        const text = storage.getItem(STORE_KEY);
        return text ? JSON.parse(text) : null;
      } catch (e) {
        return null;
      }
    }
    function writeRaw(state) {
      memory = state;
      if (!storage) return;
      try {
        storage.setItem(STORE_KEY, JSON.stringify(state));
      } catch (e) {
        /* 저장 실패(사생활 보호 모드 등) → 메모리 상태로만 동작 */
      }
    }

    /* ---------------------------------------------- 시드 상태 (demo_seed.py) */
    function at(nowMs, deltaMs) {
      const start = kstMidnight(nowMs);
      const earliest = start + 30 * 60e3;
      return Math.max(earliest, Math.min(nowMs - 5 * 60e3, nowMs - deltaMs));
    }

    function buildSeed(nowMs) {
      const day = kstDate(nowMs);
      const metrics = Object.assign({}, SEED_METRICS);
      const score = computeDailyScore(metrics, BASELINE, 0);
      const rows = buildSummaryRows(metrics, BASELINE);
      const headline = seedHeadline(SEED_SENIOR.display_name, score.factors, 0);
      const narrative = seedNarrative(SEED_SENIOR.display_name, day, metrics, score.factors, 0);

      const behaviors = [
        ['NIGHT_ACTIVITY', 55, 7.5 * 3600e3, '새벽 화장실 이동 포함'],
        ['WALKING', 3215, 3 * 3600e3, '오전 산책과 집안 이동'],
        ['INACTIVE', 300, 2 * 3600e3, '오후 소파에서 5시간 무활동'],
        ['TOILET_VISIT', 8, 1 * 3600e3, '하루 화장실 이용 8회'],
        ['BEDROOM_STAY', 480, 40 * 60e3, '침실 체류 8시간'],
      ].map((spec, idx) => ({
        id: 'seed-b-' + idx,
        event_type: spec[0],
        value: spec[1],
        unit: (ACTIVITY_LABELS[spec[0]] || ['', ''])[1],
        occurred_at: isoUtc(at(nowMs, spec[2])),
        note: spec[3],
        status: 'ANALYZED',
        data_quality: 0.92,
      }));

      const pastFallAt = kstMidnight(nowMs) - 2 * 86400e3 + 3 * 3600e3;
      const falls = [{
        id: 'seed-f-1',
        event_id: 'demo-past-fall-001',
        occurred_at: isoUtc(pastFallAt),
        status: 'CONFIRMED',
        risk_level: 'MEDIUM',
        confidence: 0.81,
        reasoning: '거실에서 앉은 자세로 낮아진 뒤 20초간 움직임이 없었습니다.',
        is_test: false,
      }];

      return {
        version: 1,
        created_at: isoUtc(nowMs),
        senior: Object.assign({}, SEED_SENIOR),
        baseline: Object.assign({}, BASELINE),
        devices: DEVICE_SEED.map((d) => Object.assign({}, d, { last_seen_at: isoUtc(nowMs - 90e3) })),
        behaviors,
        falls,
        notifications: [{
          notification_id: 'seed-n-1',
          event_id: 'demo-past-fall-001',
          alert_type: 'FALL_SUSPECTED',
          created_at: isoUtc(pastFallAt),
          acknowledged_at: isoUtc(pastFallAt + 6 * 60e3),
        }],
        reports: {
          [day]: {
            report_date: day,
            score: score.score,
            risk_level: score.risk_level,
            risk_label: score.risk_label,
            ui_color: score.ui_color,
            headline,
            narrative,
            summary: { metrics, baseline: Object.assign({}, BASELINE), rows, fall_count: 0 },
            factors: score.factors,
            data_status: 'FINAL',
            source: 'demo-seed',
            model_name: null,
            event_count: 5,
            generated_at: isoUtc(nowMs),
          },
        },
        audit: [],
        seq: 0,
      };
    }

    function load() {
      let st = readRaw();
      if (!st || st.version !== 1 || !st.senior) {
        st = buildSeed(nowFn());
        writeRaw(st);
      }
      return st;
    }

    function save(st) {
      writeRaw(st);
    }

    function nextId(st, prefix) {
      st.seq = (st.seq || 0) + 1;
      return prefix + '-' + st.seq + '-' + Math.random().toString(36).slice(2, 7);
    }

    /* -------------------------------------------------- 응답 조립 */
    function profile(st) {
      const birth = st.senior.birth_date ? new Date(st.senior.birth_date + 'T00:00:00+09:00') : null;
      const nowP = kstParts(nowFn());
      let age = null;
      if (birth) {
        const bp = kstParts(birth.getTime());
        age = nowP.y - bp.y - ((nowP.m < bp.m || (nowP.m === bp.m && nowP.d < bp.d)) ? 1 : 0);
      }
      return Object.assign({}, st.senior, {
        age,
        is_active: true,
        devices: st.devices.map((d) => ({
          device_id: d.device_id,
          status: d.status,
          last_seen_at: d.last_seen_at || null,
          health_status: d.health_status || 'HEALTHY',
          health_metrics: { fps: 15.0, source: 'demo-engine' },
          last_health_at: d.last_seen_at || null,
        })),
      });
    }

    function latestReport(st) {
      const days = Object.keys(st.reports || {}).sort();
      if (!days.length) return null;
      return st.reports[days[days.length - 1]];
    }

    function behaviorItem(b) {
      const meta = ACTIVITY_LABELS[b.event_type] || [b.event_type, ''];
      return {
        kind: 'behavior',
        id: b.id,
        event_id: b.id,
        title: meta[0],
        detail: b.note || '',
        occurred_at: b.occurred_at,
        status: b.status || 'ANALYZED',
        risk_level: null,
        confidence: b.data_quality || 0.92,
        value: b.value,
        unit: b.unit || meta[1],
        activity_type: b.event_type,
      };
    }

    function fallItem(f) {
      return {
        kind: 'fall',
        id: f.id,
        event_id: f.event_id,
        title: '낙상 의심',
        detail: f.reasoning || '',
        occurred_at: f.occurred_at,
        status: f.status,
        risk_level: f.risk_level,
        confidence: f.confidence,
        is_test: !!f.is_test,
      };
    }

    function eventsWithin(st, days) {
      const since = nowFn() - (days || 7) * 86400e3;
      const items = []
        .concat((st.behaviors || []).map(behaviorItem))
        .concat((st.falls || []).map(fallItem))
        .filter((it) => new Date(it.occurred_at).getTime() >= since);
      items.sort((a, b) => String(b.occurred_at).localeCompare(String(a.occurred_at)));
      return items.slice(0, 50);
    }

    function alertItems(st) {
      const byEvent = {};
      (st.falls || []).forEach((f) => { byEvent[f.event_id] = f; });
      return (st.notifications || [])
        .filter((n) => !n.acknowledged_at)
        .map((n) => {
          const f = byEvent[n.event_id] || {};
          return {
            notification_id: n.notification_id,
            alert_type: n.alert_type || 'FALL_SUSPECTED',
            event_id: n.event_id,
            senior_id: st.senior.id,
            senior_name: st.senior.display_name,
            occurred_at: f.occurred_at || n.created_at,
            confidence: f.confidence != null ? f.confidence : 0.95,
            risk_level: f.risk_level || 'HIGH',
            status: f.status || 'SUSPECTED',
            is_test: !!f.is_test,
            reasoning: f.reasoning || '',
            acknowledged_at: null,
          };
        })
        .sort((a, b) => String(b.occurred_at).localeCompare(String(a.occurred_at)));
    }

    function summaryPayload(st, days) {
      const since = nowFn() - (days || 7) * 86400e3;
      const falls = (st.falls || []).filter((f) => new Date(f.occurred_at).getTime() >= since);
      const behaviors = (st.behaviors || []).slice().sort((a, b) => String(b.occurred_at).localeCompare(String(a.occurred_at)));
      const report = latestReport(st);
      return {
        senior_id: st.senior.id,
        days: days || 7,
        fall_count: falls.length,
        unacknowledged_alerts: (st.notifications || []).filter((n) => !n.acknowledged_at).length,
        last_behavior_at: behaviors.length ? behaviors[0].occurred_at : null,
        latest_report: report || null,
      };
    }

    /* -------------------------------------------------- 분석 테스트 실행 */
    function buildBehaviorPayloads(st, metrics, nowMs) {
      const payloads = [];
      BEHAVIOR_SPECS.forEach((spec) => {
        const type = spec[0];
        const value = metrics[spec[1]];
        if (value === undefined || value === null || value === 0) return;
        const captured = at(nowMs, TIME_OFFSETS_MS[type] || 3600e3);
        let note;
        if (type === 'WALKING') note = '분석 구간에서 ' + fmtNum(value) + '걸음을 추정했습니다';
        else if (type === 'NIGHT_ACTIVITY') note = '야간 시간대 활동 ' + fmtNum(value) + '분';
        else if (type === 'TOILET_VISIT') note = '화장실 이용 ' + fmtNum(value) + '회';
        else if (type === 'BEDROOM_STAY') note = '침실 체류 ' + fmtNum(value) + '분';
        else if (type === 'INACTIVE') note = '장시간 무활동 ' + fmtNum(value) + '분';
        else if (type === 'WANDERING') note = '좌우 반복 이동(배회) ' + fmtNum(value) + '분';
        else note = type + ' ' + fmtNum(value);
        payloads.push({
          event_id: nextId(st, 'be'),
          captured_at: isoUtc(captured),
          activity_type: type,
          event_value: Number(value),
          unit: spec[2],
          confidence: 0.9,
          data_quality: 0.92,
          note,
        });
      });
      return payloads;
    }

    function simulateSync(st, scenario, seniorId) {
      const facts = SCENARIOS[scenario];
      if (!facts) throw ApiError(422, '알 수 없는 시나리오입니다: ' + scenario);
      if (seniorId && seniorId !== st.senior.id) throw ApiError(404, '연결된 어르신을 찾지 못했습니다.');

      const nowMs = nowFn();
      const day = kstDate(nowMs);
      const metrics = Object.assign({}, facts.metrics);

      const detected = facts.events.map((e) => Object.assign({}, e, {
        occurred_at: isoUtc(nowMs - (e.kind === 'fall' ? 0 : 5 * 60e3)),
      }));
      const fallCount = detected.filter((e) => e.kind === 'fall').length;
      const score = computeDailyScore(metrics, st.baseline, fallCount);

      const behaviorPayloads = buildBehaviorPayloads(st, metrics, nowMs);

      /* 같은 날 같은 지표는 최신 값으로 대체한다(시연 목록이 중복으로 쌓이지 않도록). */
      const today = kstDate(nowMs);
      const keep = (st.behaviors || []).filter((b) => {
        if (kstDate(new Date(b.occurred_at).getTime()) !== today) return true;
        return !behaviorPayloads.some((p) => p.activity_type === b.event_type);
      });
      st.behaviors = keep.concat(behaviorPayloads.map((p) => ({
        id: p.event_id,
        event_type: p.activity_type,
        value: p.event_value,
        unit: p.unit,
        occurred_at: p.captured_at,
        note: p.note,
        status: 'ANALYZED',
        data_quality: p.data_quality,
      })));

      const fallPayloads = [];
      detected.filter((e) => e.kind === 'fall').forEach((e) => {
        const fall = {
          id: nextId(st, 'fall'),
          event_id: 'sim-' + nextId(st, 'ev'),
          occurred_at: e.occurred_at,
          status: 'SUSPECTED',
          risk_level: e.confidence >= 0.75 ? 'HIGH' : 'MEDIUM',
          confidence: e.confidence,
          reasoning: e.reasoning,
          is_test: false,
        };
        st.falls = (st.falls || []).concat([fall]);
        st.notifications = (st.notifications || []).concat([{
          notification_id: nextId(st, 'note'),
          event_id: fall.event_id,
          alert_type: 'FALL_SUSPECTED',
          created_at: fall.occurred_at,
          acknowledged_at: null,
        }]);
        fallPayloads.push(fall);
      });

      const headline = ruleHeadline(st.senior.display_name, score.factors, fallCount, score.risk_level);
      const narrative = ruleNarrative(st.senior.display_name, day, metrics, score.factors, detected, fallCount);
      const rows = buildSummaryRows(metrics, st.baseline);
      const report = {
        report_date: day,
        score: score.score,
        risk_level: score.risk_level,
        risk_label: score.risk_label,
        ui_color: score.ui_color,
        headline,
        narrative,
        summary: { metrics, baseline: Object.assign({}, st.baseline), rows, fall_count: fallCount },
        factors: score.factors,
        data_status: 'FINAL',
        source: 'pipeline-rule',
        model_name: null,
        event_count: behaviorPayloads.length + fallPayloads.length,
        generated_at: isoUtc(nowMs),
      };
      st.reports = st.reports || {};
      st.reports[day] = report;

      st.devices = (st.devices || []).map((d) => (d.device_id === 'DEMO-EDGE-01'
        ? Object.assign({}, d, { last_seen_at: isoUtc(nowMs), health_status: 'HEALTHY' })
        : d));

      st.audit = (st.audit || []).concat([{ at: isoUtc(nowMs), scenario, score: score.score }]).slice(-20);
      save(st);

      return {
        scenario,
        senior_id: st.senior.id,
        device_id: 'DEMO-EDGE-01',
        analysis: {
          scenario,
          label: facts.label,
          description: facts.description,
          duration_s: facts.duration_s,
          events: detected.map((e) => ({
            kind: e.kind, event_type: e.event_type, confidence: e.confidence,
            reasoning: e.reasoning, duration_s: e.duration_s, frame_index: e.frame_index,
            occurred_at: e.occurred_at, features: e.features,
          })),
          segment_metrics: {
            steps: facts.segment_steps != null ? facts.segment_steps : undefined,
            clip_seconds: facts.clip_seconds,
            frame_count: facts.frame_count,
            gait_stability: facts.gait_stability,
            torso_angle_max: facts.torso_angle_max,
            detector: 'rule',
          },
          metrics,
          score,
          report,
          report_source: 'pipeline-rule',
          behavior_count: behaviorPayloads.length,
          fall_count: fallPayloads.length,
          detector: 'rule',
          ai_model: null,
        },
        sent: { behavior: behaviorPayloads.length, fall: fallPayloads.length, report: 1, errors: [] },
        report,
      };
    }

    async function simulate(st, scenario, seniorId) {
      await delay(520);
      return simulateSync(st, scenario, seniorId);
    }

    /* -------------------------------------------------- 라우팅 */
    function requireAuth(options) {
      const body = options || {};
      if (body.auth === false) return;
      if (!body.token) throw ApiError(401, '인증이 필요합니다.');
    }

    function handle(st, path, options, query) {
      const opts = options || {};
      const method = (opts.method || 'GET').toUpperCase();

      /* 공개 */
      if (path === '/demo/config') {
        return {
          enabled: true,
          mode: 'static',
          credentials: Object.assign({}, CREDENTIALS),
          scenarios: Object.keys(SCENARIOS),
        };
      }
      if (path === '/health') {
        return {
          status: 'ok',
          environment: 'static-demo',
          version: APP_VERSION,
          database: 'localStorage',
          webapp: true,
          engine: 'browser-demo',
        };
      }
      if (path === '/auth/login' && method === 'POST') {
        const body = opts.body || {};
        const email = String(body.email || '').trim().toLowerCase();
        if (email !== CREDENTIALS.email || body.password !== CREDENTIALS.password) {
          throw ApiError(401, 'Invalid email or password');
        }
        return {
          access_token: 'demo-' + nowFn().toString(36),
          refresh_token: 'demo-refresh',
          token_type: 'bearer',
          expires_in: 86400,
        };
      }

      requireAuth(opts);

      if (path === '/auth/me') {
        return { id: 'demo-guardian-0001', email: CREDENTIALS.email, is_active: true };
      }
      if (path === '/auth/logout') return { status: 'ok' };

      if (path === '/guardians/me/seniors') {
        return { items: [profile(st)] };
      }
      if (path === '/guardians/me/alerts') {
        return { items: alertItems(st) };
      }
      const ack = path.match(/^\/guardians\/me\/notifications\/([^/]+)\/acknowledge$/);
      if (ack && method === 'POST') {
        const id = decodeURIComponent(ack[1]);
        const note = (st.notifications || []).find((n) => n.notification_id === id);
        if (!note) throw ApiError(404, '알림을 찾지 못했습니다.');
        if (!note.acknowledged_at) note.acknowledged_at = isoUtc(nowFn());
        save(st);
        return { notification_id: id, acknowledged_at: note.acknowledged_at };
      }

      if (path === '/demo/reset' && method === 'POST') {
        const fresh = buildSeed(nowFn());
        save(fresh);
        Object.keys(st).forEach((k) => { delete st[k]; });
        Object.assign(st, fresh);
        return {
          status: 'reset',
          guardian: { email: CREDENTIALS.email, id: 'demo-guardian-0001' },
          senior: { id: fresh.senior.id, display_name: fresh.senior.display_name },
          reset: true,
        };
      }
      if (path === '/demo/simulate' && method === 'POST') {
        throw new Error('DEMO_SIMULATE_ASYNC');
      }

      const seniorPath = path.match(/^\/seniors\/([^/]+)(\/.*)?$/);
      if (seniorPath) {
        const seniorId = decodeURIComponent(seniorPath[1]);
        const rest = seniorPath[2] || '';
        if (seniorId !== st.senior.id) throw ApiError(404, '연결된 어르신을 찾지 못했습니다.');

        if (rest === '' && method === 'GET') return profile(st);
        if (rest === '' && (method === 'PATCH' || method === 'PUT')) {
          const body = opts.body || {};
          const next = Object.assign({}, st.senior);
          const fields = ['display_name', 'birth_date', 'gender', 'height_cm', 'weight_kg',
            'medical_conditions', 'photo_url', 'emergency_contact', 'memo'];
          fields.forEach((f) => {
            if (Object.prototype.hasOwnProperty.call(body, f)) next[f] = body[f];
          });
          if (next.display_name !== undefined && !String(next.display_name || '').trim()) {
            throw ApiError(422, '성함을 입력해 주세요.');
          }
          if (!Array.isArray(next.medical_conditions)) {
            next.medical_conditions = next.medical_conditions ? [next.medical_conditions] : [];
          }
          st.senior = next;
          save(st);
          return profile(st);
        }
        if (rest === '/access') return { senior_id: seniorId, has_access: true };
        if (rest === '/daily-reports/latest') {
          const report = latestReport(st);
          return report || {
            report_date: kstDate(nowFn()), score: null, risk_level: 'UNKNOWN', risk_label: '데이터 수집 중',
            ui_color: '#566079', headline: '아직 오늘의 리포트가 도착하지 않았습니다',
            narrative: '카메라 분석이 시작되면 오늘의 활동과 안심 점수가 이곳에 표시됩니다.',
            summary: {}, factors: { policy_version: null, items: [] }, data_status: 'DATA_INSUFFICIENT',
            source: null, model_name: null, event_count: 0, generated_at: null,
          };
        }
        if (rest === '/events') {
          const days = Number(query.days || 7);
          const items = eventsWithin(st, days);
          return { items, count: items.length, days };
        }
        if (rest === '/summary') {
          return summaryPayload(st, Number(query.days || 7));
        }
        if (rest === '/test-fall' && method === 'POST') {
          const nowMs = nowFn();
          const fall = {
            id: nextId(st, 'fall'),
            event_id: 'guardian-test-' + nextId(st, 'ev'),
            occurred_at: isoUtc(nowMs),
            status: 'SUSPECTED',
            risk_level: 'HIGH',
            confidence: 0.99,
            reasoning: '보호자 앱에서 실행한 낙상 알림 테스트입니다.',
            is_test: true,
          };
          st.falls = (st.falls || []).concat([fall]);
          st.notifications = (st.notifications || []).concat([{
            notification_id: nextId(st, 'note'),
            event_id: fall.event_id,
            alert_type: 'FALL_TEST',
            created_at: fall.occurred_at,
            acknowledged_at: null,
          }]);
          save(st);
          return {
            status: 'stored', event_id: fall.event_id, event_status: fall.status,
            notification_count: 1, is_test: true,
          };
        }
        const fallPatch = rest.match(/^\/fall-events\/([^/]+)$/);
        if (fallPatch && method === 'PATCH') {
          const eventId = decodeURIComponent(fallPatch[1]);
          const status = (opts.body || {}).status;
          const fall = (st.falls || []).find((f) => f.event_id === eventId || f.id === eventId);
          if (!fall) throw ApiError(404, '낙상 이벤트를 찾지 못했습니다.');
          if (['SUSPECTED', 'CONFIRMED', 'DISMISSED'].indexOf(status) === -1) {
            throw ApiError(422, '잘못 된 상태 값입니다.');
          }
          fall.status = status;
          (st.notifications || []).forEach((n) => {
            if (n.event_id === fall.event_id && status !== 'SUSPECTED' && !n.acknowledged_at) {
              n.acknowledged_at = isoUtc(nowFn());
            }
          });
          save(st);
          return fallItem(fall);
        }
      }

      throw ApiError(404, '지원하지 않는 경로입니다: ' + path);
    }

    async function request(path, options) {
      const raw = String(path || '');
      const parts = raw.split('?');
      const cleanPath = parts[0].replace(/\/+$/, '') || '/';
      const query = {};
      if (parts[1]) {
        parts[1].split('&').forEach((pair) => {
          const kv = pair.split('=');
          if (kv[0]) query[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
        });
      }
      const st = load();
      if (cleanPath === '/demo/simulate' && (options || {}).method === 'POST') {
        requireAuth(options);
        return simulate(st, (options.body || {}).scenario, (options.body || {}).senior_id);
      }
      if (cleanPath === '/demo/simulate') {
        throw ApiError(405, 'POST로 호출해야 합니다.');
      }
      await delay(60);
      return handle(st, cleanPath, options, query);
    }

    return {
      mode: 'static',
      credentials: () => Object.assign({}, CREDENTIALS),
      scenarios: () => Object.keys(SCENARIOS),
      request,
      reset: () => { const fresh = buildSeed(nowFn()); save(fresh); return fresh; },
      snapshot: () => load(),
      computeDailyScore,
      buildSummaryRows,
      ruleNarrative,
      SEED_METRICS,
      BASELINE,
      SCENARIOS,
      /* 테스트용 동기 진입점 (브라우저 런타임에서는 쓰지 않는다) */
      _debug: {
        dispatch: (path, options) => {
          const [cleanPath, qs] = String(path).split('?');
          const query = {};
          if (qs) qs.split('&').forEach((pair) => {
            const kv = pair.split('=');
            if (kv[0]) query[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || '');
          });
          return handle(load(), cleanPath, options || {}, query);
        },
        simulate: (scenario, seniorId, options) => {
          requireAuth(options || {});
          return simulateSync(load(), scenario, seniorId);
        },
      },
    };
  }

  global.HOMEONQ_DEMO = {
    createEngine,
    computeDailyScore,
    buildSummaryRows,
    ruleNarrative,
    seedNarrative,
    ApiError,
    CREDENTIALS,
    SCENARIOS,
  };
})(typeof window !== 'undefined' ? window : globalThis);
