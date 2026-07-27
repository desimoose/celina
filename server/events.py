"""Validated observable events and persisted in-process subscriptions."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import queue
import threading
import uuid


EVENT_KINDS = {
    "session.created",
    "session.recovered",
    "session.ending",
    "session.deleted",
    "search.started",
    "plan.completed",
    "query.started",
    "query.completed",
    "query.failed",
    "candidate.selected",
    "source.read.started",
    "source.read.completed",
    "source.read.blocked",
    "gap.detected",
    "conflict.detected",
    "follow_up.started",
    "synthesis.started",
    "synthesis.completed",
    "citation.verified",
    "citation.rejected",
    "answer.corrected",
    "search.stopped",
    "search.completed",
    "search.failed",
    "stream.resync",
}

PHASES = {
    "session",
    "planning",
    "retrieving",
    "selecting",
    "reading",
    "checking_gaps",
    "synthesizing",
    "verifying",
    "completed",
    "stopped",
    "failed",
}

SEVERITIES = {"info", "warning", "error"}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class Event:
    event_id: str
    session_id: str
    run_id: str
    correlation_id: str
    sequence: int | None
    occurred_at: str
    kind: str
    phase: str
    severity: str
    summary: str
    details: dict
    traffic_event_ids: tuple[str, ...]

    @classmethod
    def create(
        cls,
        session_id,
        run_id,
        correlation_id,
        kind,
        phase,
        summary,
        details=None,
        severity="info",
        traffic_event_ids=(),
    ):
        if kind not in EVENT_KINDS:
            raise ValueError("unknown event kind")
        if phase not in PHASES:
            raise ValueError("unknown event phase")
        if severity not in SEVERITIES:
            raise ValueError("unknown event severity")
        for name, value in (
            ("session_id", session_id),
            ("run_id", run_id),
            ("correlation_id", correlation_id),
            ("summary", summary),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required")
        details = details or {}
        try:
            json.dumps(details)
            json.dumps(list(traffic_event_ids))
        except (TypeError, ValueError) as error:
            raise ValueError("event details must be JSON serializable") from error
        return cls(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            run_id=run_id,
            correlation_id=correlation_id,
            sequence=None,
            occurred_at=_utc_now(),
            kind=kind,
            phase=phase,
            severity=severity,
            summary=summary,
            details=dict(details),
            traffic_event_ids=tuple(traffic_event_ids),
        )

    @classmethod
    def from_dict(cls, value):
        return cls(
            event_id=value["event_id"],
            session_id=value["session_id"],
            run_id=value["run_id"],
            correlation_id=value["correlation_id"],
            sequence=value["sequence"],
            occurred_at=value["occurred_at"],
            kind=value["kind"],
            phase=value["phase"],
            severity=value["severity"],
            summary=value["summary"],
            details=value.get("details") or {},
            traffic_event_ids=tuple(value.get("traffic_event_ids") or ()),
        )

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at,
            "kind": self.kind,
            "phase": self.phase,
            "severity": self.severity,
            "summary": self.summary,
            "details": self.details,
            "traffic_event_ids": list(self.traffic_event_ids),
        }


class Subscription:
    def __init__(self, bus, session_id, maxsize):
        self._bus = bus
        self.session_id = session_id
        self._queue = queue.Queue(maxsize=maxsize)
        self._closed = False

    def get(self, timeout=None):
        if self._closed and self._queue.empty():
            return None
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        if self._closed:
            return
        self._closed = True
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._bus._unsubscribe(self)

    def _put(self, event):
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            marker = Event.create(
                session_id=event.session_id,
                run_id=event.run_id,
                correlation_id=event.correlation_id,
                kind="stream.resync",
                phase=event.phase,
                severity="warning",
                summary="The live trace needs to resync.",
                details={"after_sequence": event.sequence},
            )
            self._queue.put_nowait(replace(marker, sequence=event.sequence))


class EventBus:
    def __init__(self, store, subscriber_queue_size=256):
        self.store = store
        self.subscriber_queue_size = subscriber_queue_size
        self._lock = threading.RLock()
        self._subscribers = {}

    def publish(self, event):
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        with self._lock:
            sequence = self.store.append_event(event.to_dict())
            persisted = replace(event, sequence=sequence)
            for subscription in tuple(
                self._subscribers.get(event.session_id, ())
            ):
                subscription._put(persisted)
            return persisted

    def subscribe(self, session_id, after_sequence=0):
        subscription = Subscription(
            self, session_id, self.subscriber_queue_size
        )
        with self._lock:
            for item in self.store.list_events(session_id, after_sequence):
                subscription._put(Event.from_dict(item))
            self._subscribers.setdefault(session_id, set()).add(subscription)
        return subscription

    def subscriber_count(self, session_id):
        with self._lock:
            return len(self._subscribers.get(session_id, ()))

    def _unsubscribe(self, subscription):
        with self._lock:
            subscribers = self._subscribers.get(subscription.session_id)
            if not subscribers:
                return
            subscribers.discard(subscription)
            if not subscribers:
                self._subscribers.pop(subscription.session_id, None)
