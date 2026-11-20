#!/usr/bin/env bash
# 로컬 시연 서버: venv 준비 → 의존성 설치 → 마이그레이션/시드 → uvicorn
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/api-server"

PYTHON="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "▶ 가상환경 생성 (.venv)"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo "▶ 마이그레이션 + 데모 시드"
python scripts/dev_bootstrap.py

echo "▶ 서버 시작: http://localhost:${PORT:-8000}/"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload
