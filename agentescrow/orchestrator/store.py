"""SQLite persistence for jobs and their event timeline.

Jobs are stored as JSON documents (the pydantic ``Job`` model) next to an indexed state
column. Saves are optimistic: pass ``expected_state`` and the write only lands if the job
is still in that state, so two concurrent requests cannot both move the same job.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agentescrow.domain.models import Job, JobState, utc_now

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id     TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL,
    ts         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL,
    data       TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events (job_id, id);
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id    TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    received_at TEXT NOT NULL,
    job_id      TEXT,
    outcome     TEXT NOT NULL DEFAULT ''
);
"""

# Lookup columns added after the first release; ``_migrate`` adds them to older databases.
_LOOKUP_COLUMNS = ("order_id", "authorization_id", "capture_id")


class JobNotFound(KeyError):
    pass


class StaleJobError(RuntimeError):
    """The job changed state since it was loaded; reload and retry."""


class JobStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._write_lock = threading.Lock()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)
        logger.info("Job store ready at %s", path)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add the PayPal-id lookup columns (and indexes) if this database predates them."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in _LOOKUP_COLUMNS:
            if column not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_jobs_{column} ON jobs ({column})")
        # Back-fill rows written before the columns existed.
        for row in conn.execute("SELECT job_id, data FROM jobs WHERE order_id IS NULL AND authorization_id IS NULL"):
            job = Job.model_validate_json(row["data"])
            if job.order_id or job.authorization_id or job.capture_id:
                conn.execute(
                    "UPDATE jobs SET order_id = ?, authorization_id = ?, capture_id = ? WHERE job_id = ?",
                    (job.order_id, job.authorization_id, job.capture_id, job.job_id),
                )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:  # commit or roll back
                yield conn
        finally:
            conn.close()

    # --------------------------------------------------------------------- jobs --
    def create(self, job: Job) -> Job:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, state, data, created_at, updated_at, order_id, authorization_id, capture_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id, job.state.value, job.model_dump_json(), job.created_at.isoformat(),
                    job.updated_at.isoformat(), job.order_id, job.authorization_id, job.capture_id,
                ),
            )  # fmt: skip
        return job

    def get(self, job_id: str) -> Job:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return Job.model_validate_json(row["data"])

    def list(self, limit: int = 100, states: list[JobState] | None = None) -> list[Job]:
        sql, params = "SELECT data FROM jobs", []
        if states:
            sql += f" WHERE state IN ({','.join('?' * len(states))})"
            params += [state.value for state in states]
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, [*params, limit]).fetchall()
        return [Job.model_validate_json(row["data"]) for row in rows]

    def find_by(self, column: str, value: str) -> Job | None:
        """Find the job holding a PayPal id. ``column`` is order_id, authorization_id or capture_id."""
        if column not in _LOOKUP_COLUMNS:
            raise ValueError(f"Cannot look up jobs by {column!r}")
        if not value:
            return None
        with self._connect() as conn:
            row = conn.execute(f"SELECT data FROM jobs WHERE {column} = ? LIMIT 1", (value,)).fetchone()
        return Job.model_validate_json(row["data"]) if row else None

    def counts_by_state(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT state, COUNT(*) AS n FROM jobs GROUP BY state").fetchall()
        return {row["state"]: row["n"] for row in rows}

    # ----------------------------------------------------------------- webhooks --
    def record_webhook(self, event_id: str, event_type: str, job_id: str | None) -> bool:
        """Remember a webhook event. Returns False if this event id was already processed (a PayPal retry)."""
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO webhook_events (event_id, event_type, received_at, job_id) VALUES (?, ?, ?, ?)",
                (event_id, event_type, utc_now().isoformat(), job_id),
            )
            return cursor.rowcount == 1

    def set_webhook_outcome(self, event_id: str, outcome: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute("UPDATE webhook_events SET outcome = ? WHERE event_id = ?", (outcome[:200], event_id))

    def save(self, job: Job, *, expected_state: JobState | None = None) -> Job:
        """Persist ``job``. With ``expected_state`` the write fails if the stored state differs."""
        job.updated_at = utc_now()
        sql = (
            "UPDATE jobs SET state = ?, data = ?, updated_at = ?, order_id = ?, authorization_id = ?, capture_id = ?"
            " WHERE job_id = ?"
        )
        params: list[Any] = [
            job.state.value, job.model_dump_json(), job.updated_at.isoformat(),
            job.order_id, job.authorization_id, job.capture_id, job.job_id,
        ]  # fmt: skip
        if expected_state is not None:
            sql += " AND state = ?"
            params.append(expected_state.value)
        with self._write_lock, self._connect() as conn:
            updated = conn.execute(sql, params).rowcount
        if updated == 0:
            if expected_state is not None:
                raise StaleJobError(f"Job {job.job_id} is no longer in state {expected_state.value}")
            raise JobNotFound(job.job_id)
        return job

    # ------------------------------------------------------------------- events --
    def add_event(self, job_id: str, kind: str, message: str, data: dict[str, Any] | None = None) -> int:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO events (job_id, ts, kind, message, data) VALUES (?, ?, ?, ?, ?)",
                (job_id, utc_now().isoformat(), kind, message, json.dumps(data or {}, default=str)),
            )
            return int(cursor.lastrowid)

    def events(self, job_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, kind, message, data FROM events WHERE job_id = ? AND id > ? ORDER BY id",
                (job_id, after_id),
            ).fetchall()
        return [
            {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "message": r["message"], "data": json.loads(r["data"])}
            for r in rows
        ]
