"""Provider-reported token accounting for the local session watchtower."""

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _optional_count(value, name):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")
    return value


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    is_estimated: bool


@dataclass(frozen=True)
class UsageRecord:
    usage_id: str
    session_id: str
    correlation_id: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    context_limit: int | None
    context_percentage: float | None
    is_estimated: bool
    recorded_at: str


@dataclass(frozen=True)
class UsageSummary:
    session_id: str
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    total_tokens: int | None
    context_percentage: float | None
    records: tuple[UsageRecord, ...]


def normalize_usage(provider, usage):
    usage = usage or {}
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    cached_input_tokens = usage.get("cached_input_tokens")

    if input_tokens is None and "prompt_tokens" in usage:
        input_tokens = usage.get("prompt_tokens")
    if output_tokens is None and "completion_tokens" in usage:
        output_tokens = usage.get("completion_tokens")
    if cached_input_tokens is None:
        details = usage.get("prompt_tokens_details") or {}
        cached_input_tokens = details.get("cached_tokens")
    if cached_input_tokens is None and provider == "anthropic":
        cache_values = [
            usage.get("cache_read_input_tokens"),
            usage.get("cache_creation_input_tokens"),
        ]
        if any(value is not None for value in cache_values):
            cached_input_tokens = sum(value or 0 for value in cache_values)

    return NormalizedUsage(
        input_tokens=_optional_count(input_tokens, "input_tokens"),
        output_tokens=_optional_count(output_tokens, "output_tokens"),
        cached_input_tokens=_optional_count(
            cached_input_tokens,
            "cached_input_tokens",
        ),
        is_estimated=False,
    )


def _context_percentage(input_tokens, context_limit):
    if input_tokens is None or context_limit is None:
        return None
    return round((input_tokens / context_limit) * 100, 1)


def _sum_known(records, field):
    values = [getattr(record, field) for record in records]
    if not values or any(value is None for value in values):
        return None
    return sum(values)


class TokenAccountant:
    def __init__(self, store, session_id, context_limits=None):
        self.store = store
        self.session_id = session_id
        self.context_limits = dict(context_limits or {})

    def record(self, provider, model, usage, correlation_id):
        normalized = normalize_usage(provider, usage)
        context_limit = self.context_limits.get((provider, model))
        record = UsageRecord(
            usage_id=str(uuid.uuid4()),
            session_id=self.session_id,
            correlation_id=correlation_id,
            provider=provider,
            model=model,
            input_tokens=normalized.input_tokens,
            output_tokens=normalized.output_tokens,
            cached_input_tokens=normalized.cached_input_tokens,
            context_limit=context_limit,
            context_percentage=_context_percentage(
                normalized.input_tokens,
                context_limit,
            ),
            is_estimated=normalized.is_estimated,
            recorded_at=_utc_now(),
        )
        self.store.append_token_usage(_record_to_dict(record))
        return record

    def summary(self, session_id):
        records = tuple(
            _record_from_dict(item)
            for item in self.store.list_token_usage(session_id)
        )
        input_tokens = _sum_known(records, "input_tokens")
        output_tokens = _sum_known(records, "output_tokens")
        cached_input_tokens = _sum_known(records, "cached_input_tokens")
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        percentages = [
            record.context_percentage
            for record in records
            if record.context_percentage is not None
        ]
        return UsageSummary(
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            total_tokens=total_tokens,
            context_percentage=max(percentages) if percentages else None,
            records=records,
        )


def _record_to_dict(record):
    return {
        "usage_id": record.usage_id,
        "session_id": record.session_id,
        "correlation_id": record.correlation_id,
        "provider": record.provider,
        "model": record.model,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cached_input_tokens": record.cached_input_tokens,
        "context_limit": record.context_limit,
        "is_estimated": record.is_estimated,
        "recorded_at": record.recorded_at,
    }


def _record_from_dict(value):
    return UsageRecord(
        usage_id=value["usage_id"],
        session_id=value["session_id"],
        correlation_id=value["correlation_id"],
        provider=value["provider"],
        model=value["model"],
        input_tokens=value.get("input_tokens"),
        output_tokens=value.get("output_tokens"),
        cached_input_tokens=value.get("cached_input_tokens"),
        context_limit=value.get("context_limit"),
        context_percentage=_context_percentage(
            value.get("input_tokens"),
            value.get("context_limit"),
        ),
        is_estimated=bool(value.get("is_estimated")),
        recorded_at=value["recorded_at"],
    )
