"""Memory-only authorization material for Celina's loopback API."""

import secrets
import hmac
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, urlsplit


class LocalSecurity:
    """Owns the per-launch cookie and CSRF values without persisting them."""

    cookie_name = "celina_launch"

    def __init__(self, expected_origin):
        if not _is_loopback_origin(expected_origin):
            raise ValueError("expected_origin must be an HTTP loopback origin")
        self.expected_origin = expected_origin
        self.launch_token = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)

    @property
    def launch_cookie_header(self):
        return (
            f"{self.cookie_name}={self.launch_token}; Path=/; "
            "HttpOnly; SameSite=Strict"
        )

    def authorize_mutation(
        self,
        cookie_header,
        csrf_header,
        origin,
        query_string="",
    ):
        """Return whether a request has all local mutation credentials."""
        try:
            cookies = SimpleCookie(cookie_header or "")
            supplied_cookie = cookies.get(self.cookie_name)
            supplied_cookie = supplied_cookie.value if supplied_cookie else ""
        except (TypeError, ValueError):
            supplied_cookie = ""
        return (
            isinstance(origin, str)
            and origin == self.expected_origin
            and isinstance(csrf_header, str)
            and not self._query_contains_secret(query_string)
            and _secret_matches(supplied_cookie, self.launch_token)
            and _secret_matches(csrf_header, self.csrf_token)
        )

    def _query_contains_secret(self, query_string):
        if not isinstance(query_string, str):
            return True
        values = [value for _key, value in parse_qsl(query_string)]
        return any(
            _secret_matches(value, token)
            for value in values
            for token in (self.launch_token, self.csrf_token)
        )

    @staticmethod
    def denial_body():
        """Use one generic body so authorization failures cannot echo secrets."""
        return '{"error":"forbidden"}'


def _is_loopback_origin(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and (port is None or 0 < port <= 65535)
    )


def _secret_matches(supplied, expected):
    if not isinstance(supplied, str):
        return False
    try:
        return hmac.compare_digest(supplied, expected)
    except TypeError:
        return False
