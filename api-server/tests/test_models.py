from datetime import date, datetime, timezone
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models import *

@pytest.fixture
def engine():
    eng = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()

def test_all_models_registered_and_foreign_keys():
    expected = {'guardians','seniors','guardian_senior','camera_devices','senior_baselines','daily_scores','daily_reports','behavior_events','fall_sessions','fall_learning_sequences','fall_events','video_clips','notifications','auth_sessions','outbox_messages'}
    assert set(Base.metadata.tables) == expected
    for table in Base.metadata.tables.values():
        assert table.primary_key.columns

def test_guardian_senior_many_to_many_and_multiple_cameras(engine):
    with Session(engine) as s:
        s.add_all([Guardian(id='g1', email='a@example.com', password_hash='hash'), Guardian(id='g2', email='b@example.com', password_hash='hash'), Senior(id='s1', display_name='테스트')])
        s.flush()
        s.add_all([GuardianSenior(id='gs1', guardian_id='g1', senior_id='s1'), GuardianSenior(id='gs2', guardian_id='g2', senior_id='s1'), CameraDevice(id='c1', device_id='cam-1', senior_id='s1', token_hash='h1'), CameraDevice(id='c2', device_id='cam-2', senior_id='s1', token_hash='h2')])
        s.commit()
        assert s.query(CameraDevice).filter_by(senior_id='s1').count() == 2
        assert s.query(GuardianSenior).filter_by(senior_id='s1').count() == 2

def test_unique_device_and_guardian_link(engine):
    with Session(engine) as s:
        s.add_all([Guardian(id='g1', email='a@example.com', password_hash='h'), Senior(id='s1', display_name='x')]); s.commit()
        s.add(GuardianSenior(id='gs1', guardian_id='g1', senior_id='s1')); s.commit()
        s.add(GuardianSenior(id='gs2', guardian_id='g1', senior_id='s1'))
        with pytest.raises(IntegrityError): s.commit()
        s.rollback()
        s.add(CameraDevice(id='c1', device_id='same', senior_id='s1', token_hash='h')); s.commit()
        s.add(CameraDevice(id='c2', device_id='same', senior_id='s1', token_hash='h'))
        with pytest.raises(IntegrityError): s.commit()

def test_event_sequence_notification_constraints_and_independent_ack(engine):
    with Session(engine) as s:
        s.add_all([Guardian(id='g', email='g@example.com', password_hash='h'), Senior(id='s', display_name='x')]); s.flush()
        s.add(CameraDevice(id='c', device_id='cam', senior_id='s', token_hash='hash')); s.flush()
        s.add(FallSession(id='fs', senior_id='s', device_id='c', started_at=datetime.now(timezone.utc), status='OPEN')); s.flush()
        s.add(FallEvent(id='fe', event_id='event-1', session_id='fs', event_status='SUSPECTED', confidence=.7, occurred_at=datetime.now(timezone.utc))); s.flush()
        s.add(FallLearningSequence(id='seq1', session_id='fs', frame_index=0, timestamp=datetime.now(timezone.utc), coordinate_system='mediapipe_image_normalized_2d', joint_data={}, data_source='edge'))
        s.add(Notification(id='n1', fall_event_id='fe', recipient_id='g', alert_type='FALL', status='PENDING'))
        s.commit()
        n=s.get(Notification,'n1'); assert n.acknowledged_at is None
        n.acknowledged_at=datetime.now(timezone.utc); s.commit()
        assert s.get(FallEvent,'fe').event_status == 'SUSPECTED'
        s.add(FallLearningSequence(id='seq2', session_id='fs', frame_index=0, timestamp=datetime.now(timezone.utc), coordinate_system='mediapipe_image_normalized_2d', joint_data={}, data_source='edge'))
        with pytest.raises(IntegrityError): s.commit()

def test_nullable_score_and_constraints(engine):
    with Session(engine) as s:
        s.add(Senior(id='s', display_name='x')); s.flush()
        s.add(DailyScore(id='d', senior_id='s', score_date=date.today(), score=None, risk_level='UNKNOWN', ui_color='gray', influencing_factors={}, data_status='DATA_INSUFFICIENT', policy_version='unfinalized', calculated_at=datetime.now(timezone.utc)))
        s.commit()
        assert s.get(DailyScore,'d').score is None

def test_foreign_key_metadata_present():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column is not None
