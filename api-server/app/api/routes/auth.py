import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import AuthSession, Guardian
from app.schemas.auth import GuardianResponse, LoginRequest, RegisterRequest, TokenResponse
from app.services.auth import (
    create_access_token, get_current_guardian, hash_password, hash_token, verify_password,
)

router = APIRouter(tags=['authentication'])


def _new_session(db: Session, guardian_id: str) -> str:
    raw = secrets.token_urlsafe(48)
    row = AuthSession(
        id=str(uuid.uuid4()),
        guardian_id=guardian_id,
        refresh_token_hash=hash_token(raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days),
    )
    db.add(row)
    return raw


@router.post('/auth/register', response_model=GuardianResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.scalar(select(Guardian).where(Guardian.email == email)):
        raise HTTPException(409, 'Email already registered')
    guardian = Guardian(id=str(uuid.uuid4()), email=email, password_hash=hash_password(payload.password), is_active=True)
    db.add(guardian)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, 'Unable to create account')
    db.refresh(guardian)
    return guardian


@router.post('/auth/login', response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    guardian = db.scalar(select(Guardian).where(Guardian.email == payload.email.strip().lower()))
    if not guardian or not guardian.is_active or not verify_password(payload.password, guardian.password_hash):
        raise HTTPException(401, 'Invalid email or password')
    refresh = _new_session(db, guardian.id)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(guardian.id),
        refresh_token=refresh,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post('/auth/refresh', response_model=TokenResponse)
def refresh(payload: dict, db: Session = Depends(get_db)):
    raw = payload.get('refresh_token')
    if not isinstance(raw, str) or not raw:
        raise HTTPException(401, 'Invalid refresh token')
    row = db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(raw)))
    now = datetime.now(timezone.utc)
    if not row or row.revoked_at or row.expires_at.replace(tzinfo=timezone.utc) <= now:
        if row and row.revoked_at:  # Reuse of a rotated/revoked token revokes all sessions for this account.
            db.query(AuthSession).filter(
                AuthSession.guardian_id == row.guardian_id, AuthSession.revoked_at.is_(None)
            ).update({AuthSession.revoked_at: now})
            db.commit()
        raise HTTPException(401, 'Invalid refresh token')
    guardian = db.get(Guardian, row.guardian_id)
    if not guardian or not guardian.is_active:
        raise HTTPException(401, 'Invalid refresh token')
    row.revoked_at = now
    replacement = _new_session(db, guardian.id)
    db.commit()
    return TokenResponse(
        access_token=create_access_token(guardian.id),
        refresh_token=replacement,
        expires_in=settings.access_token_minutes * 60,
    )


@router.post('/auth/logout', status_code=204)
def logout(payload: dict, db: Session = Depends(get_db), guardian: Guardian = Depends(get_current_guardian)):
    raw = payload.get('refresh_token')
    if isinstance(raw, str):
        row = db.scalar(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == hash_token(raw), AuthSession.guardian_id == guardian.id
            )
        )
        if row and not row.revoked_at:
            row.revoked_at = datetime.now(timezone.utc)
            db.commit()


@router.get('/auth/me', response_model=GuardianResponse)
def me(guardian: Guardian = Depends(get_current_guardian)):
    return guardian
