#!/usr/bin/env bash
# 전체 검증: 백엔드 테스트 → 파이프라인 테스트 → E2E → (node가 있으면) 웹앱/Expo 검사
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FAIL=0

PY="${PYTHON:-python3}"
if [ -x "$ROOT/api-server/.venv/bin/python" ]; then PY="$ROOT/api-server/.venv/bin/python"; fi

echo "== 1) 백엔드 테스트"
(cd api-server && "$PY" -m pytest -q) || FAIL=1

echo "== 2) 파이프라인 테스트"
(cd camera-analysis && "$PY" -m pytest -q) || FAIL=1

echo "== 3) 엔드투엔드(분석→HTTP→DB→조회)"
"$PY" scripts/e2e_demo.py || FAIL=1

if command -v node >/dev/null 2>&1; then
  echo "== 4) 웹앱 런타임 스모크(jsdom 필요: npm i jsdom)"
  node scripts/webapp_smoke.test.mjs || FAIL=1
  echo "== 5) Expo 정적 검사"
  node scripts/mobile_app_check.mjs || FAIL=1
else
  echo "!! node가 없어 4)5)는 건너뜁니다 (웹앱/Expo 검증)"
fi

if [ "$FAIL" -eq 0 ]; then echo "✅ 전체 검증 통과"; else echo "❌ 일부 검증 실패"; fi
exit "$FAIL"
