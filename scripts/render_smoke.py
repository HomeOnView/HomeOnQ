"""Render 무료 배포 설정 점검: render.yaml의 빌드/시작 명령을 그대로 흉내 내 검증한다.

    python scripts/render_smoke.py

1) `APP_ENV=demo` + SQLite + 자동 생성 JWT_SECRET 환경에서
   `cd api-server && python scripts/dev_bootstrap.py` 를 **두 번** 실행해 멱등성 확인
   (무료 플랜은 슬립·재배포 때마다 파일시스템이 초기화되므로 매 기동마다 이 경로를 탄다)
2) `uvicorn app.main:app --host 0.0.0.0 --port $PORT` 로 서버를 띄워
   웹앱(/), 상태(/api/v1/health), 데모 설정(/api/v1/demo/config), 로그인,
   분석 테스트(/api/v1/demo/simulate), 알림까지 실제 HTTP로 확인
3) 모든 요청이 끝나면 서버를 종료한다(상시 데몬을 남기지 않는다).
"""
from __future__ import annotations

import base64
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api-server"
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_health(base: str, timeout: float = 60.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(base + "/api/v1/health", timeout=2.0).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


class Checker:
    def __init__(self) -> None:
        self.results: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        self.results.append((bool(ok), name, detail))
        print(("  ✅ " if ok else "  ❌ ") + name + (f" — {detail}" if detail else ""))
        return ok

    def summary(self) -> int:
        passed = sum(1 for ok, _, _ in self.results if ok)
        print(f"\n결과: {passed}/{len(self.results)} 통과")
        for ok, name, detail in self.results:
            if not ok:
                print(f"  실패: {name} {detail}")
        return 0 if passed == len(self.results) else 1


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="homeonq-render-"))
    db_path = tmpdir / "homeonq_dev.db"
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    # render.yaml의 envVars와 동일한 구성
    env = {
        **os.environ,
        "APP_ENV": "demo",
        "DATABASE_URL": f"sqlite:///{db_path}",
        "AUTO_CREATE_SCHEMA": "true",
        "JWT_SECRET": base64.b64encode(secrets.token_bytes(32)).decode(),
        "CORS_ORIGINS": '["*"]',
        "ACCESS_TOKEN_MINUTES": "60",
        "PORT": str(port),
        "PYTHONUNBUFFERED": "1",
    }
    checker = Checker()
    server: subprocess.Popen | None = None
    log_file = open(tmpdir / "server.log", "w", encoding="utf-8")
    print(f"임시 DB: {db_path}\n서버: {base}\n")

    try:
        print("[1/4] 기동 명령: python scripts/dev_bootstrap.py (1회차)")
        first = subprocess.run([PY, "scripts/dev_bootstrap.py"], cwd=API_DIR, env=env,
                               capture_output=True, text=True)
        checker.check(first.returncode == 0, "부트스트랩 1회차 (마이그레이션+시드)",
                      (first.stdout or first.stderr).strip().splitlines()[-1] if (first.stdout or first.stderr) else "")
        if first.returncode != 0:
            print(first.stdout, first.stderr)
            return checker.summary()

        print("[2/4] 기동 명령: python scripts/dev_bootstrap.py (2회차 = 슬립/재배포)")
        second = subprocess.run([PY, "scripts/dev_bootstrap.py"], cwd=API_DIR, env=env,
                                capture_output=True, text=True)
        checker.check(second.returncode == 0, "부트스트랩 2회차 (멱등)", 
                      (second.stdout or second.stderr).strip().splitlines()[-1] if (second.stdout or second.stderr) else "")
        emails = [line for line in first.stdout.splitlines() if "보호자:" in line]
        emails2 = [line for line in second.stdout.splitlines() if "보호자:" in line]
        checker.check(emails and emails == emails2, "재시드 후에도 동일 데모 계정", (emails2[0].strip() if emails2 else ""))

        print("[3/4] 기동 명령: uvicorn app.main:app --host 0.0.0.0 --port $PORT")
        server = subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port),
             "--log-level", "warning"],
            cwd=API_DIR, env=env, stdout=log_file, stderr=log_file,
        )
        up = wait_health(base)
        checker.check(up, "헬스체크 /api/v1/health 200", base)
        if not up:
            print((tmpdir / "server.log").read_text()[-2000:])
            return checker.summary()

        import httpx

        health = httpx.get(base + "/api/v1/health", timeout=10).json()
        checker.check(health.get("status") == "ok" and health.get("environment") == "demo"
                      and health.get("database") == "ok" and health.get("webapp") is True,
                      "health: status/environment/database/webapp", str(health))

        index = httpx.get(base + "/", timeout=10)
        checker.check(index.status_code == 200 and "HOMEONQ" in index.text, "웹앱(/) 서빙 · HOMEONQ 표기",
                      f"{len(index.text)} bytes")
        checker.check(httpx.get(base + "/app.js", timeout=10).status_code == 200
                      and httpx.get(base + "/styles.css", timeout=10).status_code == 200,
                      "정적 자산(/app.js, /styles.css)")

        cfg = httpx.get(base + "/api/v1/demo/config", timeout=10).json()
        checker.check(cfg.get("enabled") is True and len(cfg.get("scenarios") or []) == 4,
                      "'분석 테스트' 탭 활성(demo/config enabled)",
                      f"scenarios={cfg.get('scenarios')}")
        cred = cfg.get("credentials") or {}
        checker.check(cred.get("email") == "demo@homeonq.kr", "데모 계정 자동 입력값", str(cred.get("email")))

        print("[4/4] 로그인 → 분석 테스트(/demo/simulate)")
        login = httpx.post(base + "/api/v1/auth/login", timeout=15,
                           json={"email": cred.get("email"), "password": cred.get("password")})
        checker.check(login.status_code == 200, "보호자 로그인", login.text[:80] if login.status_code != 200 else "")
        if login.status_code != 200:
            return checker.summary()
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}

        seniors = httpx.get(base + "/api/v1/guardians/me/seniors", headers=headers, timeout=15).json()
        sid = seniors["items"][0]["id"]

        sim = httpx.post(base + "/api/v1/demo/simulate", headers=headers,
                         json={"scenario": "fall", "senior_id": sid}, timeout=120)
        sim_ok = sim.status_code == 200 and (sim.json().get("sent") or {}).get("report") == 1
        checker.check(sim_ok, "/demo/simulate 낙상 시나리오", f"status={sim.status_code}")
        if sim.status_code == 200:
            sent = sim.json().get("sent", {})
            checker.check(sent.get("fall") == 1 and sent.get("behavior", 0) >= 1,
                          "파이프라인 분석 → 기기 API 전송", f"행동 {sent.get('behavior')} · 낙상 {sent.get('fall')}")

        alerts = httpx.get(base + "/api/v1/guardians/me/alerts", headers=headers, timeout=15).json()
        checker.check(len(alerts.get("items") or []) >= 1, "낙상 알림 생성", f"{len(alerts.get('items') or [])}건")

        latest = httpx.get(f"{base}/api/v1/seniors/{sid}/daily-reports/latest", headers=headers, timeout=15).json()
        checker.check(latest.get("score") is not None, "리포트 갱신", f"{latest.get('score')}점 · {latest.get('risk_label')}")

        reset = httpx.post(base + "/api/v1/demo/reset", headers=headers, timeout=60)
        checker.check(reset.status_code == 200, "데모 초기화(/demo/reset)", f"status={reset.status_code}")

        return checker.summary()
    except Exception:  # pragma: no cover
        traceback.print_exc()
        return 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        log_file.close()
        print("서버를 종료했습니다.")


if __name__ == "__main__":
    raise SystemExit(main())
