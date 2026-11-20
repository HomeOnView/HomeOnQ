import uuid
from datetime import datetime, timezone, timedelta
from app.models import Guardian, Senior, GuardianSenior, CameraDevice, BehaviorEvent, SeniorBaseline, FallEvent, Notification, OutboxMessage
from app.services.auth import hash_token

def setup_device(client):
    c, factory = client
    c.post('/api/v1/auth/register', json={'email':'telemetry@example.com','password':'strong-password-123'})
    tokens=c.post('/api/v1/auth/login',json={'email':'telemetry@example.com','password':'strong-password-123'}).json()
    headers={'Authorization':'Bearer '+tokens['access_token']}
    db=factory(); g=db.query(Guardian).filter_by(email='telemetry@example.com').one()
    senior=Senior(id=str(uuid.uuid4()),display_name='Telemetry senior',is_active=True); db.add(senior); db.flush()
    db.add(GuardianSenior(id=str(uuid.uuid4()),guardian_id=g.id,senior_id=senior.id,status='active'))
    raw='test-device-secret-token'; device=CameraDevice(id=str(uuid.uuid4()),device_id='telemetry-cam',senior_id=senior.id,token_hash=hash_token(raw),status='active'); db.add(device); db.commit(); sid=senior.id; db.close()
    return c, factory, headers, {'X-Device-Token':raw}, sid

def test_behavior_ingest_dedup_conflict_and_guardian_read(client):
    c, dbf, gh, dh, sid=setup_device(client)
    payload={'event_id':str(uuid.uuid4()),'captured_at':datetime.now(timezone.utc).isoformat(),'activity_type':'WALKING','walking_steps':120,'confidence':0.9,'metadata':{'coordinate_system':'normalized_2d'}}
    first=c.post('/api/v1/device/behavior-events',headers=dh,json=payload); assert first.status_code==201 and first.json()['status']=='stored'
    again=c.post('/api/v1/device/behavior-events',headers=dh,json=payload); assert again.status_code==200 and again.json()['status']=='duplicate'
    changed={**payload,'walking_steps':121}; assert c.post('/api/v1/device/behavior-events',headers=dh,json=changed).status_code==409
    assert c.get(f'/api/v1/seniors/{sid}/behavior-events',headers=gh).status_code==200
    assert c.post('/api/v1/device/behavior-events',json=payload).status_code==401

def test_baseline_collecting_and_ready_after_three_distinct_days(client):
    c, dbf, gh, dh, sid=setup_device(client)
    for day in range(3):
        payload={'captured_at':(datetime(2026,10,1,tzinfo=timezone.utc)+timedelta(days=day)).isoformat(),'walking_steps':100+day,'activity_duration_seconds':200,'data_quality':0.95,'source_event_id':f'source-{day}'}
        r=c.post('/api/v1/device/baseline-data',headers=dh,json=payload); assert r.status_code==202
    result=c.get(f'/api/v1/seniors/{sid}/baseline',headers=gh).json()
    assert result['baseline_status']=='READY' and result['observed_days']==3
    score=c.get(f'/api/v1/seniors/{sid}/daily-score',headers=gh).json()
    assert score['score'] is None and score['status']=='UNKNOWN'

def test_fall_event_and_transactional_outbox(client):
    c, dbf, gh, dh, sid=setup_device(client)
    payload={'event_id':'fall-unique-001','detected_at':datetime.now(timezone.utc).isoformat(),'fall_suspected':True,'confidence':0.88,'risk_level':'HIGH','reasoning':'rapid vertical movement'}
    r=c.post('/api/v1/device/fall-events',headers=dh,json=payload); assert r.status_code==201
    assert r.json()['notification_count']==1
    duplicate=c.post('/api/v1/device/fall-events',headers=dh,json=payload); assert duplicate.status_code==200 and duplicate.json()['status']=='duplicate'
    db=dbf(); assert db.query(FallEvent).count()==1; assert db.query(Notification).count()==1; assert db.query(OutboxMessage).count()==1; db.close()
    assert c.get(f'/api/v1/seniors/{sid}/fall-events',headers=gh).status_code==200
    assert c.post('/api/v1/device/fall-events',headers=dh,json={**payload,'event_id':'bad-fall','confidence':1.5}).status_code==422
