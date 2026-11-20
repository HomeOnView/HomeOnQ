"""엔드투엔드 검증: 샘플 분석 → 실제 HTTP 텔레메트리 전송 → DB 저장 → 보호자 API 조회.

임시 SQLite DB에 Alembic 마이그레이션과 데모 시드를 적용하고, 실제 uvicorn 서버를
잠깐 띄운 뒤 `camera-analysis` 파이프라인이 HTTP로 이벤트를 보낸다. 마지막에
보호자 API 응답과 DB 행 수를 확인하고 서버를 종료한다.

    python scripts/e2e_demo.py            # 전체 검증
    python scripts/e2e_demo.py --keep     # 임시 DB/로그 보존
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api-server"
CAMERA_DIR = ROOT / "camera-analysis"
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_health(base: str, timeout: float = 40.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(base + "/api/v1/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


class Checker:
    def __init__(self):
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    tmpdir = Path(tempfile.mkdtemp(prefix="homeonq-e2e-"))
    db_path = tmpdir / "e2e.db"
    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "APP_ENV": "development",
        "AUTO_CREATE_SCHEMA": "false",
        "PYTHONUNBUFFERED": "1",
    }
    checker = Checker()
    server: subprocess.Popen | None = None
    log_file = open(tmpdir / "server.log", "w", encoding="utf-8")

    print(f"작업 DB: {db_path}")
    print(f"서버: {base}\n")

    try:
        # 1) 마이그레이션 + 시드
        print("[1/6] Alembic 마이그레이션")
        proc = subprocess.run([PY, "-m", "alembic", "upgrade", "head"], cwd=API_DIR, env=env,
                              capture_output=True, text=True)
        checker.check(proc.returncode == 0, "alembic upgrade head", (proc.stderr or proc.stdout).strip()[-160:])

        print("[2/6] 데모 시드")
        proc = subprocess.run([PY, "scripts/dev_bootstrap.py", "--skip-migrate"], cwd=API_DIR, env=env,
                              capture_output=True, text=True)
        checker.check(proc.returncode == 0, "데모 시드 생성", (proc.stdout or proc.stderr).strip().splitlines()[-1] if (proc.stdout or proc.stderr) else "")
        if proc.returncode != 0:
            print(proc.stdout, proc.stderr)
            return checker.summary()

        # 2) 서버 기동
        print("[3/6] FastAPI 서버 기동")
        server = subprocess.Popen(
            [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=API_DIR, env=env, stdout=log_file, stderr=log_file,
        )
        up = wait_health(base, timeout=45)
        checker.check(up, "GET /api/v1/health 200", base)
        if not up:
            print((tmpdir / "server.log").read_text()[-2000:])
            return checker.summary()

        import httpx

        # 3) 웹앱/로그인
        print("[4/6] 웹앱 서빙 · 로그인 · 보호자 API")
        index = httpx.get(base + "/", timeout=10)
        checker.check(index.status_code == 200 and "홈온큐" in index.text, "모바일 웹앱(/) 서빙", f"{len(index.text)} bytes")
        checker.check(httpx.get(base + "/app.js", timeout=10).status_code == 200, "정적 자산(/app.js)")

        login = httpx.post(base + "/api/v1/auth/login", json={"email": "demo@homeonq.kr", "password": "homeonq-demo-2026"}, timeout=15)
        checker.check(login.status_code == 200, "보호자 로그인", login.text[:80] if login.status_code != 200 else "")
        if login.status_code != 200:
            return checker.summary()
        token = login.json()["access_token"]
        headers = {"Authorization": "Bearer " + token}

        seniors = httpx.get(base + "/api/v1/guardians/me/seniors", headers=headers, timeout=15).json()
        senior = seniors["items"][0]
        sid = senior["id"]
        checker.check(senior["display_name"] == "강O순 어르신", "어르신 프로필 조회", f"{senior['display_name']} / {senior.get('age')}세")

        # 4) 파이프라인 → HTTP 전송
        print("[5/6] 파이프라인 분석 → 실제 HTTP 전송")
        sys.path.insert(0, str(CAMERA_DIR))
        from onview.config import load_config  # noqa: E402
        from onview.local_queue import LocalEventQueue  # noqa: E402
        from onview.pipeline import PipelineRunner  # noqa: E402
        from onview.reporter import EventReporter  # noqa: E402
        from onview.skeleton_source import SCENARIO_FILES  # noqa: E402

        cfg = load_config(SERVER_MODE="HTTP", SERVER_URL=base,
                          DEVICE_TOKEN="demo-edge-token-homeonq-0001",
                          DB_PATH=str(tmpdir / "queue.db"),
                          SENIOR_NAME="강O순 어르신")
        queue = LocalEventQueue(cfg.DB_PATH)
        reporter = EventReporter(config=cfg, local_queue=queue)
        runner = PipelineRunner(config=cfg, reporter=reporter, queue=queue)

        sent_counts = {}
        for scenario in ("normal", "fall"):
            result = runner.run_file(str(CAMERA_DIR / "samples" / SCENARIO_FILES[scenario]))
            ok = all(result.sent["behavior"]) and result.sent["report"] is True
            if scenario == "fall":
                ok = ok and all(result.sent["fall"])
            sent_counts[scenario] = result
            checker.check(ok, f"{scenario} 시나리오 전송", f"행동 {len(result.behavior_payloads)} · 낙상 {len(result.fall_payloads)} · 점수 {result.score['score']}")

        fall_result = sent_counts["fall"]
        expected_score = fall_result.score["score"]
        expected_label = fall_result.score["risk_label"]
        runner.close()

        latest = httpx.get(f"{base}/api/v1/seniors/{sid}/daily-reports/latest", headers=headers, timeout=15).json()
        checker.check(latest.get("score") == expected_score, "리포트 DB 저장(점수 일치)",
                      f"API {latest.get('score')} vs 파이프라인 {expected_score}")
        checker.check(latest.get("risk_label") == expected_label and "낙상" in (latest.get("narrative") or ""),
                      "리포트 문장·등급 저장", f"{latest.get('risk_label')} / {len(latest.get('narrative') or '')}자")

        events = httpx.get(f"{base}/api/v1/seniors/{sid}/events?days=7", headers=headers, timeout=15).json()
        kinds = [e["kind"] for e in events.get("items", [])]
        checker.check(kinds.count("fall") >= 1 and kinds.count("behavior") >= 5, "이벤트 타임라인 조회",
                      f"낙상 {kinds.count('fall')} · 행동 {kinds.count('behavior')}")

        alerts = httpx.get(base + "/api/v1/guardians/me/alerts", headers=headers, timeout=15).json()
        checker.check(len(alerts.get("items", [])) >= 1, "낙상 알림 생성", f"미확인 알림 {len(alerts.get('items', []))}건")
        note_id = alerts["items"][0]["notification_id"]
        ack = httpx.post(f"{base}/api/v1/guardians/me/notifications/{note_id}/acknowledge", headers=headers, timeout=15)
        checker.check(ack.status_code == 200, "알림 확인 처리")

        patched = httpx.patch(f"{base}/api/v1/seniors/{sid}", headers=headers,
                              json={"height_cm": 159.0, "medical_conditions": ["당뇨", "고혈압", "척추측만증", "관절염"]}, timeout=15)
        checker.check(patched.status_code == 200 and patched.json()["height_cm"] == 159.0
                      and "관절염" in patched.json()["medical_conditions"], "프로필 수정(PATCH)")

        testfall = httpx.post(f"{base}/api/v1/seniors/{sid}/test-fall", headers=headers, timeout=15)
        checker.check(testfall.status_code == 201 and testfall.json()["is_test"] is True, "앱 낙상 테스트 트리거")

        sim = httpx.post(base + "/api/v1/demo/simulate", headers=headers,
                         json={"scenario": "wandering", "senior_id": sid}, timeout=90)
        sim_ok = sim.status_code == 200 and sim.json().get("sent", {}).get("report") == 1
        if not sim_ok and sim.status_code != 200:
            print("    simulate 응답:", sim.status_code, sim.text[:300])
        checker.check(sim_ok, "웹앱 시뮬레이션 API(ASGI)", f"탐지 {len(sim.json().get('analysis', {}).get('events', [])) if sim.status_code == 200 else 0}건")

        # 5) DB 직접 확인
        con = sqlite3.connect(db_path)
        rows = {
            "behavior_events": con.execute("select count(*) from behavior_events").fetchone()[0],
            "fall_events": con.execute("select count(*) from fall_events").fetchone()[0],
            "daily_reports": con.execute("select count(*) from daily_reports").fetchone()[0],
            "notifications": con.execute("select count(*) from notifications").fetchone()[0],
            "outbox_messages": con.execute("select count(*) from outbox_messages").fetchone()[0],
        }
        con.close()
        checker.check(rows["behavior_events"] >= 10 and rows["fall_events"] >= 2 and rows["daily_reports"] >= 1,
                      "SQLite 실제 저장 행 확인", json.dumps(rows, ensure_ascii=False))
        checker.check(rows["outbox_messages"] >= 2, "낙상 알림 Outbox 트랜잭션 저장", f"{rows['outbox_messages']}건")

        # 6) 재실행 안전성(중복 방지)
        print("[6/6] 멱등성 확인")
        import uuid
        from datetime import datetime, timezone
        payload = {
            "event_id": "e2e-dedup-" + uuid.uuid4().hex[:8],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "activity_type": "WALKING",
            "walking_steps": 1234,
            "confidence": 0.9,
        }
        dh = {"X-Device-Token": "demo-edge-token-homeonq-0001"}
        first = httpx.post(base + "/api/v1/device/behavior-events", headers=dh, json=payload, timeout=15)
        again = httpx.post(base + "/api/v1/device/behavior-events", headers=dh, json=payload, timeout=15)
        checker.check(first.status_code == 201 and again.status_code == 200 and again.json()["status"] == "duplicate",
                      "동일 이벤트 재전송 중복 방지")

    except Exception:
        traceback.print_exc()
        checker.results.append((False, "예외 발생", traceback.format_exc()[-200:]))
    finally:
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        log_file.close()
        if args.keep:
            print(f"\n로그/DB 보존: {tmpdir}")
        else:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    print("\n서버를 종료했습니다." if server else "")
    return checker.summary()


if __name__ == "__main__":
    raise SystemExit(main())
