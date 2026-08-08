"""Bounded, durable idempotency records for retryable mutations."""

from contextlib import contextmanager
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid


KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_CACHED_RESPONSE_BYTES = 256 * 1024
MAX_CACHED_HEADERS_BYTES = 64 * 1024


def fingerprint(method, path, payload):
    raw = "%s %s\n%s" % (method, path, payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IdempotencyStore:
    def __init__(self, path, ttl_seconds=3600, max_records=512):
        self.path = os.path.abspath(os.fspath(path))
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_records = max(1, int(max_records))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    token TEXT,
                    status INTEGER,
                    headers_json TEXT,
                    body BLOB,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def begin(self, key, request_fingerprint):
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("Idempotency-Key must be 1-128 safe characters")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM idempotency_records WHERE updated_at <= ?",
                (now - self.ttl_seconds,),
            )
            record = connection.execute(
                """
                SELECT fingerprint, state, status, headers_json, body
                FROM idempotency_records
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
            if record is None:
                token = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO idempotency_records (
                        key, fingerprint, state, token, updated_at
                    ) VALUES (?, ?, 'in_progress', ?, ?)
                    """,
                    (key, request_fingerprint, token, now),
                )
                self._trim(connection)
                return "new", token, None

            stored_fingerprint, state, status, headers_json, body = record
            if stored_fingerprint != request_fingerprint:
                return "conflict", None, None
            if state == "in_progress":
                return "in_progress", None, None
            return "replay", None, {
                "status": status,
                "body": bytes(body or b""),
                "headers": dict(json.loads(headers_json or "{}")),
            }

    def complete(self, token, status, body, headers):
        body = bytes(body)
        if len(body) > MAX_CACHED_RESPONSE_BYTES:
            raise ValueError("cached response body too large")
        headers_json = json.dumps(
            dict(headers or {}),
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(headers_json.encode("utf-8")) > MAX_CACHED_HEADERS_BYTES:
            raise ValueError("cached response headers too large")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE idempotency_records
                SET state = 'complete', status = ?, headers_json = ?,
                    body = ?, updated_at = ?
                WHERE token = ? AND state = 'in_progress'
                """,
                (int(status), headers_json, body, int(time.time()), token),
            )

    def abandon(self, token):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM idempotency_records WHERE token = ?",
                (token,),
            )

    def _trim(self, connection):
        count = connection.execute(
            "SELECT COUNT(*) FROM idempotency_records"
        ).fetchone()[0]
        excess = count - self.max_records
        if excess > 0:
            connection.execute(
                """
                DELETE FROM idempotency_records
                WHERE rowid IN (
                    SELECT rowid FROM idempotency_records
                    ORDER BY updated_at ASC, rowid ASC
                    LIMIT ?
                )
                """,
                (excess,),
            )
