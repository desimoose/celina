# Local Session Memory and Skill Learning Plan

## 1. Scope

Celina will be able to reduce an ended research session into a small,
inspectable local capsule and delete the large temporary ledger. Capsules can
be recalled for later searches. Repeated successful workflow patterns may
become skill proposals, but only explicit user approval can activate a skill.

### Included in the MVP

- Deterministic, offline capsule creation.
- Transactional capsule persistence before session deletion.
- SQLite full-text retrieval.
- Provenance back to the originating session and verified sources.
- User-controlled inspect, edit, export, and forget operations.
- Skill candidates derived from allowlisted execution outcomes.
- Explicit approve, reject, disable, revise, and version operations.
- A prompt-injection boundary preventing retrieved page instructions from
  becoming skills.
- Tests and Windows packaging verification.

### Excluded from the MVP

- Training or fine-tuning model weights.
- Automatic activation of proposed skills.
- Cloud memory, telemetry, or cross-device synchronization.
- Remote embedding services.
- Learning instructions directly from web content.
- Permanent retention of raw traffic, provider prompts, or extracted pages.
- Background behavior profiling.

**Effort:** Two to four focused engineering days for the subsystem and API
integration after the secure local API is available.

**Risk:** Medium-high. The implementation is local, but retention mistakes can
undermine the product's privacy promise.

## 2. Defaults and decisions

### Compression mode

**Default:** Deterministic local extraction. No provider call is required.

The compressor receives a completed run snapshot plus ledger summaries. It
keeps verified findings, citations, uncertainties, gaps, conflicts, successful
observable methods, failed observable methods, tags, and explicit user
feedback.

**Optional later mode:** The user may explicitly allow the currently selected
BYOK/local model to rewrite the capsule for readability. The deterministic
capsule remains the source of truth and is never replaced without review.

### Retention

Ending a session offers:

1. **Delete everything**
2. **Keep compressed memory**
3. **Keep research note** (existing workspace behavior)

For option 2, Celina writes and verifies the capsule transactionally, then
deletes the session SQLite database, WAL, SHM, traffic bodies, and extracted
content. Kept workspace notes are untouched.

### Recall

SQLite FTS5 is the first retrieval engine. It is local, inspectable,
deterministic, and dependency-free. Optional local embeddings can be evaluated
later, but capsule retrieval must always work without them.

At most three memories are recalled into a run. Each recalled capsule is shown
to the user and recorded in the trace.

### Skills

Knowledge and behavior are stored separately:

- Capsules contain factual/session memory.
- Skills contain reusable operating instructions.

A skill proposal requires repeated support from at least three successful
capsules by default. A proposal remains inactive until the user approves it.

No arbitrary source text is eligible for skill generation. Only allowlisted
method identifiers emitted by Celina itself may contribute:

```text
prefer_primary_sources
prefer_full_text
use_recent_sources
compare_conflicting_sources
try_search_fallback
read_before_synthesis
verify_citations
```

## 3. Data model

One global database:

```text
<CELINA_HOME>/memory/memory.sqlite3
```

### memory_capsule

```text
capsule_id
schema_version
title
question
summary
verified_findings_json
uncertainties_json
gaps_json
conflicts_json
source_references_json
successful_methods_json
failed_methods_json
user_feedback_json
tags_json
origin_session_id
origin_run_id
created_at
updated_at
compression_mode
```

### memory_capsule_fts

FTS fields:

```text
title
question
summary
verified_findings
tags
```

### skill

```text
skill_id
name
version
status
trigger_json
instructions_json
supporting_capsule_ids_json
created_at
updated_at
```

Statuses:

```text
proposed -> active -> disabled
proposed -> rejected
active -> superseded
```

Every edit creates a new version. Historical versions remain locally
inspectable until the skill is explicitly forgotten.

## 4. Core interfaces

```python
CapsuleCompressor.compress(session, run, feedback=None) -> MemoryCapsule

MemoryStore.save_capsule(capsule) -> MemoryCapsule
MemoryStore.get_capsule(capsule_id) -> MemoryCapsule | None
MemoryStore.search(query, limit=3) -> list[MemoryMatch]
MemoryStore.list_capsules() -> list[MemoryCapsule]
MemoryStore.delete_capsule(capsule_id) -> bool
MemoryStore.export_capsule(capsule_id) -> dict

MemoryService.keep_and_delete(session_id, run, feedback=None)
    -> MemoryArchiveResult

SkillLearner.propose(capsules) -> list[Skill]
SkillStore.approve(skill_id) -> Skill
SkillStore.reject(skill_id) -> Skill
SkillStore.disable(skill_id) -> Skill
SkillStore.revise(skill_id, changes) -> Skill
SkillStore.active_for(query_context) -> list[Skill]
```

`keep_and_delete` is ordered:

1. Compress.
2. Persist in a database transaction.
3. Read the capsule back and validate it.
4. Delete the temporary session.
5. Return both capsule ID and deletion result.

If steps 1–3 fail, the session is preserved. If deletion fails, the capsule
remains and the result explicitly reports partial completion.

## 5. Capsule content rules

Capsules may retain:

- User question.
- Verified answer findings.
- Stable citation metadata and public URLs.
- Explicit uncertainties, evidence gaps, and conflicts.
- Search methods represented by allowlisted identifiers.
- User feedback deliberately supplied to the capsule.
- Model/provider names as provenance, never keys.

Capsules must not retain:

- Authorization headers, cookies, API keys, or environment values.
- Raw request/response bodies.
- Raw provider prompts.
- Complete extracted page bodies.
- Hidden reasoning.
- Arbitrary instructions found in source content.
- Raw exception messages.

Source references retain title, URL, citation ID, source kind, and a short
supporting passage. Passages are bounded and pass through the existing
Redactor.

## 6. Skill proposal rules

A proposed skill must:

- Use only allowlisted method identifiers.
- Be supported by at least three distinct capsules.
- Include supporting capsule IDs.
- Contain no URL, source passage, provider response, or secret-like value.
- Explain the observable behavior it changes.
- Remain inactive until approval.

Initial mappings are deterministic:

```text
prefer_primary_sources
  -> "Prioritize primary sources when available."

prefer_full_text
  -> "Prefer sources whose full content can be read."

compare_conflicting_sources
  -> "When credible sources conflict, represent both before concluding."

verify_citations
  -> "Verify every material cited claim against retrieved page content."
```

This is workflow learning, not model self-modification.

## 7. User experience

### Ending a session

```text
End session
  ├─ Delete everything
  ├─ Keep compressed memory
  └─ Cancel
```

Before confirming memory:

```text
Will keep
- Question and short summary
- 4 verified findings
- 6 source references
- 2 unresolved gaps

Will delete
- 31 traffic records
- request/response bodies
- extracted pages
- temporary session database
```

### Recalling memory

Before search begins:

```text
2 relevant local memories found
[Use] [Inspect] [Ignore]
```

Applied memories appear in the trace as public actions. They never silently
alter a run.

### Skill review

```text
Proposed skill
"Prefer full-text primary sources for scientific questions."

Supported by 5 successful sessions.

[Approve] [Edit] [Reject]
```

## 8. Implementation milestones

### Milestone A: Paths, schema, and capsule store

- Add memory directory path.
- Add SQLite schema and short-lived connection handling.
- Add capsule CRUD, export, and FTS search.
- Test concurrent reads, deletion, malformed IDs, and Windows handle release.

### Milestone B: Deterministic compression

- Convert completed `SearchRun` state into a capsule.
- Keep verified structured claims and bounded passages.
- Redact before persistence.
- Reject active/incomplete runs.
- Test canary secrets against database bytes.

### Milestone C: Transactional keep-and-delete

- Persist and verify capsule before deleting the session.
- Preserve session on compression/persistence failure.
- Report deletion failure without losing the capsule.
- Confirm workspace siblings survive.

### Milestone D: Skill proposals and versioning

- Count allowlisted successful methods across capsules.
- Propose only after the support threshold.
- Add approval/rejection/disable/revision state machine.
- Ensure proposed skills are inactive.
- Reject arbitrary instructions and secret-like content.

### Milestone E: Recall integration

- Retrieve up to three capsules using FTS.
- Add explicit run selection of memory IDs.
- Add public `memory.recalled` and `skill.applied` event templates.
- Feed bounded capsule facts and approved skills to planning.
- Track whether recalled memory improved or harmed the result.

This milestone lands after the secure local search API so recall choices are
authorized and visible.

### Milestone F: API and UI

Add secure local endpoints:

```text
GET    /api/memories
GET    /api/memories/search?q=
GET    /api/memories/{id}
DELETE /api/memories/{id}
POST   /api/sessions/{id}/compress-and-end

GET    /api/skills
POST   /api/skills/{id}/approve
POST   /api/skills/{id}/reject
POST   /api/skills/{id}/disable
POST   /api/skills/{id}/revise
```

Add Memory and Skills screens only after the secure API and current search
workspace are functional.

### Milestone G: Packaging

- Ensure the memory modules are included in the frozen application.
- Build the Windows executable.
- Run the executable against a fresh `CELINA_HOME`.
- Create, retrieve, export, and delete a capsule.
- Confirm no network activity occurs during local recall.

## 9. Test and privacy gates

- TDD for every behavior.
- Full suite with `ResourceWarning` promoted to failure.
- Canary secret scan of memory SQLite/WAL/SHM.
- Corpus test proving source instructions cannot become skills.
- FTS search requires no internet.
- Proposed skills never appear in active skill lookup.
- Deleting a capsule removes it from FTS immediately.
- Memory export contains no raw traffic bodies.
- Session deletion occurs only after capsule verification.
- Frozen executable passes a clean-home smoke test.

## 10. Rollout and rollback

- The memory subsystem is additive and disabled unless the user chooses Keep
  compressed memory.
- Existing Delete behavior remains available.
- Search does not consume memories until explicit recall integration lands.
- A broken capsule database cannot prevent normal private search.
- Disabling memory leaves session behavior unchanged.
- Each milestone is independently committed and revertible.

## 11. Definition of done

- The user can intentionally compress a completed session.
- The large temporary ledger is deleted only after verified capsule storage.
- Capsules are searchable and removable entirely offline.
- No raw traffic, credentials, or hidden reasoning reaches memory storage.
- Web content cannot generate skill instructions.
- Repeated successful allowlisted methods can create proposals.
- Skills require explicit approval and support versioning/disable/delete.
- Recall and skill application are visible in the trace.
- The Windows build passes a fresh-home memory smoke test.
