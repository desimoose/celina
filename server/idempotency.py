"""Bounded, process-local idempotency records for retryable mutations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
import threading
import uuid


KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def fingerprint(method, path, payload):
    raw = "%s %s\n%s" % (method, path, payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class _Record:
    fingerprint: str
    state: str = "in_progress"
    token: str = ""
    status: int | None = None
    body: bytes = b""
    headers: dict | None = None
    updated_at: object = None


class IdempotencyStore:
    def __init__(self, ttl_seconds=3600, max_records=512):
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_records = max(16, int(max_records))
        self._records = {}
        self._lock = threading.RLock()

    def begin(self, key, request_fingerprint):
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("Idempotency-Key must be 1-128 safe characters")
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge(now)
            record = self._records.get(key)
            if record is None:
                token = str(uuid.uuid4())
                self._records[key] = _Record(
                    request_fingerprint,
                    token=token,
                    updated_at=now,
                )
                self._trim()
                return "new", token, None
            if record.fingerprint != request_fingerprint:
                return "conflict", None, None
            if record.state == "in_progress":
                return "in_progress", None, None
            return "replay", None, {
                "status": record.status,
                "body": record.body,
                "headers": dict(record.headers or {}),
            }

    def complete(self, token, status, body, headers):
        with self._lock:
            for record in self._records.values():
                if record.token == token and record.state == "in_progress":
                    record.state = "complete"
                    record.status = status
                    record.body = bytes(body)
                    record.headers = dict(headers or {})
                    record.updated_at = datetime.now(timezone.utc)
                    return

    def abandon(self, token):
        with self._lock:
            for key, record in list(self._records.items()):
                if record.token == token:
                    self._records.pop(key, None)
                    return

    def _purge(self, now):
        cutoff = now - timedelta(seconds=self.ttl_seconds)
        for key, record in list(self._records.items()):
            if record.updated_at and record.updated_at < cutoff:
                self._records.pop(key, None)

    def _trim(self):
        while len(self._records) > self.max_records:
            oldest = min(
                self._records,
                key=lambda key: self._records[key].updated_at or datetime.min.replace(tzinfo=timezone.utc),
            )
            self._records.pop(oldest, None)
