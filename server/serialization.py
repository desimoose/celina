"""Explicit product-state serializers for the local API."""


def serialize_session(session):
    """Return only fields the local product API may expose for a session."""
    return {
        "session_id": session.session_id,
        "state": session.state,
        "created_at": session.created_at,
        "last_active_at": session.last_active_at,
        "content_recording": session.content_recording,
        "incognito": getattr(session, "incognito", False),
        "recovery_required": session.recovery_required,
    }


def serialize_search_run(run):
    """Return a whitelist of serializable, user-visible search-run state."""
    plan = _value(run, "query_plan")
    return {
        "run_id": _value(run, "run_id"),
        "state": _value(run, "state"),
        "query": _value(run, "query"),
        "query_plan": {
            "queries": _string_list(_value(plan, "queries", ())),
            "angles": _string_list(_value(plan, "angles", ())),
            "summary": _string(_value(plan, "summary", ""), ""),
        },
        "candidates": [
            _serialize_candidate(item)
            for item in (_value(run, "candidates", ()) or ())
        ],
        "evidence": [
            _serialize_evidence(item)
            for item in (_value(run, "evidence", ()) or ())
        ],
        "answer": _serialize_answer(_value(run, "answer")),
        "gaps": _string_list(_value(run, "gaps", ())),
        "conflicts": _string_list(_value(run, "conflicts", ())),
        "follow_up_count": _integer(_value(run, "follow_up_count", 0)),
        "error_class": _string(_value(run, "error_class"), None),
    }


def _serialize_candidate(item):
    return {
        "candidate_id": _string(_value(item, "candidate_id"), None),
        "title": _string(_value(item, "title"), None),
        "url": _string(_value(item, "url"), None),
        "canonical_url": _string(_value(item, "canonical_url"), None),
        "source_kind": _string(_value(item, "source_kind"), None),
        "published_at": _string(_value(item, "published_at"), None),
        "authors": _string_list(_value(item, "authors", ())),
        "snippet": _string(_value(item, "snippet"), None),
        "open_access": _boolean(_value(item, "open_access")),
        "retrieval_query_ids": _string_list(
            _value(item, "retrieval_query_ids", ())
        ),
    }


def _serialize_evidence(item):
    return {
        "citation_id": _string(_value(item, "citation_id"), None),
        "candidate_id": _string(_value(item, "candidate_id"), None),
        "title": _string(_value(item, "title"), None),
        "url": _string(_value(item, "url"), None),
        "source_kind": _string(_value(item, "source_kind"), None),
        "content_type": _string(_value(item, "content_type"), None),
        "character_count": _integer(_value(item, "character_count")),
        "was_read": _boolean(_value(item, "was_read")),
    }


def _serialize_answer(answer):
    if answer is None:
        return None
    if isinstance(answer, str):
        return answer
    if not isinstance(answer, dict):
        return None
    return {
        "answer": _string(answer.get("answer"), ""),
        "citations": _string_list(answer.get("citations", ())),
    }


def _value(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _string(value, default):
    return value if isinstance(value, str) else default


def _string_list(values):
    if not isinstance(values, (list, tuple)):
        return []
    return [value for value in values if isinstance(value, str)]


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _boolean(value):
    return value if isinstance(value, bool) else None
