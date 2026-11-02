"""Storage: SQLite on your computer, PostgreSQL in the cloud.

Pass a file path (or "sqlite:///file.db") for SQLite, or a "postgresql://..." URL
for PostgreSQL. Amounts are stored as whole ngwee (1 kwacha = 100 ngwee) so totals
never pick up floating-point errors; they are returned in kwacha.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from .parser import Entry

_TABLES = """
CREATE TABLE IF NOT EXISTS merchants (
    phone            TEXT PRIMARY KEY,
    name             TEXT,
    consented        INTEGER NOT NULL DEFAULT 0,
    pending_delete   INTEGER NOT NULL DEFAULT 0,
    last_inbound_at  TEXT,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    id            {pk},
    merchant      TEXT NOT NULL REFERENCES merchants(phone) ON DELETE CASCADE,
    provider      TEXT NOT NULL,
    direction     TEXT NOT NULL CHECK (direction IN ('in','out')),
    amount_ngwee  BIGINT NOT NULL,
    counterparty  TEXT,
    reference     TEXT,
    note          TEXT,
    occurred_at   TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    raw           TEXT,
    confidence    TEXT NOT NULL DEFAULT 'high',
    deleted       INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_ref
    ON entries(merchant, provider, reference) WHERE reference <> '' AND deleted = 0;
CREATE INDEX IF NOT EXISTS by_day ON entries(merchant, occurred_at);
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   TEXT PRIMARY KEY,
    received_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summary_log (
    phone    TEXT NOT NULL,
    day      TEXT NOT NULL,
    sent_at  TEXT NOT NULL,
    PRIMARY KEY (phone, day)
);
"""


class DuplicateEntry(Exception):
    pass


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Ledger:
    def __init__(self, url: str = "kwacha_books.db"):
        self.url = url
        self.pg = url.startswith(("postgres://", "postgresql://"))
        self._lock = threading.RLock()
        self._connect()
        pk = "BIGSERIAL PRIMARY KEY" if self.pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        for stmt in _TABLES.format(pk=pk).split(";"):
            if stmt.strip():
                self._run(stmt)

    # ----- connection -----
    def _connect(self):
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            self.conn = psycopg.connect(self.url, row_factory=dict_row, autocommit=True)
            self._integrity = psycopg.errors.UniqueViolation
            self._retryable = (psycopg.OperationalError, psycopg.InterfaceError)
        else:
            path = self.url[len("sqlite:///"):] if self.url.startswith("sqlite:///") else self.url
            self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._integrity = sqlite3.IntegrityError
            self._retryable = ()

    def _run(self, sql: str, params: tuple = ()):
        if self.pg:
            sql = sql.replace("?", "%s")
        with self._lock:
            try:
                return self.conn.execute(sql, params)
            except self._retryable:
                # the cloud database dropped an idle connection: reconnect once and retry
                self._connect()
                return self.conn.execute(sql, params)

    def _one(self, sql, params=()):
        row = self._run(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql, params=()):
        return [dict(r) for r in self._run(sql, params).fetchall()]

    @staticmethod
    def _entry(row: dict) -> dict:
        row["amount"] = row.pop("amount_ngwee") / 100
        return row

    # ----- merchants -----
    def merchant(self, phone: str) -> Optional[dict]:
        return self._one("SELECT * FROM merchants WHERE phone = ?", (phone,))

    def ensure_merchant(self, phone: str, now: Optional[datetime] = None) -> dict:
        now = now or datetime.now()
        self._run("INSERT INTO merchants(phone, created_at) VALUES (?, ?) ON CONFLICT (phone) DO NOTHING",
                  (phone, _iso(now)))
        return self.merchant(phone)

    def touch(self, phone: str, now: datetime) -> None:
        """Remember when the merchant last messaged us (WhatsApp's 24-hour reply window)."""
        self._run("UPDATE merchants SET last_inbound_at = ? WHERE phone = ?", (_iso(now), phone))

    def set_consent(self, phone: str, name: str = "") -> None:
        self._run("UPDATE merchants SET consented = 1, name = COALESCE(NULLIF(?, ''), name) WHERE phone = ?",
                  (name, phone))

    def set_pending_delete(self, phone: str, pending: bool) -> None:
        self._run("UPDATE merchants SET pending_delete = ? WHERE phone = ?", (1 if pending else 0, phone))

    def forget(self, phone: str) -> None:
        """Delete everything held about a merchant (data-protection request)."""
        self._run("DELETE FROM entries WHERE merchant = ?", (phone,))
        self._run("DELETE FROM summary_log WHERE phone = ?", (phone,))
        self._run("DELETE FROM merchants WHERE phone = ?", (phone,))

    def all_merchants(self) -> list[dict]:
        return self._all("SELECT * FROM merchants WHERE consented = 1 ORDER BY created_at")

    # ----- entries -----
    def add(self, phone: str, e: Entry, now: Optional[datetime] = None) -> int:
        now = now or datetime.now()
        if e.reference and self._one(
                "SELECT id FROM entries WHERE merchant=? AND provider=? AND reference=? AND deleted=0",
                (phone, e.provider, e.reference)):
            raise DuplicateEntry(e.reference)
        try:
            row = self._one(
                """INSERT INTO entries(merchant, provider, direction, amount_ngwee, counterparty, reference,
                                       note, occurred_at, recorded_at, raw, confidence)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (phone, e.provider, e.direction, round(e.amount * 100), e.counterparty, e.reference, e.note,
                 _iso(e.occurred_at or now), _iso(now), e.raw, e.confidence))
        except self._integrity:
            # the same SMS arrived twice at the same moment (e.g. two server workers)
            raise DuplicateEntry(e.reference)
        return row["id"]

    def undo_last(self, phone: str) -> Optional[dict]:
        row = self._one("SELECT * FROM entries WHERE merchant=? AND deleted=0 ORDER BY id DESC LIMIT 1", (phone,))
        if row:
            self._run("UPDATE entries SET deleted=1 WHERE id=?", (row["id"],))
            return self._entry(row)
        return None

    def between(self, phone: str, start: date, end: date) -> list[dict]:
        """Entries with start <= day < end."""
        rows = self._all(
            """SELECT * FROM entries WHERE merchant=? AND deleted=0
               AND occurred_at >= ? AND occurred_at < ? ORDER BY occurred_at, id""",
            (phone, start.isoformat(), end.isoformat()))
        return [self._entry(r) for r in rows]

    def day(self, phone: str, d: date) -> list[dict]:
        return self.between(phone, d, d + timedelta(days=1))

    # ----- webhook bookkeeping -----
    def first_time_seen(self, message_id: str, now: Optional[datetime] = None) -> bool:
        """True the first time a WhatsApp message id arrives; False on Meta's retries."""
        cur = self._run("INSERT INTO processed_messages(message_id, received_at) VALUES (?, ?) "
                        "ON CONFLICT (message_id) DO NOTHING", (message_id, _iso(now or datetime.now())))
        return cur.rowcount == 1

    def claim_summary(self, phone: str, d: date, now: datetime) -> bool:
        """True if no summary has been sent for this merchant and day yet (and claims it)."""
        cur = self._run("INSERT INTO summary_log(phone, day, sent_at) VALUES (?, ?, ?) "
                        "ON CONFLICT (phone, day) DO NOTHING", (phone, d.isoformat(), _iso(now)))
        return cur.rowcount == 1

    def release_summary(self, phone: str, d: date) -> None:
        self._run("DELETE FROM summary_log WHERE phone = ? AND day = ?", (phone, d.isoformat()))

    def stats(self) -> dict:
        return {
            "merchants": self._one("SELECT COUNT(*) AS n FROM merchants")["n"],
            "consented": self._one("SELECT COUNT(*) AS n FROM merchants WHERE consented = 1")["n"],
            "entries": self._one("SELECT COUNT(*) AS n FROM entries WHERE deleted = 0")["n"],
            "needs_check": self._one("SELECT COUNT(*) AS n FROM entries WHERE deleted = 0 AND confidence = 'check'")["n"],
        }
