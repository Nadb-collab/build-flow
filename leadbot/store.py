"""SQLite record of what the bot has handled, so each customer message is answered once."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS handled (
                lead TEXT NOT NULL,
                message_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reply TEXT NOT NULL,
                reason TEXT NOT NULL,
                dry_run INTEGER NOT NULL,
                handled_at TEXT NOT NULL,
                PRIMARY KEY (lead, message_id)
            );
            CREATE TABLE IF NOT EXISTS escalated_leads (
                lead TEXT PRIMARY KEY,
                escalated_at TEXT NOT NULL
            );
            """
        )

    def is_handled(self, lead: str, message_id: str, include_dry_run: bool = False) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM handled WHERE lead = ? AND message_id = ? AND dry_run <= ?",
            (lead, message_id, int(include_dry_run)),
        ).fetchone()
        return row is not None

    def auto_reply_count(self, lead: str) -> int:
        (n,) = self._db.execute(
            "SELECT COUNT(*) FROM handled WHERE lead = ? AND action = 'reply' AND dry_run = 0",
            (lead,),
        ).fetchone()
        return n

    def record(self, lead: str, message_id: str, action: str, reply: str, reason: str, dry_run: bool) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO handled VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead, message_id, action, reply, reason, int(dry_run), _now()),
        )
        self._db.commit()

    def is_escalated(self, lead: str) -> bool:
        return self._db.execute("SELECT 1 FROM escalated_leads WHERE lead = ?", (lead,)).fetchone() is not None

    def mark_escalated(self, lead: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO escalated_leads VALUES (?, ?)", (lead, _now()))
        self._db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
