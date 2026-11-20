# HOMEONQ API server

FastAPI + SQLAlchemy 2.x + Alembic. SQLite로 바로 실행되고, 같은 서버가 `webapp/`의
모바일 웹앱을 `/`에서 서빙합니다.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/dev_bootstrap.py              # alembic upgrade head + 데모 시드
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- 웹앱: http://localhost:8000/
- API 문서: http://localhost:8000/docs
- 상태: http://localhost:8000/api/v1/health

테스트: `pytest -q` (20개). 마이그레이션: `alembic upgrade head`.
운영 설정은 `.env.example`의 production 항목을 참고하세요(JWT_SECRET, PostgreSQL, CORS 제한 필수).
