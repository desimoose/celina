"""Transactional local session ledgers.

Each research session owns one SQLite database beneath the sessions root.
Connections are short-lived so a session can be closed and deleted without a
process-wide database handle keeping files open on Windows.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
import re
import shutil
import sqlite3
import uuid

import paths


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_DB_NAME = "ledger.sqlite3"
_SCHEMA_VERSION = 1


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class Session:
    session_id: str
    created_at: str
    last_active_at: str
    state: str
    content_recording: bool
    recovery_required: bool


@dataclass(frozen=True)
class DeleteResult:
    session_id: str
    deleted: bool
    errors: tuple[str, ...]


class SessionStore:
    def __init__(self, root=None):
        self.root = os.path.realpath(root or paths.sessions_dir())
        os.makedirs(self.root, exist_ok=True)

    def create(self, content_recording=True):
        session_id = str(uuid.uuid4())
        directory = self._directory(session_id, create=True)
        database = os.path.join(directory, _DB_NAME)
        now = _utc_now()
        with self._connection(database) as connection:
            self._create_schema(connection)
            connection.execute(
                """
                INSERT INTO session (
                    session_id, created_at, last_active_at, state,
                    content_recording, recovery_required
                ) VALUES (?, ?, ?, 'active', ?, 0)
                """,
                (session_id, now, now, 1 if content_recording else 0),
            )
        return self.get(session_id)

    def get(self, session_id):
        database = self._database(session_id)
        if not os.path.isfile(database):
            return None
        try:
            with self._connection(database) as connection:
                row = connection.execute(
                    """
                    SELECT session_id, created_at, last_active_at, state,
                           content_recording, recovery_required
                    FROM session
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.DatabaseError:
            return None
        return self._session_from_row(row) if row else None

    def list_recoverable(self):
        sessions = []
        for name in sorted(os.listdir(self.root)):
            if not _SAFE_ID.fullmatch(name):
                continue
            item = self.get(name)
            if item and item.state in {"active", "ending"}:
                sessions.append(replace(item, recovery_required=True))
        return sessions

    def mark_stopped(self, session_id):
        return self._set_state(session_id, "stopped")

    def append_event(self, event):
        session_id = event["session_id"]
        database = self._database(session_id)
        if not os.path.isfile(database):
            raise KeyError("unknown session")
        with self._connection(database) as connection:
            connection.execute("BEGIN IMMEDIATE")
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM event"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO event (
                    event_id, session_id, run_id, correlation_id, sequence,
                    occurred_at, kind, phase, severity, summary, details_json,
                    traffic_event_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"],
                    session_id,
                    event["run_id"],
                    event["correlation_id"],
                    sequence,
                    event["occurred_at"],
                    event["kind"],
                    event["phase"],
                    event.get("severity", "info"),
                    event["summary"],
                    json.dumps(event.get("details") or {}, separators=(",", ":")),
                    json.dumps(
                        event.get("traffic_event_ids") or [],
                        separators=(",", ":"),
                    ),
                ),
            )
            connection.execute(
                "UPDATE session SET last_active_at = ?",
                (_utc_now(),),
            )
            connection.commit()
        return sequence

    def list_events(self, session_id, after_sequence=0):
        database = self._database(session_id)
        if not os.path.isfile(database):
            return []
        with self._connection(database) as connection:
            rows = connection.execute(
                """
                SELECT event_id, session_id, run_id, correlation_id, sequence,
                       occurred_at, kind, phase, severity, summary,
                       details_json, traffic_event_ids_json
                FROM event
                WHERE sequence > ?
                ORDER BY sequence
                """,
                (after_sequence,),
            ).fetchall()
        return [{
            "event_id": row["event_id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "correlation_id": row["correlation_id"],
            "sequence": row["sequence"],
            "occurred_at": row["occurred_at"],
            "kind": row["kind"],
            "phase": row["phase"],
            "severity": row["severity"],
            "summary": row["summary"],
            "details": json.loads(row["details_json"]),
            "traffic_event_ids": json.loads(row["traffic_event_ids_json"]),
        } for row in rows]

    def delete(self, session_id):
        directory = self._directory(session_id, create=False)
        if not os.path.exists(directory):
            return DeleteResult(session_id, True, ())
        try:
            shutil.rmtree(directory)
        except OSError as error:
            return DeleteResult(
                session_id,
                False,
                (f"{type(error).__name__}: {error}",),
            )
        return DeleteResult(session_id, not os.path.exists(directory), ())

    def _set_state(self, session_id, state):
        database = self._database(session_id)
        if not os.path.isfile(database):
            raise KeyError("unknown session")
        with self._connection(database) as connection:
            connection.execute(
                """
                UPDATE session
                SET state = ?, last_active_at = ?, recovery_required = 0
                """,
                (state, _utc_now()),
            )
        return self.get(session_id)

    def _directory(self, session_id, create):
        if not isinstance(session_id, str) or not _SAFE_ID.fullmatch(session_id):
            raise ValueError("invalid session id")
        directory = os.path.realpath(os.path.join(self.root, session_id))
        if os.path.dirname(directory) != self.root:
            raise ValueError("session path escapes root")
        if create:
            os.makedirs(directory, exist_ok=False)
        return directory

    def _database(self, session_id):
        return os.path.join(self._directory(session_id, create=False), _DB_NAME)

    @staticmethod
    @contextmanager
    def _connection(database):
        connection = sqlite3.connect(database, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _session_from_row(row):
        return Session(
            session_id=row["session_id"],
            created_at=row["created_at"],
            last_active_at=row["last_active_at"],
            state=row["state"],
            content_recording=bool(row["content_recording"]),
            recovery_required=bool(row["recovery_required"]),
        )

    @staticmethod
    def _create_schema(connection):
        connection.executescript(
            """
            CREATE TABLE schema_version (
                version INTEGER NOT NULL
            );
            INSERT INTO schema_version(version) VALUES (1);

            CREATE TABLE session (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL,
                state TEXT NOT NULL,
                content_recording INTEGER NOT NULL,
                recovery_required INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE event (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                sequence INTEGER NOT NULL UNIQUE,
                occurred_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                phase TEXT NOT NULL,
                severity TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL,
                traffic_event_ids_json TEXT NOT NULL
            );
            CREATE INDEX event_session_sequence
            ON event(session_id, sequence);
            """
        )
        current = connection.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        if current != _SCHEMA_VERSION:
            raise RuntimeError("unsupported session schema")
