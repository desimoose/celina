#!/usr/bin/env python3
"""Repository-native release policy checks for Celina."""

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "SECURITY.md",
    "docs/SECURITY_MODEL.md",
    "docs/OPERATIONS.md",
    "CONTRIBUTING.md",
    ".github/workflows/ci.yml",
)

CI_COMMANDS = (
    "python -m unittest discover -s tests -q",
    "node --test tests/test_privacy_ui.js tests/test_search_capture.js",
    "python -c \"import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('server').glob('*.py')]\"",
    "node --check web/app.js",
    "git diff --check",
    "python scripts/verify_release.py",
)

APPROVED_PROVIDER_GATEWAYS = frozenset({
    "https://api.anthropic.com/v1/messages",
    "https://api.openai.com/v1/chat/completions",
    "https://openrouter.ai/api/v1/chat/completions",
    "https://api.x.ai/v1/chat/completions",
    "http://localhost:11434/v1/chat/completions",
})

_TEXT_SUFFIXES = frozenset({
    ".html", ".ini", ".js", ".json", ".md", ".ps1", ".py", ".spec",
    ".toml", ".txt", ".yaml", ".yml",
})
_SKIPPED_DIRS = frozenset({
    ".git", ".playwright-cli", ".superpowers", "__pycache__", "build",
    "dist",
})
_NON_PRODUCTION_PREFIXES = ("tests/", "docs/", ".agents/", ".claude/")

_TELEMETRY_CLIENTS = (
    "amplitude", "appcenter", "crashlytics", "datadog", "mixpanel",
    "newrelic", "posthog", "rollbar", "segment", "sentry",
)
_REMOTE_FLAG_CLIENTS = (
    "configcat", "flagsmith", "growthbook", "launchdarkly", "optimizely",
    "splitio", "statsig", "unleash",
)
_TRACKING_HOSTS = (
    "amplitude.com", "app-measurement.com", "crashlytics.com",
    "google-analytics.com", "googletagmanager.com", "mixpanel.com",
    "posthog.com", "segment.io", "sentry.io",
)

_URL_RE = re.compile(r"https?://[^\s'\"`<>]+", re.IGNORECASE)
_GATEWAY_URL_RE = re.compile(
    r'[\"\']url[\"\']\s*:\s*[\"\'](https?://[^\"\']+)[\"\']',
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b[A-Z][A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|AUTH_TOKEN|PASSWORD|SECRET)"
    r"[ \t]*[:=][ \t]*(?:\"[^\"\r\n]+\"|'[^'\r\n]+'|[A-Za-z0-9_./+-]{8,})"
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
_TOKEN_PREFIX_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)


def _relative(path, root):
    return path.relative_to(root).as_posix()


def _repository_files(root):
    root = Path(root).resolve()
    candidates = set()
    if (root / ".git").exists():
        result = subprocess.run(
            [
                "git", "-C", str(root), "ls-files", "--cached", "--others",
                "--exclude-standard", "-z",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            candidates.update(
                root / item.decode("utf-8", "surrogateescape")
                for item in result.stdout.split(b"\0") if item
            )
    if not candidates:
        candidates.update(path for path in root.rglob("*") if path.is_file())
    return sorted(
        (
            path for path in candidates
            if path.is_file()
            and not any(part in _SKIPPED_DIRS for part in path.relative_to(root).parts)
        ),
        key=lambda path: _relative(path, root),
    )


def _read_text(path):
    if path.name == ".env.example" or path.suffix.lower() in _TEXT_SUFFIXES:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ""
    return ""


def _line_number(text, offset):
    return text.count("\n", 0, offset) + 1


def _check_required_artifacts(root):
    issues = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            issues.append(f"missing required file: {relative}")

    for relative in (".github/workflows/ci.yml", "CONTRIBUTING.md"):
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for command in CI_COMMANDS:
            expected = f"- run: {command}" if relative.endswith(".yml") else command
            if expected not in text:
                issues.append(f"{relative}: missing required command: {command}")
    return issues


def _gateway_urls(root):
    path = root / "server" / "gateway.py"
    if not path.is_file():
        return set()
    return set(_GATEWAY_URL_RE.findall(path.read_text(encoding="utf-8")))


def _check_provider_gateways(root):
    issues = []
    security_path = root / "SECURITY.md"
    security = (
        security_path.read_text(encoding="utf-8") if security_path.is_file() else ""
    )
    for url in sorted(_gateway_urls(root)):
        if url not in APPROVED_PROVIDER_GATEWAYS:
            issues.append("server/gateway.py: provider gateway is not approved")
        elif url not in security:
            issues.append(
                "server/gateway.py: provider gateway is not documented in SECURITY.md"
            )
    return issues


def _check_secrets(root, files):
    issues = []
    for path in files:
        relative = _relative(path, root)
        if relative.startswith(_NON_PRODUCTION_PREFIXES):
            continue
        text = _read_text(path)
        if not text:
            continue
        matches = list(_SECRET_ASSIGNMENT_RE.finditer(text))
        matches.extend(_PRIVATE_KEY_RE.finditer(text))
        matches.extend(_TOKEN_PREFIX_RE.finditer(text))
        for match in sorted(matches, key=lambda item: item.start()):
            issues.append(
                f"{relative}:{_line_number(text, match.start())}: possible secret"
            )
    return issues


def _dependency_files(relative):
    name = Path(relative).name.lower()
    return (
        name.startswith("requirements")
        or name in {
            "package.json", "package-lock.json", "pnpm-lock.yaml",
            "pyproject.toml", "yarn.lock",
        }
    )


def _tracking_url(url):
    lower = url.lower().rstrip(".,);]")
    if any(host in lower for host in _TRACKING_HOSTS):
        return True
    return bool(re.search(
        r"https?://(?:analytics|events|metrics|telemetry)\."
        r"[^/]+/(?:[^\s?#]*/)*(?:capture|diagnostics?|events?|track|telemetry)(?:[/?#]|$)",
        lower,
    ))


def _check_zero_telemetry(root, files):
    issues = []
    client_pattern = "|".join(map(re.escape, _TELEMETRY_CLIENTS))
    flag_pattern = "|".join(map(re.escape, _REMOTE_FLAG_CLIENTS))
    dependency_re = re.compile(rf"(?im)^\s*(?:[\"']?)(?:{client_pattern})(?:[\"']?)\s*(?:[=<>~!]|$)")
    import_re = re.compile(
        rf"(?im)(?:^\s*(?:from|import)\s+|\brequire\s*\(|\bfrom\s+[\"'])(?:[^\n]*\b)?(?:{client_pattern})\b"
    )
    flag_re = re.compile(
        rf"(?im)(?:^\s*(?:from|import)\s+|\brequire\s*\(|\bfrom\s+[\"'])(?:[^\n]*\b)?(?:{flag_pattern})\b"
    )
    upload_re = re.compile(
        r"(?i)\b(?:post|send|upload)_(?:diagnostics?|product_?events?|telemetry|usage_?events?)\b"
    )

    documented_gateways = {
        url for url in _gateway_urls(root)
        if url in APPROVED_PROVIDER_GATEWAYS
        and (root / "SECURITY.md").is_file()
        and url in (root / "SECURITY.md").read_text(encoding="utf-8")
    }

    for path in files:
        relative = _relative(path, root)
        if relative.startswith(_NON_PRODUCTION_PREFIXES):
            continue
        text = _read_text(path)
        if not text:
            continue
        if _dependency_files(relative) and dependency_re.search(text):
            issues.append(f"{relative}: telemetry dependency is not allowed")
        elif import_re.search(text):
            issues.append(f"{relative}: telemetry dependency is not allowed")
        if flag_re.search(text):
            issues.append(f"{relative}: remote feature flag client is not allowed")
        if upload_re.search(text):
            issues.append(f"{relative}: product-event or diagnostic upload is not allowed")
        for match in _URL_RE.finditer(text):
            url = match.group(0).rstrip(".,);]")
            if url in documented_gateways:
                continue
            if _tracking_url(url):
                issues.append(
                    f"{relative}:{_line_number(text, match.start())}: tracking or telemetry URL is not allowed"
                )
    return issues


def check_repository(root=ROOT):
    """Return deterministic, secret-safe release policy findings."""
    root = Path(root).resolve()
    files = _repository_files(root)
    issues = []
    issues.extend(_check_required_artifacts(root))
    issues.extend(_check_provider_gateways(root))
    issues.extend(_check_secrets(root, files))
    issues.extend(_check_zero_telemetry(root, files))
    return sorted(set(issues))


def main():
    issues = check_repository(ROOT)
    if issues:
        print("Release verification failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("Release verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
