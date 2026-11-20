import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db.session import get_db
from app.models import Base, Guardian, Senior, GuardianSenior, CameraDevice
from app.services.auth import hash_token

@pytest.fixture()
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    def override_db():
        db = TestingSession()
        try: yield db
        finally: db.close()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c, TestingSession
    app.dependency_overrides.clear(); Base.metadata.drop_all(engine); engine.dispose()

def test_register_login_me_and_refresh_logout(client):
    c, factory = client
    r = c.post('/api/v1/auth/register', json={'email':'a@example.com','password':'a-very-strong-password'})
    assert r.status_code == 201
    db = factory(); g = db.query(Guardian).filter_by(email='a@example.com').one()
    assert g.password_hash != 'a-very-strong-password'
    db.close()
    assert c.post('/api/v1/auth/register', json={'email':'a@example.com','password':'a-very-strong-password'}).status_code == 409
    login = c.post('/api/v1/auth/login', json={'email':'a@example.com','password':'a-very-strong-password'})
    assert login.status_code == 200
    tokens = login.json(); headers={'Authorization':'Bearer '+tokens['access_token']}
    assert c.get('/api/v1/auth/me', headers=headers).status_code == 200
    rotated = c.post('/api/v1/auth/refresh', json={'refresh_token':tokens['refresh_token']})
    assert rotated.status_code == 200
    assert c.post('/api/v1/auth/refresh', json={'refresh_token':tokens['refresh_token']}).status_code == 401
    assert c.post('/api/v1/auth/logout', json={'refresh_token':rotated.json()['refresh_token']}, headers=headers).status_code == 204

def test_guardian_senior_authorization_and_device_lifecycle(client):
    c, factory = client
    c.post('/api/v1/auth/register', json={'email':'owner@example.com','password':'a-very-strong-password'})
    c.post('/api/v1/auth/register', json={'email':'other@example.com','password':'another-strong-password'})
    login=c.post('/api/v1/auth/login',json={'email':'owner@example.com','password':'a-very-strong-password'}).json()
    h={'Authorization':'Bearer '+login['access_token']}
    db=factory(); owner=db.query(Guardian).filter_by(email='owner@example.com').one(); other=db.query(Guardian).filter_by(email='other@example.com').one()
    senior=Senior(id=str(uuid.uuid4()),display_name='Test senior',is_active=True)
    db.add(senior); db.flush(); db.add(GuardianSenior(id=str(uuid.uuid4()),guardian_id=owner.id,senior_id=senior.id,status='active')); db.commit(); sid=senior.id; db.close()
    assert c.get(f'/api/v1/seniors/{sid}',headers=h).status_code == 200
    other_login=c.post('/api/v1/auth/login',json={'email':'other@example.com','password':'another-strong-password'}).json()
    assert c.get(f'/api/v1/seniors/{sid}',headers={'Authorization':'Bearer '+other_login['access_token']}).status_code == 404
    created=c.post('/api/v1/guardians/me/devices',headers=h,json={'device_id':'cam-01','senior_id':sid})
    assert created.status_code == 201
    token=created.json()['device_token']; assert created.json()['device_token']
    db=factory(); device=db.query(CameraDevice).filter_by(device_id='cam-01').one(); assert device.token_hash == hash_token(token); assert token not in device.token_hash; db.close()
    assert c.get('/api/v1/device/me',headers={'X-Device-Token':token}).status_code == 200
    assert c.post('/api/v1/device/heartbeat',headers={'X-Device-Token':token}).status_code == 200
    rotated=c.post('/api/v1/guardians/me/devices/cam-01/rotate-key',headers=h); assert rotated.status_code == 200
    assert c.get('/api/v1/device/me',headers={'X-Device-Token':token}).status_code == 401
    new=rotated.json()['device_token']
    assert c.post('/api/v1/guardians/me/devices/cam-01/revoke',headers=h).status_code == 204
    assert c.get('/api/v1/device/me',headers={'X-Device-Token':new}).status_code == 401

def test_invalid_expired_access_and_inactive_relationship(client):
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    c, factory = client
    c.post('/api/v1/auth/register', json={'email':'guard@example.com','password':'strong-password-123'})
    token=c.post('/api/v1/auth/login',json={'email':'guard@example.com','password':'strong-password-123'}).json()['access_token']
    assert c.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+token+'x'}).status_code == 401
    expired=jwt.encode({'sub':'g','iat':datetime.now(timezone.utc)-timedelta(hours=2),'exp':datetime.now(timezone.utc)-timedelta(hours=1),'jti':'expired','typ':'access'},settings.jwt_secret,algorithm=settings.jwt_algorithm)
    assert c.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+expired}).status_code == 401
    db=factory(); g=db.query(Guardian).filter_by(email='guard@example.com').one(); s=Senior(id=str(uuid.uuid4()),display_name='inactive relation target'); db.add(s); db.flush(); rel=GuardianSenior(id=str(uuid.uuid4()),guardian_id=g.id,senior_id=s.id,status='inactive'); db.add(rel); db.commit(); sid=s.id; db.close()
    assert c.get(f'/api/v1/seniors/{sid}',headers={'Authorization':'Bearer '+token}).status_code == 404
