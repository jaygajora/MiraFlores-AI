"""Append-only event log in SQLite.

Every human or system action on the workpaper is one immutable row. Current
state is a projection of the log (state.py). Consequences:
  * nothing is ever overwritten: an "edit" is a new event that supersedes an older one
  * history, undo, "what changed since I last looked" and version compare are
    queries over the log
  * each row carries the hash of the previous row, so the record that was
    sealed at filing can be shown to be the record that exists later
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    id         TEXT NOT NULL UNIQUE,
    at         TEXT NOT NULL,          -- wall-clock time the event was recorded
    sim_at     TEXT NOT NULL,          -- workpaper clock (season replay) when it happened
    actor      TEXT NOT NULL,          -- staff id, client user id, or 'system'
    kind       TEXT NOT NULL,
    target     TEXT,                   -- primary ref the event is about
    batch      TEXT,                   -- groups events created by one bulk action
    data       TEXT NOT NULL,          -- JSON payload
    prev_hash  TEXT NOT NULL,
    hash       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS events_target ON events(target);
CREATE TABLE IF NOT EXISTS files (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    mime       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    sha256     TEXT NOT NULL,
    content    BLOB NOT NULL,
    at         TEXT NOT NULL,
    actor      TEXT NOT NULL
);
"""

GENESIS = "0" * 64
log = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class EventStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._listeners: list = []

    # ------------------------------------------------------------------ writes
    def append(self, *, actor: str, kind: str, sim_at: str, target: str | None = None,
               data: dict | None = None, batch: str | None = None, event_id: str | None = None) -> dict:
        with self._lock:
            row = self._conn.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            eid = event_id or f"e-{uuid.uuid4().hex[:12]}"
            at = now_iso()
            payload = json.dumps(data or {}, sort_keys=True, separators=(",", ":"))
            h = hashlib.sha256("|".join([prev, eid, at, sim_at, actor, kind, target or "", batch or "", payload]).encode()).hexdigest()
            cur = self._conn.execute(
                "INSERT INTO events(id, at, sim_at, actor, kind, target, batch, data, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (eid, at, sim_at, actor, kind, target, batch, payload, prev, h))
            ev = {"seq": cur.lastrowid, "id": eid, "at": at, "sim_at": sim_at, "actor": actor, "kind": kind,
                  "target": target, "batch": batch, "data": data or {}, "prev_hash": prev, "hash": h}
        for fn in list(self._listeners):
            try:
                fn(ev)
            except Exception:  # listeners must never break a write
                log.exception("event listener failed")
        return ev

    def append_many(self, items: Iterable[dict], *, actor: str, sim_at: str, batch: str | None = None) -> list[dict]:
        batch = batch or f"b-{uuid.uuid4().hex[:10]}"
        with self._lock:
            return [self.append(actor=actor, sim_at=sim_at, batch=batch, **it) for it in items]

    def put_file(self, name: str, mime: str, content: bytes, actor: str) -> dict:
        fid = f"f-{uuid.uuid4().hex[:12]}"
        sha = hashlib.sha256(content).hexdigest()
        with self._lock:
            self._conn.execute("INSERT INTO files(id,name,mime,size,sha256,content,at,actor) VALUES (?,?,?,?,?,?,?,?)",
                               (fid, name, mime, len(content), sha, content, now_iso(), actor))
        return {"id": fid, "name": name, "mime": mime, "size": len(content), "sha256": sha}

    def get_file(self, fid: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["data"] = json.loads(d["data"])
        return d

    def all(self) -> list[dict]:
        with self._lock:
            return [self._row(r) for r in self._conn.execute("SELECT * FROM events ORDER BY seq")]

    def since(self, seq: int) -> list[dict]:
        with self._lock:
            return [self._row(r) for r in self._conn.execute("SELECT * FROM events WHERE seq>? ORDER BY seq", (seq,))]

    def head(self) -> int:
        with self._lock:
            r = self._conn.execute("SELECT MAX(seq) AS s FROM events").fetchone()
            return r["s"] or 0

    def verify_chain(self) -> dict:
        prev = GENESIS
        n = 0
        for r in self._conn.execute("SELECT * FROM events ORDER BY seq"):
            h = hashlib.sha256("|".join([prev, r["id"], r["at"], r["sim_at"], r["actor"], r["kind"], r["target"] or "",
                                         r["batch"] or "", r["data"]]).encode()).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                return {"ok": False, "broken_at": r["seq"], "checked": n}
            prev = r["hash"]
            n += 1
        return {"ok": True, "checked": n, "head": prev}

    def subscribe(self, fn) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def reset(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM events")
            self._conn.execute("DELETE FROM files")
            self._conn.execute("DELETE FROM sqlite_sequence WHERE name='events'")
