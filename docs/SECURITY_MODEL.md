# Celina security model

Celina is a local-first research and adult-learning tool. It runs on the
user's machine, binds its server to loopback by default, and keeps notebooks,
projects, and session data under the existing local workspace and data roots.
The model protects the learner's questions, reading context, saved work, and
provider credentials while keeping the boundaries of web research visible.

## Assets and trust boundaries

The protected assets are provider keys, launch and session cookies, CSRF
tokens, notebook and project files, temporary session traffic, source
documents and excerpts, tutor questions and context, and the integrity of
local and packaged code.

Celina treats these boundaries as distinct:

1. The browser to the loopback HTTP server. Browser input, cookies, and
   imported files are untrusted; request validation, CSRF protection, and the
   launch-cookie guard protect state-changing and private routes.
2. The server to the public URL fetcher and every redirect target. URLs,
   redirects, HTML, PDFs, and search snippets are hostile input and are
   accepted only within public-network, size, and parsing limits.
3. The server to PDF and HTML extraction tools. Extracted text is data, not
   instructions or executable markup.
4. The server to hosted AI providers or local Ollama. A hosted provider
   receives the configured question and bounded context for the selected
   operation. Ollama is labeled local-only and can keep inference on the
   machine.
5. The server to notebook, project, and session files. Paths remain inside
   Celina-managed roots; temporary session data is distinct from kept work.
6. Release source to generated artifacts and bundled tools. Builds use pinned,
   hash-checked inputs; generated artifacts and tools are release inputs that
   must be reviewed as untrusted until verified.

## Attacker personas

- A **malicious webpage** attempts SSRF, redirect abuse, oversized responses,
  or prompt injection through visible content.
- A **hostile PDF** or HTML document contains instructions, active content,
  malformed structure, or data intended to escape extraction limits.
- A **compromised provider** returns malicious, malformed, secret-seeking, or
  misleading content and must not gain local authorization.
- A **same-machine user** may read files available to the operating-system
  account; Celina does not replace OS permissions or disk encryption.
- The **release supply chain** may tamper with source, generated artifacts,
  dependencies, or bundled tools.

## Release invariants

These identifiers are the contract used by tests and release review:

- `URL_PUBLIC_ONLY`: outbound research fetches use HTTP(S), validate every
  redirect, and reject loopback, private, link-local, mapped, and other
  non-public destinations.
- `UNTRUSTED_SOURCE_DATA`: web, PDF, HTML, search, notebook-import, and
  provider content is quoted evidence, never an instruction or authorization.
- `BOUNDED_MUTATION`: request bodies, extracted content, persisted records,
  retries, and other mutations have explicit size, count, and time limits.
- `ATOMIC_LOCAL_STATE`: local JSON, SQLite, and project writes are bounded and
  recoverable; interrupted writes must not replace a valid prior state with a
  partial file.
- `DURABLE_IDEMPOTENCY`: retry-safe mutations have a durable replay contract
  across server restarts, with conflict and in-progress outcomes.
- `EPHEMERAL_INCOGNITO`: Incognito session traffic is temporary and is removed
  locally when the session ends, the page closes, or the server restarts.
- `NO_SECRET_OUTPUT`: keys, cookies, CSRF values, raw secret-bearing prompts,
  and secret-bearing exception text do not appear in UI output, diagnostics,
  logs, or persisted telemetry-like records.
- `NO_TELEMETRY`: Celina does not collect, transmit, persist, or infer
  product-usage telemetry. It has no analytics SDKs, tracking pixels,
  crash-reporting clients, usage events, phone-home checks, remote feature
  flags, or hidden outbound requests. Diagnostics are local-only and
  user-invoked; provider requests are the explicit exception described above.
  Automatic and anonymous update checks are disabled. The local update-status
  route reports only the bundled version and explicitly states that no remote
  check occurred.

## Guarantees and non-guarantees

Celina guarantees local-first storage by default, loopback binding by default,
bounded and labeled source handling, explicit provider disclosure, local
Incognito cleanup, and no product telemetry. With Ollama selected, inference
can remain local; external web retrieval still contacts the requested public
sites unless the user runs an entirely offline workflow.

Celina does not guarantee anonymity, VPN/proxy/Tor behavior, protection from a
malicious process with the same OS account, recovery from disk failure without
backups, or control over a hosted provider's retention, training, abuse
monitoring, or logs. Incognito cannot control third-party provider retention.
Normal and Incognito deletion remove and verify Celina-local session residue
only. They do not send deletion requests to hosted providers and cannot delete
question or context copies already retained in provider logs, abuse-monitoring
systems, backups, or training pipelines. Provider retention periods and data
use depend on the selected provider, account plan, and current provider policy;
users must review those terms before sending a request. Celina labels hosted
providers as receiving question/context, with provider retention policies
applying, before requests are sent. The user remains responsible for provider
terms, credentials, OS access, and the trustworthiness of files they
deliberately keep.

## Review record and residual risks

| Feature | Assets | Security/reliability invariant | Control | Status | Residual risk |
| --- | --- | --- | --- | --- | --- |
| Public research fetch | Network, local parser | `URL_PUBLIC_ONLY`, `BOUNDED_MUTATION` | Validate each target and cap response/extraction | mitigated | DNS rebinding and OS networking remain outside Celina's full control |
| Tutor context | Questions, source text, keys | `UNTRUSTED_SOURCE_DATA`, `NO_SECRET_OUTPUT` | Label evidence, keep system instructions separate, bound context | mitigated | A provider can retain or mishandle data it receives |
| Notebook/project writes | Kept work | `ATOMIC_LOCAL_STATE`, `BOUNDED_MUTATION` | Root-bound, atomic local writes and recovery guidance | mitigated | Hardware/filesystem failure can still destroy data |
| Session privacy | Temporary traffic | `EPHEMERAL_INCOGNITO` | Delete local session records; audit directory, ledger, SQLite row, and sidecars; retain a metadata-only retry marker on incomplete cleanup | mitigated | Notebook files remain kept work; provider/site/server OS logs and backups may remain outside Celina |
| Update checks | Product metadata, network | `NO_TELEMETRY` | Version route is local-only; automatic remote update checks and browser calls are disabled | mitigated | Users must obtain and verify updates through their chosen distribution channel |
| Release artifacts | Code and bundled tools | `NO_TELEMETRY`, `NO_SECRET_OUTPUT` | Review, tests, hashes, and release checks | mitigated | A compromised build environment remains a supply-chain risk |

## Verification

Run the focused contract test with:

```text
python -m unittest tests.test_security_docs.SecurityDocumentationTest.test_security_documents_cover_required_threats_and_invariants -v
```

Run the Python suite with:

```text
python -m unittest discover -s tests -q
```

Do not run autonomous red-team tooling against real user data, real provider
credentials, or a live workspace. Use disposable fixtures and fake keys.
