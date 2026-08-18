"""Documents that disagree, and which one to believe.

A library accumulates versions. Someone uploads a revised HR policy
without deleting the old one, and now two documents answer "how much
annual leave?" with different numbers. Retrieval will happily return
both, and the model — told to answer only from the sources — picks one,
usually the better-ranked rather than the newer. The answer is confident
and possibly a year out of date, with a citation to prove it.

The rule here is upload recency: the most recently uploaded document
wins, and the answer says what the older one said. That is a *heuristic*,
not a fact about the documents. Nothing in a file states that it
supersedes another, so this cannot be certain — which is why the older
figure is reported rather than silently dropped. A reader who knows the
old document is the authoritative one can see that it was set aside.

Detection is deliberately narrow. Two chunks conflict when they are from
different documents and each states a different number for *the same
measured thing*, where "the same thing" means the words right after the
number match: "22 days ... paid annual leave" against "25 days ... paid
annual leave" is a conflict; "12 days ... paid sick leave" is not. That
keeps a policy quoting several unrelated figures from lighting up as a
contradiction, at the cost of missing conflicts phrased differently. A
missed conflict leaves today's behaviour; a false one rewrites a correct
answer, so the trade runs that way on purpose.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime


logger = logging.getLogger(__name__)


# Words carried along with a figure that say nothing about what is being
# measured. "22 days of paid annual leave" and "25 days paid annual
# leave" describe the same thing and must produce the same key.
_FILLER = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "each",
    "every",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "up",
    "with",
}

# How many meaningful words after the number make up the key. Enough to
# separate annual leave from sick leave, short enough that a clause
# ending early still matches.
KEY_WORDS = 4

_CLAIM = re.compile(r"(\d+(?:\.\d+)?)\s+([^.;:\n]{0,80})")


@dataclass
class Claim:
    """One figure, and what it is a figure *of*."""

    value: str
    key: tuple[str, ...]
    document_id: str
    filename: str
    uploaded_at: datetime | None
    chunk_id: str


@dataclass
class Conflict:
    """The same measurement, answered differently by two documents."""

    key: tuple[str, ...]

    # Newest first, so claims[0] is the one the answer should use.
    claims: list[Claim] = field(default_factory=list)

    @property
    def current(self) -> Claim:
        return self.claims[0]

    @property
    def superseded(self) -> list[Claim]:
        return self.claims[1:]

    def describe(self) -> str:
        """One line for the model, and for the UI."""

        subject = " ".join(self.key)

        older = "; ".join(
            f"{claim.filename} says {claim.value}"
            + (
                f" (uploaded {claim.uploaded_at:%Y-%m-%d})"
                if claim.uploaded_at
                else ""
            )
            for claim in self.superseded
        )

        current = (
            f"{self.current.filename} says {self.current.value}"
            + (
                f" (uploaded {self.current.uploaded_at:%Y-%m-%d})"
                if self.current.uploaded_at
                else ""
            )
        )

        return f"{subject}: {current} — most recent. Previously {older}."


def _normalise(words: str) -> tuple[str, ...]:
    """"of paid annual leave per year" -> ("paid", "annual", "leave")."""

    key: list[str] = []

    for word in re.findall(r"[a-z]+", words.lower()):

        if word in _FILLER:
            continue

        # Crude singularisation, so "days"/"day" and "weeks"/"week" agree.
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]

        key.append(word)

        if len(key) == KEY_WORDS:
            break

    return tuple(key)


def claims_in(chunk) -> list[Claim]:
    """Every "<number> <what it measures>" in one chunk."""

    found: list[Claim] = []

    for match in _CLAIM.finditer(chunk.content or ""):

        key = _normalise(match.group(2))

        # A bare number with nothing after it says nothing comparable.
        if len(key) < 2:
            continue

        found.append(
            Claim(
                value=match.group(1),
                key=key,
                document_id=chunk.document_id,
                filename=chunk.filename,
                uploaded_at=getattr(chunk, "uploaded_at", None),
                chunk_id=chunk.chunk_id,
            )
        )

    return found


def find_conflicts(chunks: list) -> list[Conflict]:
    """Where two documents give different figures for the same thing."""

    by_key: dict[tuple[str, ...], list[Claim]] = {}

    for chunk in chunks:

        # A calculation or a web result is not a version of a document.
        if getattr(chunk, "url", None) or chunk.document_id in {
            "calculation",
            "library",
        }:
            continue

        for claim in claims_in(chunk):
            by_key.setdefault(claim.key, []).append(claim)

    conflicts: list[Conflict] = []

    for key, claims in by_key.items():

        documents = {claim.document_id for claim in claims}
        values = {claim.value for claim in claims}

        # Both are required: one document listing 22 and 25 for the same
        # thing is a table, not a contradiction, and two documents that
        # agree are not worth mentioning.
        if len(documents) < 2 or len(values) < 2:
            continue

        # One claim per document — the best available for that document —
        # so a figure repeated across chunks is not reported twice.
        per_document: dict[str, Claim] = {}

        for claim in claims:
            per_document.setdefault(claim.document_id, claim)

        if len({claim.value for claim in per_document.values()}) < 2:
            continue

        ordered = sorted(
            per_document.values(),
            # Newest first. A document with no upload time sorts last
            # rather than winning by accident.
            key=lambda claim: (
                claim.uploaded_at is not None,
                claim.uploaded_at or datetime.min,
            ),
            reverse=True,
        )

        conflicts.append(Conflict(key=key, claims=ordered))

    if conflicts:
        logger.info(
            "Sources disagree on %d measurement(s): %s",
            len(conflicts),
            "; ".join(" ".join(conflict.key) for conflict in conflicts),
        )

    return conflicts


def stamp_upload_times(chunks: list) -> list:
    """Attach each chunk's document upload time, for ordering.

    Read from Postgres rather than the chunk metadata so it stays right
    for documents indexed before this existed, and one query covers the
    whole result set.
    """

    from port6.services.db.database import SessionLocal
    from port6.services.model.models import Document

    ids = {
        chunk.document_id
        for chunk in chunks
        if chunk.document_id
        and not getattr(chunk, "url", None)
        and chunk.document_id not in {"calculation", "library", "web"}
    }

    if not ids:
        return chunks

    db = SessionLocal()

    try:
        rows = (
            db.query(Document.id, Document.created_at)
            .filter(Document.id.in_(ids))
            .all()
        )

        uploaded = {str(row[0]): row[1] for row in rows}

    except Exception as exc:
        # Recency is an enhancement; losing it must not lose the answer.
        logger.warning("Could not read document upload times: %s", exc)
        return chunks

    finally:
        db.close()

    for chunk in chunks:
        chunk.uploaded_at = uploaded.get(chunk.document_id)

    return chunks


def context_note(conflicts: list[Conflict]) -> str:
    """The warning that goes above the sources."""

    if not conflicts:
        return ""

    lines = [
        "NOTE — the sources disagree with each other.",
        "",
        "For each item below, answer with the figure from the most recent",
        "document, then add one short sentence saying what the older",
        "document said. Do not average them and do not present both as",
        "equally current.",
        "",
    ]

    lines.extend(f"- {conflict.describe()}" for conflict in conflicts)

    return "\n".join(lines)
