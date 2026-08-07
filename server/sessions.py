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
    incognito: bool
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

    def create(self, content_recording=True, incognito=False):
        if not isinstance(content_recording, bool):
            raise ValueError("content_recording must be a boolean")
        if not isinstance(incognito, bool):
            raise ValueError("incognito must be a boolean")
        session_id = str(uuid.uuid4())
        directory = self._directory(session_id, create=True)
        if incognito:
            with open(os.path.join(directory, ".incognito"), "x", encoding="utf-8"):
                pass
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

    def list(self):
        """Return valid local ledgers without maintaining a global index."""
        sessions = []
        for name in sorted(os.listdir(self.root)):
            if not _SAFE_ID.fullmatch(name):
                continue
            item = self.get(name)
            if item is not None:
                sessions.append(item)
        return sessions

    def cleanup(
        self,
        retention_seconds=86400,
        now=None,
        include_active_incognito=False,
    ):
        """Delete expired stopped sessions and orphaned/stopped incognito sessions."""
        if not isinstance(retention_seconds, (int, float)) or retention_seconds < 0:
            raise ValueError("retention_seconds must be non-negative")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        removed = []
        for item in self.list():
            expired = False
            if item.incognito:
                expired = include_active_incognito or item.state in {"stopped", "ending"}
            elif item.state in {"stopped", "ending"}:
                try:
                    last_active = datetime.fromisoformat(
                        item.last_active_at.replace("Z", "+00:00")
                    )
                    expired = (current - last_active).total_seconds() >= retention_seconds
                except (TypeError, ValueError):
                    expired = False
            if expired:
                result = self.delete(item.session_id)
                if result.deleted:
                    removed.append(item.session_id)
        return removed

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

    def append_token_usage(self, usage):
        session_id = usage["session_id"]
        database = self._database(session_id)
        if not os.path.isfile(database):
            raise KeyError("unknown session")
        with self._connection(database) as connection:
            connection.execute(
                """
                INSERT INTO token_usage (
                    usage_id, session_id, correlation_id, provider, model,
                    input_tokens, output_tokens, cached_input_tokens,
                    context_limit, is_estimated, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage["usage_id"],
                    session_id,
                    usage["correlation_id"],
                    usage["provider"],
                    usage["model"],
                    usage.get("input_tokens"),
                    usage.get("output_tokens"),
                    usage.get("cached_input_tokens"),
                    usage.get("context_limit"),
                    1 if usage.get("is_estimated") else 0,
                    usage["recorded_at"],
                ),
            )
            connection.execute(
                "UPDATE session SET last_active_at = ?",
                (_utc_now(),),
            )

    def list_token_usage(self, session_id):
        database = self._database(session_id)
        if not os.path.isfile(database):
            return []
        with self._connection(database) as connection:
            rows = connection.execute(
                """
                SELECT usage_id, session_id, correlation_id, provider, model,
                       input_tokens, output_tokens, cached_input_tokens,
                       context_limit, is_estimated, recorded_at
                FROM token_usage
                ORDER BY recorded_at, usage_id
                """
            ).fetchall()
        return [{
            "usage_id": row["usage_id"],
            "session_id": row["session_id"],
            "correlation_id": row["correlation_id"],
            "provider": row["provider"],
            "model": row["model"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cached_input_tokens": row["cached_input_tokens"],
            "context_limit": row["context_limit"],
            "is_estimated": bool(row["is_estimated"]),
            "recorded_at": row["recorded_at"],
        } for row in rows]

    def start_traffic(self, item):
        session_id = item["session_id"]
        database = self._database(session_id)
        if not os.path.isfile(database):
            raise KeyError("unknown session")
        with self._connection(database) as connection:
            connection.execute(
                """
                INSERT INTO traffic (
                    traffic_event_id, session_id, run_id, correlation_id,
                    direction, transport, destination, method_or_action,
                    started_at, request_bytes, request_headers_json,
                    request_body, redactions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["traffic_event_id"],
                    session_id,
                    item["run_id"],
                    item["correlation_id"],
                    item["direction"],
                    item["transport"],
                    item["destination"],
                    item["method_or_action"],
                    item["started_at"],
                    item["request_bytes"],
                    json.dumps(item["request_headers"], separators=(",", ":")),
                    item["request_body"],
                    json.dumps(item["redactions"], separators=(",", ":")),
                ),
            )

    def complete_traffic(self, session_id, traffic_event_id, changes):
        database = self._database(session_id)
        if not os.path.isfile(database):
            raise KeyError("unknown session")
        with self._connection(database) as connection:
            cursor = connection.execute(
                """
                UPDATE traffic
                SET completed_at = ?, status = ?, duration_ms = ?,
                    response_bytes = ?, response_headers_json = ?,
                    response_body = ?, redactions_json = ?,
                    error_class = ?, error_summary = ?
                WHERE traffic_event_id = ?
                """,
                (
                    changes["completed_at"],
                    changes.get("status"),
                    changes["duration_ms"],
                    changes.get("response_bytes"),
                    json.dumps(
                        changes.get("response_headers") or {},
                        separators=(",", ":"),
                    ),
                    changes.get("response_body") or b"",
                    json.dumps(
                        changes.get("redactions") or [],
                        separators=(",", ":"),
                    ),
                    changes.get("error_class"),
                    changes.get("error_summary"),
                    traffic_event_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError("unknown traffic event")
            connection.execute(
                "UPDATE session SET last_active_at = ?",
                (_utc_now(),),
            )

    def list_traffic(self, session_id):
        database = self._database(session_id)
        if not os.path.isfile(database):
            return []
        with self._connection(database) as connection:
            rows = connection.execute(
                """
                SELECT traffic_event_id, session_id, run_id, correlation_id,
                       direction, transport, destination, method_or_action,
                       started_at, completed_at, status, duration_ms,
                       request_bytes, response_bytes, request_headers_json,
                       response_headers_json, request_body, response_body,
                       redactions_json, error_class, error_summary
                FROM traffic
                ORDER BY started_at, traffic_event_id
                """
            ).fetchall()
        return [{
            "traffic_event_id": row["traffic_event_id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "correlation_id": row["correlation_id"],
            "direction": row["direction"],
            "transport": row["transport"],
            "destination": row["destination"],
            "method_or_action": row["method_or_action"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "request_bytes": row["request_bytes"],
            "response_bytes": row["response_bytes"],
            "request_headers": json.loads(row["request_headers_json"]),
            "response_headers": json.loads(row["response_headers_json"] or "{}"),
            "request_body": bytes(row["request_body"] or b""),
            "response_body": bytes(row["response_body"] or b""),
            "redactions": json.loads(row["redactions_json"]),
            "error_class": row["error_class"],
            "error_summary": row["error_summary"],
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

    def _session_from_row(self, row):
        return Session(
            session_id=row["session_id"],
            created_at=row["created_at"],
            last_active_at=row["last_active_at"],
            state=row["state"],
            content_recording=bool(row["content_recording"]),
            incognito=os.path.isfile(os.path.join(
                self._directory(row["session_id"], create=False), ".incognito"
            )),
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

            CREATE TABLE token_usage (
                usage_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cached_input_tokens INTEGER,
                context_limit INTEGER,
                is_estimated INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX token_usage_session_recorded
            ON token_usage(session_id, recorded_at);

            CREATE TABLE traffic (
                traffic_event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                correlation_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                transport TEXT NOT NULL,
                destination TEXT NOT NULL,
                method_or_action TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status INTEGER,
                duration_ms INTEGER,
                request_bytes INTEGER NOT NULL,
                response_bytes INTEGER,
                request_headers_json TEXT NOT NULL,
                response_headers_json TEXT,
                request_body BLOB NOT NULL,
                response_body BLOB,
                redactions_json TEXT NOT NULL,
                error_class TEXT,
                error_summary TEXT
            );
            CREATE INDEX traffic_session_started
            ON traffic(session_id, started_at);
            """
        )
        current = connection.execute(
            "SELECT version FROM schema_version"
        ).fetchone()[0]
        if current != _SCHEMA_VERSION:
            raise RuntimeError("unsupported session schema")
