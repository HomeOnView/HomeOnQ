from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.routes import auth, demo, devices, guardian, reports, telemetry
from app.core.config import settings
from app.db.session import Base, engine

WEBAPP_DIR = Path(__file__).resolve().parents[1] / "webapp"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 로컬 개발 편의: 테이블이 없으면 만들어 준다. 운영은 Alembic만 사용한다.
    if settings.auto_create_schema and not settings.is_production:
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version=settings.api_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=None if settings.is_production else settings.cors_allow_lan_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Device-Token", "Idempotency-Key"],
)

for module in (auth, devices, telemetry, reports, guardian, demo):
    app.include_router(module.router, prefix="/api/v1")


@app.get("/api/v1/health", tags=["system"])
def health():
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "environment": settings.app_env,
        "version": settings.api_version,
        "database": "ok" if db_ok else "unavailable",
        "webapp": WEBAPP_DIR.exists(),
    }


# 웹앱(모바일 UI)을 같은 서버에서 서빙한다. 라우터를 먼저 등록했으므로
# /api/v1/* 는 그대로 API로 처리되고, 나머지 경로가 정적 파일로 간다.
if WEBAPP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")
