# Contributing to Celina

Celina is a local-first application with a deliberately small dependency and
network surface. Contributions should preserve the security invariants in
`SECURITY.md` and `docs/SECURITY_MODEL.md`, especially `NO_TELEMETRY`, provider
disclosure, loopback-only defaults, bounded untrusted input, and local-only
diagnostics.

## Development setup

Use Python 3.12 or newer and Node.js 20 or newer. The core server uses the
Python standard library; `pypdf` is the only optional runtime dependency.

```powershell
python -m pip install -r requirements.txt
```

Do not commit `.env`, provider credentials, private notebooks, session data,
or generated workspace data. Use empty values in `.env.example` and fake,
disposable credentials in tests.

## Required checks

Run these commands from the repository root before submitting a change:

```powershell
python -m unittest discover -s tests -q
node --test tests/test_privacy_ui.js tests/test_search_capture.js
python -c "import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('server').glob('*.py')]"
node --check web/app.js
git diff --check
python scripts/verify_release.py
```

The release verifier checks required security documentation, CI metadata,
conservative secret patterns, prohibited telemetry/crash-reporting
dependencies, tracking endpoints, remote feature flags, and product-event or
diagnostic uploads. Tests and fixtures may use fake adversarial values; never
copy a live secret into them.

## Network and dependency changes

New runtime dependencies and outbound destinations require explicit security
review. Analytics, crash reporting, tracking pixels, remote feature flags,
usage events, and remote diagnostic uploads are not accepted. Hosted AI calls
must remain user-initiated, route through `server/gateway.py`, and match an
endpoint and privacy disclosure listed in `SECURITY.md`. Ollama remains local.

## Security reports

Do not open a public issue containing a vulnerability or secret. Follow the
private disclosure and safe-testing instructions in `SECURITY.md`.
