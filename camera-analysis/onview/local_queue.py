"""SQLite 기반 영구 보존 로컬 이벤트 큐.

서버 장애 시 이벤트를 잃지 않고, 네트워크가 돌아오면 중복 없이 재전송한다.
(안정성 명세서 `onview/local_queue.py` 구현)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .schemas import BehaviorEvent, DetectedEvent

logger = logging.getLogger(__name__)


class LocalEventQueue:
    def __init__(self, db_path: str | Path = "local_events.db"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS offline_events (
                    event_id TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    payload TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_offline_ts ON offline_events(timestamp)")
            conn.commit()

    def enqueue(self, event: BehaviorEvent | DetectedEvent, endpoint: str, payload: dict[str, Any] | None = None) -> None:
        event_id = getattr(event, "event_id", None) or f"{getattr(event, 'event_type', 'evt')}-{event.timestamp}"
        body = payload or getattr(event, "details", {}) or {}
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO offline_events (event_id, endpoint, event_type, timestamp, payload) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event_id, endpoint, getattr(event, "event_type", "UNKNOWN"), float(event.timestamp), json.dumps(body, default=str)),
                )
                conn.commit()
            logger.info("💾 [LocalQueue] 이벤트 적재 (ID: %s, endpoint: %s)", event_id, endpoint)
        except Exception as exc:  # pragma: no cover
            logger.error("❌ [LocalQueue] 적재 실패: %s", exc)

    def get_pending_events(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT event_id, endpoint, event_type, payload, retry_count FROM offline_events "
                    "ORDER BY timestamp ASC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                {
                    "event_id": r[0],
                    "endpoint": r[1],
                    "event_type": r[2],
                    "payload": json.loads(r[3]),
                    "retry_count": r[4],
                }
                for r in rows
            ]
        except Exception as exc:  # pragma: no cover
            logger.error("❌ [LocalQueue] 조회 실패: %s", exc)
            return []

    def remove_event(self, event_id: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM offline_events WHERE event_id = ?", (event_id,))
                conn.commit()
        except Exception as exc:  # pragma: no cover
            logger.error("❌ [LocalQueue] 삭제 실패: %s", exc)

    def mark_retry(self, event_id: str, error: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE offline_events SET retry_count = retry_count + 1, last_error = ? WHERE event_id = ?",
                (error[:500], event_id),
            )
            conn.commit()

    def count(self) -> int:
        try:
            with self._connect() as conn:
                return conn.execute("SELECT COUNT(*) FROM offline_events").fetchone()[0]
        except Exception:
            return 0

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM offline_events")
            conn.commit()
