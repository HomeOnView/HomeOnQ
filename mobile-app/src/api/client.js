import { API_BASE_URL } from '../config';

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : '요청을 처리하지 못했습니다.');
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  const { method = 'GET', body, token, timeout = 15000 } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(API_BASE_URL + '/api/v1' + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (error) {
      data = text;
    }
    if (!response.ok) {
      throw new ApiError(response.status, data && data.detail ? data.detail : data);
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  demoConfig: () => request('/demo/config'),
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  me: (token) => request('/auth/me', { token }),
  health: () => request('/health'),
  seniors: (token) => request('/guardians/me/seniors', { token }),
  senior: (token, id) => request(`/seniors/${id}`, { token }),
  patchSenior: (token, id, body) => request(`/seniors/${id}`, { method: 'PATCH', token, body }),
  latestReport: (token, id) => request(`/seniors/${id}/daily-reports/latest`, { token }),
  events: (token, id, days = 7) => request(`/seniors/${id}/events?days=${days}`, { token }),
  alerts: (token) => request('/guardians/me/alerts', { token }),
  summary: (token, id) => request(`/seniors/${id}/summary`, { token }),
  testFall: (token, id) => request(`/seniors/${id}/test-fall`, { method: 'POST', token }),
  patchFall: (token, id, eventId, status) =>
    request(`/seniors/${id}/fall-events/${encodeURIComponent(eventId)}`, { method: 'PATCH', token, body: { status } }),
  acknowledge: (token, notificationId) =>
    request(`/guardians/me/notifications/${notificationId}/acknowledge`, { method: 'POST', token }),
  simulate: (token, scenario, seniorId) =>
    request('/demo/simulate', { method: 'POST', token, body: { scenario, senior_id: seniorId }, timeout: 60000 }),
  reset: (token) => request('/demo/reset', { method: 'POST', token, timeout: 30000 }),
};

export function isNetworkError(error) {
  return error && (error.name === 'AbortError' || error instanceof TypeError || /Network request failed/i.test(error.message || ''));
}
