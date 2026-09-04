"""Persistent SQLite-backed cache with per-entry TTL and SWR window.

Replaces the JSON-file cache. Survives restarts, supports composite
TTLs (today vs closed days), and lets us add columns later (e.g.,
account_id, fingerprint) without losing entries.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("costsight.cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
  key            TEXT PRIMARY KEY,
  value_json     TEXT NOT NULL,
  created_at     REAL NOT NULL,
  ttl_seconds    REAL NOT NULL,
  swr_seconds    REAL NOT NULL
);
"""


# Sweep fully-expired rows (past TTL + SWR) every N writes so the table can
# never grow without bound from keys that are written once and never read
# again — the plain get() path only ever read live rows, so dead rows for
# stale cache keys (e.g. rolling-window keys that change daily) accumulated
# forever. A periodic bulk DELETE amortises the cost across writes.
_SWEEP_EVERY_WRITES = 200


class SqliteCache:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._writes_since_sweep = 0
        # Per-thread connection cache. Opening a fresh connection (and
        # running PRAGMAs) on every op leaked connections — the `with conn`
        # context manager commits but does NOT close. We keep one connection
        # per thread instead, opened once with its PRAGMAs applied.
        self._local = threading.local()
        with self._lock:
            self._init_db()

    def _init_db(self) -> None:
        try:
            conn = self._get_conn()
            conn.executescript(_SCHEMA)
            conn.commit()
        except sqlite3.DatabaseError:
            log.warning("cache db at %s corrupt — recreating", self._path)
            # Drop the cached (possibly bad) connection before unlinking.
            old = getattr(self._local, "conn", None)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
                self._local.conn = None
            self._path.unlink(missing_ok=True)
            conn = self._get_conn()
            conn.executescript(_SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Return this thread's cached connection, opening it on first use.

        check_same_thread=False is safe here because each thread gets its
        own connection via threading.local; we never share a connection
        across threads. Writes are still serialized via self._lock.
        """
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False, timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def set(self, key: str, value: Any, ttl_seconds: float, swr_seconds: float = 0.0) -> None:
        payload = json.dumps(value, default=str)  # outside the lock by design
        now = time.time()
        conn = self._get_conn()
        do_sweep = False
        try:
            with self._lock, conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_entries(key, value_json, created_at, ttl_seconds, swr_seconds) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key, payload, now, ttl_seconds, swr_seconds),
                )
                self._writes_since_sweep += 1
                do_sweep = self._writes_since_sweep >= _SWEEP_EVERY_WRITES
                if do_sweep:
                    self._writes_since_sweep = 0
        except sqlite3.Error as exc:
            # FINDING 51: under multi-process contention (uvicorn --workers N, a
            # CLI sharing the db) or a long WAL checkpoint, a write can exceed
            # the busy timeout and raise. A failed *cache* write must never fail
            # the request — log and carry on uncached.
            log.warning("cache set failed for key=%s: %s", key, type(exc).__name__)
            return
        if do_sweep:
            self._sweep_expired()

    def _sweep_expired(self) -> None:
        """Delete rows past their TTL + SWR window — they can never be served."""
        now = time.time()
        conn = self._get_conn()
        try:
            with self._lock, conn:
                conn.execute(
                    "DELETE FROM cache_entries "
                    "WHERE (? - created_at) >= (ttl_seconds + swr_seconds)",
                    (now,),
                )
        except sqlite3.OperationalError as exc:
            # A sweep is best-effort housekeeping; never fail a write because
            # of lock contention here.
            log.warning("cache sweep skipped: %s", exc)

    def get(self, key: str) -> Optional[Any]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value_json, created_at, ttl_seconds, swr_seconds FROM cache_entries WHERE key=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        value_json, created_at, ttl_seconds, swr_seconds = row
        age = time.time() - created_at
        if age >= ttl_seconds:
            # Past the fresh window. If also past the SWR grace window the row
            # is permanently dead — lazy-delete it so a never-re-read key can't
            # linger forever (bounds table growth alongside the periodic sweep).
            if age >= (ttl_seconds + swr_seconds):
                try:
                    with self._lock, conn:
                        conn.execute(
                            "DELETE FROM cache_entries WHERE key=? AND created_at=?",
                            (key, created_at),
                        )
                except sqlite3.OperationalError:
                    pass
            return None
        return json.loads(value_json)

    def get_swr(self, key: str) -> tuple[Optional[Any], bool]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value_json, created_at, ttl_seconds, swr_seconds FROM cache_entries WHERE key=?",
            (key,),
        ).fetchone()
        if not row:
            return None, True
        value_json, created_at, ttl, swr = row
        age = time.time() - created_at
        if age < ttl:
            return json.loads(value_json), False
        if age < (ttl + swr):
            return json.loads(value_json), True
        # Past SWR window — lazy-delete, but only if this exact row is still
        # there. Best-effort: a failed delete must not fail the read.
        try:
            with self._lock, conn:
                conn.execute(
                    "DELETE FROM cache_entries WHERE key=? AND created_at=?",
                    (key, created_at),
                )
        except sqlite3.Error as exc:
            log.warning("cache get_swr lazy-delete failed for key=%s: %s", key, type(exc).__name__)
        return None, True

    def bust(self, prefix: str = "") -> int:
        conn = self._get_conn()
        with self._lock, conn:
            if prefix == "":
                # Empty prefix means "clear everything" — a plain DELETE
                # avoids a LIKE '%' full-table scan.
                cur = conn.execute("DELETE FROM cache_entries")
            else:
                # FINDING 25: range bounds use the key PRIMARY KEY index;
                # `LIKE 'prefix%'` does NOT (case_sensitive_like is OFF by
                # default), so it was a full-table scan over value_json-laden
                # rows while holding the global write lock. `￿` is a high
                # sentinel above any normal key char, giving an exclusive upper
                # bound on the prefix range.
                cur = conn.execute(
                    "DELETE FROM cache_entries WHERE key >= ? AND key < ?",
                    (prefix, prefix + "￿"),
                )
            return cur.rowcount
