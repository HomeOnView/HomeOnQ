from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Expo Go / Expo web / 로컬 개발에서 쓰는 기본 오리진.
DEFAULT_CORS_ORIGINS = [
    'http://localhost:8081',
    'http://127.0.0.1:8081',
    'http://localhost:19006',
    'http://127.0.0.1:19006',
    'http://localhost:8082',
    'http://127.0.0.1:8082',
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_env: str = 'development'
    app_name: str = 'HOMEONQ API'
    api_version: str = '0.3.0'
    # 로컬 개발 기본값은 SQLite. 운영에서는 PostgreSQL + psycopg DSN을 넣는다.
    database_url: str = 'sqlite:///./homeonq_dev.db'
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    # 개발 환경에서만 적용되는 사설망(LAN) 오리진 허용 정규식.
    # Expo Go를 같은 Wi-Fi의 휴대폰에서 열면 http://192.168.x.x:8081 형태로 접근한다.
    cors_allow_lan_regex: str = (
        r'^http://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d{1,3}\.\d{1,3}\.\d{1,3}'
        r'|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$'
    )
    jwt_secret: str = 'development-only-change-this-secret-before-use-32bytes-min'
    jwt_algorithm: str = 'HS256'
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    guardian_dev_token: str | None = None
    # 개발 환경에서 테이블이 없으면 자동 생성한다(운영에서는 Alembic만 사용).
    auto_create_schema: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env == 'production'


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.app_env == 'production':
        if len(s.jwt_secret) < 32 or s.jwt_secret.startswith('development-only'):
            raise RuntimeError('A strong JWT_SECRET is required in production')
        if s.guardian_dev_token:
            raise RuntimeError('GUARDIAN_DEV_TOKEN must not be configured in production')
        if not s.database_url.startswith('postgresql'):
            raise RuntimeError('Production DATABASE_URL must use PostgreSQL')
        if s.auto_create_schema:
            raise RuntimeError('AUTO_CREATE_SCHEMA must be false in production')
        if '*' in s.cors_origins:
            raise RuntimeError('Wildcard CORS origin is not allowed in production')
    return s


settings = get_settings()
