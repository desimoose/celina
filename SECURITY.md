# Security policy

## Scope and supported versions

The current released version and the current `main` branch are supported for
security reports. Celina is a local-first Windows desktop research and
adult-learning application; it is not a hosted service. Older releases may
not receive fixes, so upgrade to the current release before reporting an issue
when practical.

## Security model

Read [the security model](docs/SECURITY_MODEL.md) for assets, trust boundaries,
attacker personas, release invariants, guarantees, and residual risks. Read
[the operations runbook](docs/OPERATIONS.md) for backup, restore, corruption
recovery, diagnostics, and incident procedures.

Important invariants include `URL_PUBLIC_ONLY`, `UNTRUSTED_SOURCE_DATA`,
`BOUNDED_MUTATION`, `ATOMIC_LOCAL_STATE`, `DURABLE_IDEMPOTENCY`,
`EPHEMERAL_INCOGNITO`, `NO_SECRET_OUTPUT`, and `NO_TELEMETRY`.

## Guarantees and privacy limits

Celina binds locally by default, stores kept work locally, and does not
collect, transmit, persist, or infer product-usage telemetry. There are no
analytics SDKs, tracking pixels, crash-reporting clients, usage events,
phone-home checks, remote feature flags, or hidden outbound requests.
Diagnostics are local-only and user-invoked. Explicit requests to the selected
provider are not product telemetry.

Ollama is local-only. A hosted provider receives the user's configured
question and bounded context. Incognito deletes Celina-local session traffic,
but cannot control third-party provider retention, website logs, OS access, or
network observation. Celina does not promise anonymity, VPN/proxy/Tor
protection, or security against a same-machine user with equivalent OS access.

## Private disclosure

Please report suspected vulnerabilities privately before public disclosure.
Use the repository's private security contact or the hosting provider's
private vulnerability-reporting mechanism, and include:

- affected version or commit;
- a concise impact statement and reproducible steps;
- disposable fixtures, fake credentials, and sanitized logs;
- any proposed mitigation and whether data may have been exposed.

Do not include real provider keys, private notebooks, personal data, or live
workspace exports. If private contact is unavailable, open an issue asking
for a secure channel without describing the vulnerability or including
secrets.

## Safe testing boundaries

Test only against a disposable local checkout, fake credentials, and systems
you own or have explicit permission to test. Do not attack real websites,
providers, users, or the live workspace. Do not run autonomous red-team tools
against real user data or real provider credentials. Avoid denial-of-service,
credential testing, persistence, or exfiltration. A safe report can use a
malicious webpage, hostile PDF, compromised provider fixture, same-machine
user permission scenario, or release supply chain fixture without contacting
third parties.
