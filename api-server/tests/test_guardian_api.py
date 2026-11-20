"""보호자 앱용 API(프로필·리포트·이벤트·알림·테스트 낙상) 통합 테스트."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import (
    BehaviorEvent, CameraDevice, DailyReport, FallEvent, FallSession, Guardian,
    GuardianSenior, Notification, Senior,
)
from app.services.auth import hash_token


def _login(c, email='guardian@example.com', password='strong-password-123'):
    c.post('/api/v1/auth/register', json={'email': email, 'password': password})
    tokens = c.post('/api/v1/auth/login', json={'email': email, 'password': password}).json()
    return {'Authorization': 'Bearer ' + tokens['access_token']}


def _senior(client, email='guardian@example.com'):
    c, factory = client
    db = factory()
    guardian = db.query(Guardian).filter_by(email=email).one()
    senior = Senior(
        id=str(uuid.uuid4()), display_name='테스트 어르신', birth_date=date(1950, 5, 5),
        gender='여성', height_cm=158, weight_kg=51, medical_conditions=['고혈압'],
        photo_url='https://example.com/a.png', emergency_contact='010-0000-0000',
    )
    db.add(senior)
    db.flush()
    db.add(GuardianSenior(id=str(uuid.uuid4()), guardian_id=guardian.id, senior_id=senior.id, status='active'))
    raw = 'test-device-token-guardian'
    db.add(CameraDevice(id=str(uuid.uuid4()), device_id='cam-guardian', senior_id=senior.id,
                        token_hash=hash_token(raw), status='active'))
    db.commit()
    sid = senior.id
    db.close()
    return sid


def test_profile_read_patch_and_validation(client):
    c, _ = client
    headers = _login(c)
    sid = _senior(client)
    detail = c.get(f'/api/v1/seniors/{sid}', headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body['display_name'] == '테스트 어르신'
    assert body['medical_conditions'] == ['고혈압']
    assert body['devices'][0]['device_id'] == 'cam-guardian'

    updated = c.patch(f'/api/v1/seniors/{sid}', headers=headers, json={
        'height_cm': 159.5, 'weight_kg': 50, 'medical_conditions': ['고혈압', '관절염'],
        'memo': '거실 카메라', 'gender': '여성',
    })
    assert updated.status_code == 200
    assert updated.json()['height_cm'] == 159.5
    assert updated.json()['medical_conditions'] == ['고혈압', '관절염']
    assert updated.json()['memo'] == '거실 카메라'

    assert c.patch(f'/api/v1/seniors/{sid}', headers=headers, json={'height_cm': 10}).status_code == 422
    assert c.patch(f'/api/v1/seniors/{sid}', headers=headers, json={'gender': '남자'}).status_code == 422
    assert c.patch(f'/api/v1/seniors/{sid}', headers=headers, json={'photo_url': 'ftp://x'}).status_code == 422
    assert c.patch(f'/api/v1/seniors/{sid}', headers=headers, json={'unknown_field': 1}).status_code == 422

    listing = c.get('/api/v1/guardians/me/seniors', headers=headers)
    assert listing.status_code == 200 and listing.json()['items'][0]['id'] == sid


def test_daily_report_device_ingest_and_guardian_read(client):
    c, factory = client
    headers = _login(c, 'report@example.com')
    sid = _senior(client, 'report@example.com')
    raw = 'device-token-report'
    db = factory()
    db.add(CameraDevice(id=str(uuid.uuid4()), device_id='cam-report', senior_id=sid,
                        token_hash=hash_token(raw), status='active'))
    db.commit()
    db.close()
    device_headers = {'X-Device-Token': raw}
    today = date.today().isoformat()
    payload = {
        'report_date': today, 'score': 72, 'risk_level': 'WATCH', 'risk_label': '주의',
        'ui_color': '#A84D08', 'headline': '오늘은 조금 살펴봐 주세요', 'narrative': '리포트 본문',
        'summary': {'rows': [{'label': '보행', 'value': 3215, 'unit': '걸음'}]},
        'factors': {'items': [{'code': 'STEPS_DROP', 'delta': -8}]},
        'data_status': 'FINAL', 'source': 'pipeline-rule', 'model_name': None, 'event_count': 4,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    first = c.post('/api/v1/device/daily-reports', headers=device_headers, json=payload)
    assert first.status_code == 201 and first.json()['status'] == 'stored'
    payload['score'] = 68
    second = c.post('/api/v1/device/daily-reports', headers=device_headers, json=payload)
    assert second.status_code == 201 and second.json()['status'] == 'updated'

    latest = c.get(f'/api/v1/seniors/{sid}/daily-reports/latest', headers=headers).json()
    assert latest['score'] == 68 and latest['risk_label'] == '주의'
    assert latest['headline'] == '오늘은 조금 살펴봐 주세요'
    assert latest['summary']['rows'][0]['label'] == '보행'

    history = c.get(f'/api/v1/seniors/{sid}/daily-reports', headers=headers).json()
    assert history['items'][0]['report_date'] == today
    assert c.get('/api/v1/device/daily-reports').status_code in (401, 404, 405)
    # 다른 보호자는 접근할 수 없다.
    other = _login(c, 'other-report@example.com')
    assert c.get(f'/api/v1/seniors/{sid}/daily-reports/latest', headers=other).status_code == 404


def test_daily_report_latest_is_empty_when_missing(client):
    c, _ = client
    headers = _login(c, 'empty@example.com')
    sid = _senior(client, 'empty@example.com')
    latest = c.get(f'/api/v1/seniors/{sid}/daily-reports/latest', headers=headers)
    assert latest.status_code == 200
    assert latest.json()['score'] is None
    assert latest.json()['data_status'] == 'DATA_INSUFFICIENT'


def test_event_timeline_merges_behavior_and_falls(client):
    c, factory = client
    headers = _login(c, 'events@example.com')
    sid = _senior(client, 'events@example.com')
    db = factory()
    now = datetime.now(timezone.utc)
    db.add(BehaviorEvent(id=str(uuid.uuid4()), senior_id=sid, event_type='WALKING', event_value=3215,
                         occurred_at=now - timedelta(hours=2), analysis_status='ANALYZED', details={'note': '산책'}))
    device = db.query(CameraDevice).filter_by(senior_id=sid).one()
    session = FallSession(id=str(uuid.uuid4()), senior_id=sid, device_id=device.id,
                          started_at=now - timedelta(hours=1), status='SUSPECTED')
    db.add(session)
    db.flush()
    db.add(FallEvent(id=str(uuid.uuid4()), event_id='evt-1', session_id=session.id,
                     occurred_at=now - timedelta(hours=1), confidence=0.8, severity='HIGH',
                     rationale={'reasoning': '급격한 자세 변화'}))
    db.commit()
    db.close()

    timeline = c.get(f'/api/v1/seniors/{sid}/events', headers=headers).json()
    assert timeline['count'] == 2
    assert timeline['items'][0]['kind'] == 'fall'
    assert timeline['items'][0]['title'] == '낙상 의심'
    assert timeline['items'][1]['title'] == '보행'
    assert timeline['items'][1]['value'] == 3215

    only_falls = c.get(f'/api/v1/seniors/{sid}/events?kind=fall', headers=headers).json()
    assert only_falls['count'] == 1

    summary = c.get(f'/api/v1/seniors/{sid}/summary', headers=headers).json()
    assert summary['fall_count'] == 1
    assert summary['latest_report'] is None


def test_test_fall_creates_notification_and_alert(client):
    c, factory = client
    headers = _login(c, 'alert@example.com')
    sid = _senior(client, 'alert@example.com')

    triggered = c.post(f'/api/v1/seniors/{sid}/test-fall', headers=headers)
    assert triggered.status_code == 201
    body = triggered.json()
    assert body['is_test'] is True and body['notification_count'] == 1

    alerts = c.get('/api/v1/guardians/me/alerts', headers=headers).json()
    assert len(alerts['items']) == 1
    assert alerts['items'][0]['is_test'] is True
    assert alerts['items'][0]['senior_name'] == '테스트 어르신'

    db = factory()
    note = db.query(Notification).one()
    ack = c.post(f'/api/v1/guardians/me/notifications/{note.id}/acknowledge', headers=headers)
    assert ack.status_code == 200
    assert c.get('/api/v1/guardians/me/alerts', headers=headers).json()['items'] == []
    assert len(c.get('/api/v1/guardians/me/alerts?include_acknowledged=true', headers=headers).json()['items']) == 1
    db.close()

    # 테스트 낙상은 이벤트 목록에도 is_test로 표시된다.
    timeline = c.get(f'/api/v1/seniors/{sid}/events?kind=fall', headers=headers).json()
    assert timeline['items'][0]['is_test'] is True


def test_test_fall_requires_registered_camera(client):
    c, factory = client
    headers = _login(c, 'nocam@example.com')
    sid = _senior(client, 'nocam@example.com')
    db = factory()
    db.query(CameraDevice).filter_by(senior_id=sid).delete()
    db.commit()
    db.close()
    assert c.post(f'/api/v1/seniors/{sid}/test-fall', headers=headers).status_code == 409


def test_score_preview_rules(client):
    c, _ = client
    headers = _login(c, 'score@example.com')
    sid = _senior(client, 'score@example.com')
    result = c.post(f'/api/v1/seniors/{sid}/score-preview', headers=headers, json={
        'metrics': {'steps': 3215, 'night_activity_minutes': 55, 'toilet_visits': 8, 'inactivity_minutes': 300},
        'baseline': {'steps': 4100}, 'fall_count': 0,
    }).json()
    assert result['score'] == 70
    assert result['risk_level'] == 'WATCH' and result['risk_label'] == '주의'
    assert result['ui_color'] == '#A84D08'
    assert len(result['factors']['items']) == 4
