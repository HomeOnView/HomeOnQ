// 서버에 연결할 수 없을 때 보여줄 데모 데이터 (웹앱과 같은 수치)
export const demoSenior = {
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
};

const today = new Date().toISOString().slice(0, 10);

export const demoReport = {
  report_date: today,
  score: 70,
  risk_level: 'WATCH',
  risk_label: '주의',
  ui_color: '#A84D08',
  headline: '강O순 어르신, 오늘은 조금 살펴봐 주시면 좋겠습니다',
  narrative:
    '11월 21일 강O순 어르신의 하루를 정리했습니다.\n\n오늘은 걸음 수 3,215걸음, 야간 활동 55분, 화장실 이용 8회, 침실 체류 480분이 확인되었습니다.\n\n평소와 비교해 주의할 점이 있습니다. 평소보다 22% 적게 걸었습니다, 야간 활동이 55분 감지되었습니다, 5.0시간 동안 움직임이 적었습니다.\n\n이 리포트는 카메라 관절 좌표 분석을 바탕으로 만든 참고 자료이며, 진단을 대신하지 않습니다.',
  summary: {
    rows: [
      { key: 'steps', label: '보행', value: 3215, unit: '걸음', delta_percent: -22 },
      { key: 'night_activity', label: '야간 활동', value: 55, unit: '분' },
      { key: 'toilet', label: '화장실 이용', value: 8, unit: '회' },
      { key: 'bedroom', label: '침실 체류', value: 480, unit: '분' },
    ],
  },
  factors: { items: [{ label: '보행량 감소', detail: '평소보다 22% 적게 걸었습니다', delta: -8 }] },
  source: 'demo-data',
  data_status: 'FINAL',
  generated_at: new Date().toISOString(),
};

export const demoEvents = [
  { kind: 'behavior', id: 'd1', title: '보행', activity_type: 'WALKING', value: 3215, unit: '걸음', occurred_at: new Date(Date.now() - 3 * 3600e3).toISOString(), status: 'ANALYZED', detail: '오전 산책과 집 안 이동' },
  { kind: 'behavior', id: 'd2', title: '야간 활동', activity_type: 'NIGHT_ACTIVITY', value: 55, unit: '분', occurred_at: new Date(Date.now() - 8 * 3600e3).toISOString(), status: 'ANALYZED', detail: '새벽 화장실 이동 포함' },
  { kind: 'behavior', id: 'd3', title: '화장실 이용', activity_type: 'TOILET_VISIT', value: 8, unit: '회', occurred_at: new Date(Date.now() - 2 * 3600e3).toISOString(), status: 'ANALYZED', detail: '하루 화장실 이용 8회' },
  { kind: 'fall', id: 'd4', event_id: 'demo-past-fall-001', title: '낙상 의심', occurred_at: new Date(Date.now() - 2 * 86400e3).toISOString(), status: 'CONFIRMED', confidence: 0.81, risk_level: 'MEDIUM', detail: '거실에서 앉은 자세로 낮아진 뒤 20초간 움직임이 없었습니다.' },
];

export const demoAlerts = [];
