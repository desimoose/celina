"""Redacted local recording for Celina-managed network traffic."""

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class TrafficCancelled(Exception):
    pass


class MalformedResponseError(Exception):
    pass


class ProcessError(Exception):
    pass


@dataclass(frozen=True)
class TrafficContext:
    session_id: str
    run_id: str
    correlation_id: str
    recorder: object
    redactor: object
    cancellation: object = None


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict
    body: bytes
    traffic_event_id: str | None


@dataclass(frozen=True)
class TrafficRecord:
    traffic_event_id: str
    session_id: str
    run_id: str
    correlation_id: str
    direction: str
    transport: str
    destination: str
    method_or_action: str
    started_at: str
    completed_at: str | None
    status: int | None
    duration_ms: int | None
    request_bytes: int
    response_bytes: int | None
    request_headers: dict
    response_headers: dict
    request_body: bytes
    response_body: bytes
    redactions: tuple[str, ...]
    error_class: str | None
    error_summary: str | None


class TrafficRecorder:
    def __init__(self, store):
        self.store = store

    def start(self, context, request, action_type):
        body = request.data or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        headers = {
            key.lower(): value
            for key, value in request.header_items()
        }
        content_type = _header(headers, "content-type")
        redacted_body = context.redactor.redact_body(content_type, body)
        safe_headers = context.redactor.redact_headers(headers)
        safe_url = context.redactor.redact_url(request.full_url)
        event_id = str(uuid.uuid4())
        redactions = list(redacted_body.redactions)
        if safe_headers != headers:
            redactions.append("sensitive-header")
        if safe_url != request.full_url:
            redactions.append("sensitive-url")
        self.store.start_traffic({
            "traffic_event_id": event_id,
            "session_id": context.session_id,
            "run_id": context.run_id,
            "correlation_id": context.correlation_id,
            "direction": "outbound",
            "transport": urllib.parse.urlsplit(request.full_url).scheme,
            "destination": safe_url,
            "method_or_action": action_type,
            "started_at": _utc_now(),
            "request_bytes": len(body),
            "request_headers": safe_headers,
            "request_body": redacted_body.body,
            "redactions": redactions,
        })
        return event_id, tuple(redactions)

    def start_process(self, context, destination, action_type, metadata):
        safe_url = context.redactor.redact_url(destination)
        body = json.dumps(
            metadata,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        redacted_body = context.redactor.redact_body("application/json", body)
        event_id = str(uuid.uuid4())
        redactions = list(redacted_body.redactions)
        if safe_url != destination:
            redactions.append("sensitive-url")
        self.store.start_traffic({
            "traffic_event_id": event_id,
            "session_id": context.session_id,
            "run_id": context.run_id,
            "correlation_id": context.correlation_id,
            "direction": "outbound",
            "transport": "process",
            "destination": safe_url,
            "method_or_action": action_type,
            "started_at": _utc_now(),
            "request_bytes": len(body),
            "request_headers": {},
            "request_body": redacted_body.body,
            "redactions": redactions,
        })
        return event_id, tuple(redactions)

    def complete_process(
        self,
        context,
        traffic_event_id,
        started,
        exit_status,
        output,
        redactions=(),
        error_summary=None,
    ):
        error = (
            ProcessError(error_summary or "process exited non-zero")
            if exit_status != 0
            else None
        )
        self.complete(
            context,
            traffic_event_id,
            started,
            status=exit_status,
            headers={"content-type": "text/plain; charset=utf-8"},
            body=output,
            redactions=redactions,
            error=error,
        )

    def complete(
        self,
        context,
        traffic_event_id,
        started,
        status=None,
        headers=None,
        body=b"",
        redactions=(),
        error=None,
    ):
        response_headers = {
            key.lower(): value
            for key, value in dict(headers or {}).items()
        }
        content_type = _header(response_headers, "content-type")
        redacted_body = context.redactor.redact_body(content_type, body)
        safe_headers = context.redactor.redact_headers(response_headers)
        all_redactions = list(redactions) + list(redacted_body.redactions)
        if safe_headers != response_headers:
            all_redactions.append("sensitive-header")
        error_class = type(error).__name__ if error else None
        error_summary = None
        if error:
            error_summary = context.redactor.redact_text(str(error))[0]
        self.store.complete_traffic(
            context.session_id,
            traffic_event_id,
            {
                "completed_at": _utc_now(),
                "status": status,
                "duration_ms": max(0, round((time.monotonic() - started) * 1000)),
                "response_bytes": len(body),
                "response_headers": safe_headers,
                "response_body": redacted_body.body,
                "redactions": sorted(set(all_redactions)),
                "error_class": error_class,
                "error_summary": error_summary,
            },
        )

    def mark_malformed(self, context, traffic_event_id, error):
        records = self.store.list_traffic(context.session_id)
        item = next(
            record
            for record in records
            if record["traffic_event_id"] == traffic_event_id
        )
        self.store.complete_traffic(
            context.session_id,
            traffic_event_id,
            {
                "completed_at": item["completed_at"],
                "status": item["status"],
                "duration_ms": item["duration_ms"],
                "response_bytes": item["response_bytes"],
                "response_headers": item["response_headers"],
                "response_body": item["response_body"],
                "redactions": item["redactions"],
                "error_class": type(error).__name__,
                "error_summary": context.redactor.redact_text(str(error))[0],
            },
        )

    def list(self, session_id):
        return [
            TrafficRecord(
                traffic_event_id=item["traffic_event_id"],
                session_id=item["session_id"],
                run_id=item["run_id"],
                correlation_id=item["correlation_id"],
                direction=item["direction"],
                transport=item["transport"],
                destination=item["destination"],
                method_or_action=item["method_or_action"],
                started_at=item["started_at"],
                completed_at=item["completed_at"],
                status=item["status"],
                duration_ms=item["duration_ms"],
                request_bytes=item["request_bytes"],
                response_bytes=item["response_bytes"],
                request_headers=item["request_headers"],
                response_headers=item["response_headers"],
                request_body=item["request_body"],
                response_body=item["response_body"],
                redactions=tuple(item["redactions"]),
                error_class=item["error_class"],
                error_summary=item["error_summary"],
            )
            for item in self.store.list_traffic(session_id)
        ]


def http_request(context, request, timeout, action_type):
    if context is not None and _cancelled(context):
        raise TrafficCancelled("request cancelled before opening connection")

    traffic_event_id = None
    request_redactions = ()
    started = time.monotonic()
    if context is not None:
        traffic_event_id, request_redactions = context.recorder.start(
            context,
            request,
            action_type,
        )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
            headers = dict(response.headers.items())
    except urllib.error.HTTPError as error:
        body = error.read()
        if context is not None:
            context.recorder.complete(
                context,
                traffic_event_id,
                started,
                status=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
                body=body,
                redactions=request_redactions,
                error=error,
            )
        error.close()
        error.fp = io.BytesIO(body)
        raise
    except (urllib.error.URLError, TimeoutError) as error:
        if context is not None:
            context.recorder.complete(
                context,
                traffic_event_id,
                started,
                redactions=request_redactions,
                error=error,
            )
        raise

    if context is not None:
        context.recorder.complete(
            context,
            traffic_event_id,
            started,
            status=status,
            headers=headers,
            body=body,
            redactions=request_redactions,
        )
    return HttpResult(status, headers, body, traffic_event_id)


def provider_request(
    context,
    provider,
    request,
    timeout,
    action_type="provider.chat",
):
    result = http_request(context, request, timeout, action_type)
    try:
        return json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as cause:
        error = MalformedResponseError(
            f"{provider} returned a malformed JSON response"
        )
        if context is not None:
            context.recorder.mark_malformed(
                context,
                result.traffic_event_id,
                error,
            )
        raise error from cause


def _cancelled(context):
    return (
        context.cancellation is not None
        and context.cancellation.is_set()
    )


def _header(headers, name):
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None
