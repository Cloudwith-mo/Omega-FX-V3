"""Persistent journal for idempotent order placement."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class JournalEntry:
    client_order_id: str
    broker_order_id: Optional[str]
    status: str
    payload: dict
    created_at: str


class OrderJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._local = threading.local()
        self._conn()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    client_order_id TEXT PRIMARY KEY,
                    broker_order_id TEXT,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
            self._local.conn = conn
        return conn

    def record_intent(self, client_order_id: str, payload: dict) -> bool:
        created_at = datetime.utcnow().isoformat()
        try:
            conn = self._conn()
            conn.execute(
                "INSERT INTO orders (client_order_id, broker_order_id, status, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (client_order_id, None, "intent", json.dumps(payload, default=str), created_at),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def mark_submitted(self, client_order_id: str, broker_order_id: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE orders SET broker_order_id = ?, status = ? WHERE client_order_id = ?",
            (broker_order_id, "submitted", client_order_id),
        )
        conn.commit()

    def mark_status(self, client_order_id: str, status: str) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE orders SET status = ? WHERE client_order_id = ?",
            (status, client_order_id),
        )
        conn.commit()

    def get(self, client_order_id: str) -> Optional[JournalEntry]:
        conn = self._conn()
        row = conn.execute(
            "SELECT client_order_id, broker_order_id, status, payload, created_at "
            "FROM orders WHERE client_order_id = ?",
            (client_order_id,),
        ).fetchone()
        if not row:
            return None
        payload = json.loads(row[3])
        return JournalEntry(
            client_order_id=row[0],
            broker_order_id=row[1],
            status=row[2],
            payload=payload,
            created_at=row[4],
        )

    def list_open(self) -> list[JournalEntry]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT client_order_id, broker_order_id, status, payload, created_at "
            "FROM orders WHERE status IN ('intent', 'submitted', 'open', 'partial')"
        ).fetchall()
        entries: list[JournalEntry] = []
        for row in rows:
            entries.append(
                JournalEntry(
                    client_order_id=row[0],
                    broker_order_id=row[1],
                    status=row[2],
                    payload=json.loads(row[3]),
                    created_at=row[4],
                )
            )
        return entries

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            return
        conn.close()
        self._local.conn = None
