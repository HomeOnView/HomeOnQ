"""로컬 개발용 마이그레이션 + 시드 부트스트랩.

    cd api-server
    python scripts/dev_bootstrap.py            # alembic upgrade head + 데모 시드
    python scripts/dev_bootstrap.py --reset    # 데모 활동 데이터 초기화 후 재시드
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.demo_seed import seed_demo  # noqa: E402


def run_migrations() -> None:
    env = {**os.environ, "DATABASE_URL": settings.database_url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="데모 행동/낙상/리포트 데이터를 지우고 다시 만든다")
    parser.add_argument("--skip-migrate", action="store_true")
    args = parser.parse_args()

    if not args.skip_migrate:
        print(f"[1/2] alembic upgrade head  (DATABASE_URL={settings.database_url})")
        run_migrations()

    print("[2/2] 데모 데이터 시드")
    with SessionLocal() as db:
        result = seed_demo(db, reset=args.reset)
    print(f"  보호자: {result['guardian']['email']}")
    print(f"  어르신: {result['senior']['display_name']} ({result['senior']['id']})")
    print(f"  기기  : {', '.join(d['device_id'] for d in result['devices'])}")
    print(f"  리포트: {result['report']['report_date']} score={result['report']['score']} ({result['report']['risk_label']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
