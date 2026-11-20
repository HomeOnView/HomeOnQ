import hashlib, secrets, uuid
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models import Guardian, AuthSession, GuardianSenior, Senior, CameraDevice

_password_hasher = PasswordHasher()
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    return _password_hasher.hash(password)

def verify_password(password: str, encoded: str) -> bool:
    try: return _password_hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError): return False

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def create_access_token(guardian_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': guardian_id, 'iat': now, 'exp': now + timedelta(minutes=settings.access_token_minutes), 'jti': str(uuid.uuid4()), 'typ': 'access'}, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def decode_access_token(token: str) -> str:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={'require': ['sub','iat','exp','jti']})
        if data.get('typ') != 'access': raise ValueError('wrong token type')
        return str(data['sub'])
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail='Invalid or expired credentials', headers={'WWW-Authenticate':'Bearer'})

def get_current_guardian(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> Guardian:
    if not creds: raise HTTPException(401, 'Authentication required')
    guardian_id = decode_access_token(creds.credentials)
    guardian = db.get(Guardian, guardian_id)
    if not guardian or not guardian.is_active: raise HTTPException(401, 'Invalid or expired credentials')
    return guardian

def require_senior_access(senior_id: str, guardian: Guardian, db: Session) -> Senior:
    row = db.scalar(select(GuardianSenior).where(GuardianSenior.guardian_id == guardian.id, GuardianSenior.senior_id == senior_id, GuardianSenior.status == 'active'))
    if not row: raise HTTPException(404, 'Senior not found')
    senior = db.get(Senior, senior_id)
    if not senior or not senior.is_active: raise HTTPException(404, 'Senior not found')
    return senior

def generate_device_token() -> str:
    return secrets.token_urlsafe(48)

def get_current_device(token: str | None, db: Session) -> CameraDevice:
    if not token: raise HTTPException(401, 'Device authentication required')
    digest = hash_token(token)
    device = db.scalar(select(CameraDevice).where(CameraDevice.token_hash == digest))
    if not device or device.status != 'active': raise HTTPException(401, 'Invalid device credentials')
    # SHA-256 is appropriate here because tokens are generated with 384 bits of entropy.
    if not secrets.compare_digest(device.token_hash, digest): raise HTTPException(401, 'Invalid device credentials')
    return device
