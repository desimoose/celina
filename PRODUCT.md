# Celina product contract

## What Celina is

Celina is a local-first desktop research application. A user brings their own
model key or uses a local Ollama model. Celina searches the public web without
logging in as the user, reads selected pages, builds a cited answer, and keeps
the research process inspectable.

Celina does not operate a hosted inference service, user account system,
analytics pipeline, or telemetry endpoint.

## Who it serves

Celina is for people who want stronger web research without giving a search
product another behavioral profile. The first release is for Windows desktop
users. Ubuntu follows after the Windows release is stable; macOS follows after
the packaging and signing path is understood.

## Product promise

**Goes and looks. Leaves nothing behind.**

The precise privacy claim is:

> Celina does not log in as you. Sites see a visitor without your account
> history, so results are not shaped by that history and visits are not tied to
> those accounts. Your IP address is not hidden.

Keys and saved work remain on the user's machine. Provider requests go directly
from the user's device to the provider they selected.

## Launch scope

The first public release includes:

- BYOK providers and local Ollama.
- Agentic web research with query decomposition, retrieval, reading, gap
  checking, synthesis, and citation verification.
- An observable search trace showing actions and outcomes, never hidden model
  chain-of-thought.
- A Token Watchtower for provider-reported usage and context consumption.
- A Traffic Controller showing every Celina-managed network request and
  response.
- Session-local traffic records with explicit end-and-delete behavior.
- A local workspace for research the user deliberately keeps.
- A packaged Windows desktop application.

The first public release does not include:

- Celina-hosted inference or API keys.
- Accounts, cloud sync, teams, or remote telemetry.
- Mobile, PWA, or hosted web deployment.
- Network-level anonymity, VPN, proxy, or Tor guarantees.
- Social-platform login automation.
- Background notifications or engagement mechanics.
- Raw private chain-of-thought.

## Product behavior

Celina reports; it does not perform.

- Status language is short, concrete, and generated from observable events.
- The current action is always clear.
- Failures and unavailable sources remain visible.
- A stopped search preserves gathered evidence until the user ends the session.
- Color marks active work; completed work returns to black and white.
- There are no streaks, badges, celebrations, or prompts designed to pull the
  user back.

## Search-quality bar

A search is successful only when:

1. The answer addresses the user's question.
2. Material factual claims have citations.
3. Each citation resolves to content Celina actually retrieved.
4. The cited passage supports the associated claim.
5. Important disagreement and missing evidence are stated plainly.
6. The user can inspect the searches, pages, filters, failures, and corrections
   that produced the answer.

Latency and token cost matter, but neither outranks groundedness.

## Local-data contract

Celina separates two kinds of local data:

- **Kept work:** research the user explicitly saves to the workspace.
- **Session traffic:** temporary operational records created while a research
  session is active.

Ending and deleting a session removes its traffic ledger, raw payload records,
and temporary extracted content. It does not remove kept work unless the user
explicitly chooses that too.

After an unexpected shutdown, an unfinished session is offered for recovery or
deletion on the next launch. Celina never silently promotes temporary traffic
into permanent history.

## Release order

1. Search quality and trace correctness.
2. Session privacy, Token Watchtower, and Traffic Controller.
3. Approved desktop interface.
4. Windows packaging, documentation, and public repository.
5. Ubuntu.
6. macOS.
