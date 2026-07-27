"""Local session capsules and approval-gated workflow skills."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
import uuid

import paths
import redaction


_DB_NAME = "memory.sqlite3"
_SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_METHODS = {
    "prefer_primary_sources": "Prioritize primary sources when available.",
    "prefer_full_text": "Prefer sources whose full content can be read.",
    "use_recent_sources": "Use recent sources for time-sensitive questions.",
    "compare_conflicting_sources": (
        "Represent credible conflicting sources before concluding."
    ),
    "try_search_fallback": (
        "Use a fallback search backend when the first source fails."
    ),
    "read_before_synthesis": (
        "Synthesize only from sources whose full content was read."
    ),
    "verify_citations": (
        "Verify material cited claims against retrieved page content."
    ),
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class MemoryConflict(Exception):
    pass


class IncompleteRun(Exception):
    pass


@dataclass(frozen=True)
class MemoryCapsule:
    capsule_id: str
    schema_version: int
    title: str
    question: str
    summary: str
    verified_findings: tuple[str, ...]
    uncertainties: tuple[str, ...]
    gaps: tuple[str, ...]
    conflicts: tuple[str, ...]
    source_references: tuple[dict, ...]
    successful_methods: tuple[str, ...]
    failed_methods: tuple[str, ...]
    user_feedback: tuple[str, ...]
    tags: tuple[str, ...]
    origin_session_id: str
    origin_run_id: str
    created_at: str
    updated_at: str
    compression_mode: str

    @classmethod
    def create(
        cls,
        title,
        question,
        summary,
        verified_findings,
        uncertainties,
        gaps,
        conflicts,
        source_references,
        successful_methods,
        failed_methods,
        user_feedback,
        tags,
        origin_session_id,
        origin_run_id,
        compression_mode="deterministic-local",
    ):
        now = _utc_now()
        return cls(
            str(uuid.uuid4()),
            _SCHEMA_VERSION,
            str(title).strip(),
            str(question).strip(),
            str(summary).strip(),
            tuple(verified_findings or ()),
            tuple(uncertainties or ()),
            tuple(gaps or ()),
            tuple(conflicts or ()),
            tuple(dict(item) for item in source_references or ()),
            tuple(successful_methods or ()),
            tuple(failed_methods or ()),
            tuple(user_feedback or ()),
            tuple(tags or ()),
            origin_session_id,
            origin_run_id,
            now,
            now,
            compression_mode,
        )

    def to_dict(self):
        value = {
            key: getattr(self, key)
            for key in self.__dataclass_fields__
        }
        for key in (
            "verified_findings",
            "uncertainties",
            "gaps",
            "conflicts",
            "source_references",
            "successful_methods",
            "failed_methods",
            "user_feedback",
            "tags",
        ):
            value[key] = list(value[key])
        return value


@dataclass(frozen=True)
class MemoryMatch:
    capsule: MemoryCapsule
    score: float


@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    version: int
    status: str
    trigger: dict
    instructions: tuple[str, ...]
    supporting_capsule_ids: tuple[str, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class MemoryArchiveResult:
    capsule_id: str
    capsule_saved: bool
    session_deleted: bool
    deletion_errors: tuple[str, ...]


class MemoryStore:
    def __init__(self, root=None):
        self.root = os.path.realpath(root or paths.memory_dir())
        os.makedirs(self.root, exist_ok=True)
        self.database = os.path.join(self.root, _DB_NAME)
        with self._connection() as connection:
            self._create_schema(connection)

    def save_capsule(self, capsule):
        if not isinstance(capsule, MemoryCapsule):
            raise TypeError("capsule must be a MemoryCapsule")
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO memory_capsule VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?
                    )
                    """,
                    self._capsule_values(capsule),
                )
                connection.execute(
                    """
                    INSERT INTO memory_capsule_fts VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        capsule.capsule_id,
                        capsule.title,
                        capsule.question,
                        capsule.summary,
                        " ".join(capsule.verified_findings),
                        " ".join(capsule.tags),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise MemoryConflict("capsule already exists") from error
        return self.get_capsule(capsule.capsule_id)

    def get_capsule(self, capsule_id):
        self._validate_id(capsule_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM memory_capsule WHERE capsule_id = ?",
                (capsule_id,),
            ).fetchone()
        return self._capsule_from_row(row) if row else None

    def list_capsules(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_capsule ORDER BY created_at DESC"
            ).fetchall()
        return [self._capsule_from_row(row) for row in rows]

    def search(self, query, limit=3):
        terms = re.findall(r"[A-Za-z0-9]+", str(query or ""))
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms[:12])
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT capsule_id, bm25(memory_capsule_fts) AS rank
                FROM memory_capsule_fts
                WHERE memory_capsule_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (expression, max(1, min(int(limit), 20))),
            ).fetchall()
        matches = []
        for row in rows:
            capsule = self.get_capsule(row["capsule_id"])
            if capsule:
                matches.append(MemoryMatch(
                    capsule,
                    1.0 / (1.0 + abs(float(row["rank"]))),
                ))
        return matches

    def delete_capsule(self, capsule_id):
        self._validate_id(capsule_id)
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM memory_capsule_fts WHERE capsule_id = ?",
                (capsule_id,),
            )
            cursor = connection.execute(
                "DELETE FROM memory_capsule WHERE capsule_id = ?",
                (capsule_id,),
            )
        return cursor.rowcount == 1

    def export_capsule(self, capsule_id):
        capsule = self.get_capsule(capsule_id)
        return capsule.to_dict() if capsule else None

    def save_skill(self, skill):
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO skill VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._skill_values(skill),
            )
        return self.get_skill(skill.skill_id)

    def get_skill(self, skill_id):
        self._validate_id(skill_id)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM skill WHERE skill_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (skill_id,),
            ).fetchone()
        return self._skill_from_row(row) if row else None

    def approve_skill(self, skill_id):
        return self._set_skill_status(skill_id, "active", {"proposed"})

    def reject_skill(self, skill_id):
        return self._set_skill_status(skill_id, "rejected", {"proposed"})

    def disable_skill(self, skill_id):
        return self._set_skill_status(skill_id, "disabled", {"active"})

    def revise_skill(self, skill_id, instructions):
        current = self.get_skill(skill_id)
        if current is None:
            raise KeyError("unknown skill")
        safe = tuple(
            str(item).strip()
            for item in instructions
            if str(item).strip()
        )
        if not safe:
            raise ValueError("instructions are required")
        now = _utc_now()
        with self._connection() as connection:
            if current.status == "active":
                connection.execute(
                    """
                    UPDATE skill SET status = 'superseded', updated_at = ?
                    WHERE skill_id = ? AND version = ?
                    """,
                    (now, skill_id, current.version),
                )
            connection.execute(
                """
                INSERT INTO skill VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    current.name,
                    current.version + 1,
                    json.dumps(current.trigger, separators=(",", ":")),
                    json.dumps(safe, separators=(",", ":")),
                    json.dumps(
                        current.supporting_capsule_ids,
                        separators=(",", ":"),
                    ),
                    now,
                    now,
                ),
            )
        return self.get_skill(skill_id)

    def active_skills(self):
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT item.* FROM skill AS item
                JOIN (
                    SELECT skill_id, MAX(version) AS version
                    FROM skill GROUP BY skill_id
                ) AS latest
                ON latest.skill_id = item.skill_id
                AND latest.version = item.version
                WHERE item.status = 'active'
                ORDER BY item.name
                """
            ).fetchall()
        return [self._skill_from_row(row) for row in rows]

    def _set_skill_status(self, skill_id, status, allowed):
        current = self.get_skill(skill_id)
        if current is None:
            raise KeyError("unknown skill")
        if current.status not in allowed:
            raise MemoryConflict(
                f"cannot change skill from {current.status} to {status}"
            )
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE skill SET status = ?, updated_at = ?
                WHERE skill_id = ? AND version = ?
                """,
                (status, _utc_now(), skill_id, current.version),
            )
        return self.get_skill(skill_id)

    @staticmethod
    def _validate_id(value):
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ValueError("invalid memory identifier")

    @staticmethod
    def _capsule_values(item):
        return (
            item.capsule_id,
            item.schema_version,
            item.title,
            item.question,
            item.summary,
            json.dumps(item.verified_findings, separators=(",", ":")),
            json.dumps(item.uncertainties, separators=(",", ":")),
            json.dumps(item.gaps, separators=(",", ":")),
            json.dumps(item.conflicts, separators=(",", ":")),
            json.dumps(item.source_references, separators=(",", ":")),
            json.dumps(item.successful_methods, separators=(",", ":")),
            json.dumps(item.failed_methods, separators=(",", ":")),
            json.dumps(item.user_feedback, separators=(",", ":")),
            json.dumps(item.tags, separators=(",", ":")),
            item.origin_session_id,
            item.origin_run_id,
            item.created_at,
            item.updated_at,
            item.compression_mode,
        )

    @staticmethod
    def _skill_values(item):
        return (
            item.skill_id,
            item.name,
            item.version,
            item.status,
            json.dumps(item.trigger, separators=(",", ":")),
            json.dumps(item.instructions, separators=(",", ":")),
            json.dumps(item.supporting_capsule_ids, separators=(",", ":")),
            item.created_at,
            item.updated_at,
        )

    @staticmethod
    def _capsule_from_row(row):
        return MemoryCapsule(
            row["capsule_id"],
            row["schema_version"],
            row["title"],
            row["question"],
            row["summary"],
            tuple(json.loads(row["verified_findings_json"])),
            tuple(json.loads(row["uncertainties_json"])),
            tuple(json.loads(row["gaps_json"])),
            tuple(json.loads(row["conflicts_json"])),
            tuple(json.loads(row["source_references_json"])),
            tuple(json.loads(row["successful_methods_json"])),
            tuple(json.loads(row["failed_methods_json"])),
            tuple(json.loads(row["user_feedback_json"])),
            tuple(json.loads(row["tags_json"])),
            row["origin_session_id"],
            row["origin_run_id"],
            row["created_at"],
            row["updated_at"],
            row["compression_mode"],
        )

    @staticmethod
    def _skill_from_row(row):
        return Skill(
            row["skill_id"],
            row["name"],
            row["version"],
            row["status"],
            json.loads(row["trigger_json"]),
            tuple(json.loads(row["instructions_json"])),
            tuple(json.loads(row["supporting_capsule_ids_json"])),
            row["created_at"],
            row["updated_at"],
        )

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection):
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_capsule (
                capsule_id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL,
                title TEXT NOT NULL,
                question TEXT NOT NULL,
                summary TEXT NOT NULL,
                verified_findings_json TEXT NOT NULL,
                uncertainties_json TEXT NOT NULL,
                gaps_json TEXT NOT NULL,
                conflicts_json TEXT NOT NULL,
                source_references_json TEXT NOT NULL,
                successful_methods_json TEXT NOT NULL,
                failed_methods_json TEXT NOT NULL,
                user_feedback_json TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                origin_session_id TEXT NOT NULL,
                origin_run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                compression_mode TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_capsule_fts USING fts5(
                capsule_id UNINDEXED, title, question, summary,
                verified_findings, tags
            );
            CREATE TABLE IF NOT EXISTS skill (
                skill_id TEXT NOT NULL,
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                status TEXT NOT NULL,
                trigger_json TEXT NOT NULL,
                instructions_json TEXT NOT NULL,
                supporting_capsule_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (skill_id, version)
            );
            """
        )


class CapsuleCompressor:
    def __init__(self, redactor=None):
        self.redactor = redactor or redaction.Redactor()

    def compress(self, session_id, run, feedback=None):
        if run.state != "completed":
            raise IncompleteRun("only completed runs can become memories")
        verification = getattr(run, "verification", None)
        claims = [
            item
            for item in getattr(verification, "claims", ())
            if item.status == "supported"
        ]
        evidence_by_id = {
            item.citation_id: item
            for item in getattr(run, "evidence", ())
        }
        references = []
        seen = set()
        for claim in claims:
            for citation_id in claim.citation_ids:
                if citation_id in seen:
                    continue
                item = evidence_by_id.get(citation_id)
                if item is None or not item.was_read:
                    continue
                references.append({
                    "citation_id": citation_id,
                    "title": self._safe(item.title),
                    "url": self.redactor.redact_url(item.url),
                    "source_kind": item.source_kind,
                    "supporting_passage": self._safe(
                        (claim.supporting_passage or "")[:500]
                    ),
                })
                seen.add(citation_id)
        answer = getattr(run, "answer", None)
        summary = (
            answer.get("answer", "")
            if isinstance(answer, dict)
            else str(answer or "")
        )
        question = self._safe(getattr(run, "query", ""))
        return MemoryCapsule.create(
            title=question[:80] or "Research memory",
            question=question,
            summary=self._safe(summary[:1200]),
            verified_findings=[self._safe(item.text) for item in claims],
            uncertainties=[],
            gaps=[self._safe(item) for item in getattr(run, "gaps", ())],
            conflicts=[
                self._safe(item) for item in getattr(run, "conflicts", ())
            ],
            source_references=references,
            successful_methods=[
                item for item in getattr(run, "successful_methods", ())
                if item in _METHODS
            ],
            failed_methods=[
                item for item in getattr(run, "failed_methods", ())
                if item in _METHODS
            ],
            user_feedback=[self._safe(item) for item in feedback or ()],
            tags=[],
            origin_session_id=session_id,
            origin_run_id=run.run_id,
        )

    def _safe(self, value):
        return self.redactor.redact_text(str(value))[0]


class MemoryService:
    def __init__(self, memory_store, session_store, compressor):
        self.memory_store = memory_store
        self.session_store = session_store
        self.compressor = compressor

    def keep_and_delete(self, session_id, run, feedback=None):
        capsule = self.compressor.compress(session_id, run, feedback)
        saved = self.memory_store.save_capsule(capsule)
        verified = self.memory_store.get_capsule(saved.capsule_id)
        if verified is None or verified.to_dict() != saved.to_dict():
            self.memory_store.delete_capsule(saved.capsule_id)
            raise RuntimeError("capsule verification failed")
        deletion = self.session_store.delete(session_id)
        return MemoryArchiveResult(
            saved.capsule_id,
            True,
            deletion.deleted,
            deletion.errors,
        )


class SkillLearner:
    def __init__(self, store, support_threshold=3):
        self.store = store
        self.support_threshold = max(1, int(support_threshold))

    def propose(self, capsules):
        support = {}
        for capsule in capsules:
            for method in set(capsule.successful_methods):
                if method in _METHODS:
                    support.setdefault(method, []).append(capsule.capsule_id)
        proposals = []
        for method, capsule_ids in sorted(support.items()):
            if len(capsule_ids) < self.support_threshold:
                continue
            skill_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"celina-skill:{method}",
            ))
            if self.store.get_skill(skill_id) is not None:
                continue
            now = _utc_now()
            proposals.append(self.store.save_skill(Skill(
                skill_id,
                method.replace("_", " ").title(),
                1,
                "proposed",
                {"method": method},
                (_METHODS[method],),
                tuple(capsule_ids),
                now,
                now,
            )))
        return proposals
