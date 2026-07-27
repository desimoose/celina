"""Secret redaction for local traffic records.

Redaction happens before traffic content reaches SQLite, logs, or UI events.
The metadata records what kind of redaction occurred but never the removed
value.
"""

from dataclasses import dataclass
import json
import urllib.parse


MARKER = "[REDACTED]"

_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}

_SENSITIVE_KEYS = {
    "access_token",
    "api-key",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "cookie",
    "key",
    "password",
    "proxy-authorization",
    "secret",
    "token",
    "x-api-key",
}


@dataclass(frozen=True)
class RedactedBody:
    body: bytes
    redactions: tuple[str, ...]


class Redactor:
    def __init__(self, secret_values=()):
        cleaned = {
            value for value in secret_values
            if isinstance(value, str) and value
        }
        self._secrets = tuple(sorted(cleaned, key=len, reverse=True))

    def redact_text(self, text):
        if not isinstance(text, str):
            text = str(text)
        redactions = []
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, MARKER)
                redactions.append("configured-secret")
        return text, redactions

    def redact_headers(self, headers):
        out = {}
        for key, value in dict(headers or {}).items():
            if str(key).lower() in _SENSITIVE_HEADERS:
                out[key] = MARKER
            else:
                out[key] = self.redact_text(value)[0]
        return out

    def redact_url(self, url):
        parsed = urllib.parse.urlsplit(url)
        query = []
        for key, value in urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True
        ):
            if key.lower() in _SENSITIVE_KEYS:
                value = MARKER
            else:
                value = self.redact_text(value)[0]
            query.append((key, value))
        return urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            parsed.fragment,
        ))

    def redact_body(self, content_type, body):
        if body is None:
            return RedactedBody(b"", ())
        if isinstance(body, str):
            body = body.encode("utf-8")
        media_type = (content_type or "").split(";", 1)[0].strip().lower()

        if media_type == "application/json":
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self._redact_plain(body)
            redactions = []
            safe = self._redact_json(value, redactions)
            encoded = json.dumps(
                safe, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            return RedactedBody(encoded, tuple(redactions))

        if media_type == "application/x-www-form-urlencoded":
            redactions = []
            pairs = []
            decoded = body.decode("utf-8", "replace")
            for key, value in urllib.parse.parse_qsl(
                decoded, keep_blank_values=True
            ):
                if key.lower() in _SENSITIVE_KEYS:
                    value = MARKER
                    redactions.append("sensitive-field")
                else:
                    value, found = self.redact_text(value)
                    redactions.extend(found)
                pairs.append((key, value))
            return RedactedBody(
                urllib.parse.urlencode(pairs).encode("utf-8"),
                tuple(redactions),
            )

        return self._redact_plain(body)

    def _redact_plain(self, body):
        text = body.decode("utf-8", "replace")
        safe, redactions = self.redact_text(text)
        return RedactedBody(safe.encode("utf-8"), tuple(redactions))

    def _redact_json(self, value, redactions):
        if isinstance(value, dict):
            out = {}
            for key, item in value.items():
                if str(key).lower() in _SENSITIVE_KEYS:
                    out[key] = MARKER
                    redactions.append("sensitive-field")
                else:
                    out[key] = self._redact_json(item, redactions)
            return out
        if isinstance(value, list):
            return [self._redact_json(item, redactions) for item in value]
        if isinstance(value, str):
            safe, found = self.redact_text(value)
            redactions.extend(found)
            return safe
        return value
