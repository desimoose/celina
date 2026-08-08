# Celina operations and recovery

Celina is operated as a local-first desktop application for private research
and adult-learning workflows. The normal operating mode is a loopback server,
local workspace, and a user-selected provider. Celina has no account service,
remote control plane, or product-usage telemetry.

## Normal checks

Before a release or after an upgrade, run:

```text
python -m unittest tests.test_security_docs -v
python -m unittest discover -s tests -q
```

Confirm that the server is bound to loopback, the selected provider label is
correct, and the data roots are the expected `workspace/`, `projects/`, and
session locations. A health or diagnostic check, when available, is local-only
and user-invoked; it must not contact a remote service or expose secrets.

## Backup

Stop Celina before making a backup. Copy the user-managed `workspace/` and
`projects/` directories, plus any explicitly configured local data directory,
to a user-controlled backup destination with appropriate OS permissions. Do
not copy `.env` or provider keys unless the backup is encrypted and the user
intentionally accepts that risk. Session traffic is temporary and should not
be promoted into kept work merely because it exists on disk.

Record the Celina version and backup date. Keep at least one backup separate
from the machine running Celina. Backups are the recovery path for accidental
deletion, disk failure, and bad upgrades; Celina does not upload backups.

## Restore

1. Stop Celina and preserve the current data directory for inspection.
2. Create the expected local roots and verify their OS ownership and
   permissions.
3. Restore `workspace/` and `projects/` from a known-good backup.
4. Start Celina and inspect notebooks, projects, and session cleanup before
   continuing normal work.
5. Run the focused documentation test and the full Python suite.

Restore only into the Celina-managed roots. Do not follow unknown symlinks or
copy files from an untrusted archive into a path used for writes.

## Corruption and interrupted writes

If a notebook, project, or session file is malformed, stop editing it and
preserve a copy of the evidence. Restore the last known-good backup or use an
application-provided recovery path; do not hand-edit a damaged file while the
server is running. A failed write should leave the prior valid local state in
place under `ATOMIC_LOCAL_STATE`. If this invariant is violated, treat it as a
release-blocking reliability defect and retain the failing fixture for a
regression test.

If a server restart interrupts a retryable mutation, retry with the same
idempotency key where supported. `DURABLE_IDEMPOTENCY` requires a completed
response to replay and a conflicting payload to be rejected; never guess
whether a non-idempotent mutation completed.

## Privacy and provider disclosure

`EPHEMERAL_INCOGNITO` removes Celina-local session traffic when the session
ends, the page closes, or the server restarts. It cannot control retention by
websites, hosted AI providers, DNS services, the operating system, or a
network administrator. Incognito cannot control third-party provider
retention.

Ollama is labeled local-only. Hosted providers receive the configured
question and bounded context needed for the selected operation. Users must
review each provider's terms and retention policy before sending sensitive
material. Celina does not claim that provider requests are anonymous.

## Diagnostics and incidents

For a suspected incident, stop the server, preserve relevant local files, and
record the Celina version, selected provider, route/action, time, and a
minimal reproduction without secrets. Redact keys, cookies, CSRF values,
private source text, and raw prompts. Check for unexpected files or outbound
requests, but do not run autonomous tooling against real credentials or the
live workspace.

The incident response priorities are: contain outbound access, protect keys,
preserve evidence, restore from a known-good backup if integrity is uncertain,
and add a disposable regression fixture. `NO_SECRET_OUTPUT` and
`NO_TELEMETRY` mean diagnostics must not become a second data collection
channel: Celina does not collect, transmit, persist, or infer product-usage
telemetry, and diagnostics are local-only and user-invoked.

## Upgrade and release procedure

Review the changelog and security model, back up kept work, stop Celina, apply
the signed or otherwise verified release, and start it with the existing local
roots. Run the focused documentation test and full Python suite. Verify that
Ollama remains labeled local-only, hosted-provider disclosure is present, and
no new analytics, tracking, phone-home, remote feature-flag, or hidden network
behavior was introduced. Release artifacts and bundled tools are part of the
`release supply chain` and must be checked accordingly.
