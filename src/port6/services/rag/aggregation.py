"""Cross-document aggregation.

Some questions are not answered by the best few chunks anywhere in the
library — they are answered by *breadth*:

    "Which documents mention probation?"
    "Compare the leave policies across all documents."
    "What does each policy say about notice periods?"

Ordinary top-k retrieval fails these structurally, not stylistically. With
`top_k=5` all five chunks can come from one document, so the model is never
shown the other documents and cannot enumerate them however it is prompted.

So this does two things differently:

- retrieves for *coverage* — the best chunks from each document that matches
  at all, rather than the best chunks overall
- renders the context grouped by document, so the boundaries the answer has
  to enumerate are visible in the prompt

Detection is rule-based and deterministic. A model classifier would add a
call and a failure mode to every question in order to decide something a
handful of patterns already decide reliably.
"""

from __future__ import annotations

import logging
import re

from port6.services.rag.base import RetrievedChunk
from port6.services.rag.retrievers import (
    keyword_search,
    semantic_search,
)
from port6.services.settings.service import get_int, get_setting


logger = logging.getLogger(__name__)


# Signals that a question is about the library rather than a fact inside
# it. Deliberately conservative: these all name documents explicitly or
# ask for an exhaustive list, so "how many days of annual leave" — a single
# fact that happens to start with "how many" — does not match.
_PATTERNS = [
    r"\bwh(ich|at)\s+(documents?|files?|policies|policy documents?)\b",
    r"\bhow\s+many\s+(documents?|files?|policies)\b",
    r"\b(list|name|show)\s+(all|every|each|the)\b.*\b(documents?|files?|policies)\b",
    # "all documents", "all the documents", "all of the documents"
    r"\b(all|every|each)\s+(of\s+)?(the\s+)?(documents?|files?|policies)\b",
    r"\bacross\s+(all\s+)?(the\s+)?(documents?|files?|policies|library)\b",
    r"\bin\s+(all|every|each)\s+(document|file|policy)\b",
    r"\b(do|does)\s+any\s+(documents?|files?|policies)\b",
    r"\bevery\s+(document|file|policy)\b",
    r"\bcompare\b.*\b(documents?|files?|policies)\b",
    r"\b(documents?|files?|policies)\b.*\bmention\b",
    r"\bmention(ed|s)?\s+in\s+(which|what|any)\b",
    r"\bwhat\s+does\s+each\b",
    r"\bsummar(y|ise|ize|ising|izing)\b.*\b(all|every|the)\s+(documents?|files?)\b",
]

_COMPILED = [re.compile(pattern, re.IGNORECASE) for pattern in _PATTERNS]


# The vocabulary of asking-about-the-library, as opposed to the topic being
# asked about. "What does each policy say about probation?" is scaffolding
# plus one real term, and matching on the scaffolding hits every document.
SCAFFOLDING = {
    "document", "documents", "file", "files", "policy", "policies",
    "library", "each", "every", "all", "any", "both", "mention",
    "mentions", "mentioned", "say", "says", "said", "state", "states",
    "contain", "contains", "cover", "covers", "list", "compare",
    "comparison", "across", "between", "which", "what", "who", "how",
    "many", "does", "do", "did", "is", "are", "the", "a", "an", "of",
    "for", "to", "in", "on", "at", "by", "with", "and", "or", "about",
    "there", "their", "our", "us", "we", "have", "has", "had", "tell",
    "me", "give", "show", "name", "summary", "summarise", "summarize",
    "overview",
}


def topic_terms(question: str) -> list[str]:
    """The subject of an aggregation question, minus the scaffolding.

    Keyword retrieval has to run on this rather than the whole question:
    "policy" and "say" appear in every document, so matching the full
    question qualifies the entire library and the relevance floor below
    stops filtering anything.
    """

    from port6.services.rag.retrievers import tokenize

    return [
        token
        for token in tokenize(question or "")
        if token not in SCAFFOLDING and len(token) > 2
    ]


def is_aggregation_question(question: str) -> bool:
    """True when a question needs breadth across documents, not depth."""

    if not question:
        return False

    return any(pattern.search(question) for pattern in _COMPILED)


def matched_pattern(question: str) -> str | None:
    """Which signal fired, for the retrieval trace."""

    for pattern in _COMPILED:
        found = pattern.search(question or "")

        if found:
            return found.group(0)

    return None


def group_by_document(
    chunks: list[RetrievedChunk],
    chunks_per_document: int,
    max_documents: int,
) -> list[RetrievedChunk]:
    """Keep the best few chunks from each document, breadth first.

    Documents are ordered by their single best chunk, and each contributes
    at most `chunks_per_document` — so one verbose document cannot crowd
    the others out of the context the way plain top-k lets it.
    """

    by_document: dict[str, list[RetrievedChunk]] = {}

    for chunk in chunks:
        by_document.setdefault(chunk.document_id, []).append(chunk)

    def best_score(group: list[RetrievedChunk]) -> float:
        # Every chunk here comes from the same retriever pass, so scores
        # are comparable within this call. Distances: lower is better.
        scores = [chunk.score for chunk in group if chunk.score is not None]
        return min(scores) if scores else 1e9

    ordered = sorted(by_document.values(), key=best_score)

    selected: list[RetrievedChunk] = []

    for group in ordered[:max_documents]:
        selected.extend(group[:chunks_per_document])

    return selected


async def coverage_search(
    query: str,
    document_ids: list[str] | None = None,
) -> dict:
    """Retrieve for breadth: the best chunks from each matching document."""

    max_documents = get_int("aggregation.max_documents")
    per_document = get_int("aggregation.chunks_per_document")

    # Over-fetch so the grouping has several documents to choose between.
    # One Chroma query rather than one per document: the grouping happens
    # here, so breadth costs no extra round trips.
    candidate_k = max_documents * per_document * 4

    semantic = await semantic_search(
        query,
        top_k=candidate_k,
        document_ids=document_ids,
    )

    # BM25 alongside, because "which documents mention probation" turns on
    # the literal word far more than on embedding similarity — but only on
    # the topic terms, or the scaffolding matches everything.
    topic = topic_terms(query)
    keyword_query = " ".join(topic) if topic else query

    keyword = keyword_search(
        keyword_query,
        top_k=candidate_k,
        document_ids=document_ids,
    )

    merged: dict[str, RetrievedChunk] = {}

    for chunk in semantic:
        merged[chunk.chunk_id] = chunk

    for chunk in keyword:
        existing = merged.get(chunk.chunk_id)

        if existing is None:
            merged[chunk.chunk_id] = chunk
            continue

        for source in chunk.sources:
            if source not in existing.sources:
                existing.sources.append(source)

    candidates = list(merged.values())

    # Semantic search returns the nearest chunk from *every* document,
    # whether or not it mentions the topic. In an enumeration answer those
    # near-misses are actively harmful: the model is asked which documents
    # mention X and handed several that do not. Where the keyword
    # retriever found anything, it decides which documents qualify —
    # "mentions" is a literal claim, and BM25 answers it literally.
    keyword_documents = {chunk.document_id for chunk in keyword}

    excluded = 0

    if keyword_documents and get_setting("aggregation.require_keyword_match"):
        filtered = [
            chunk
            for chunk in candidates
            if chunk.document_id in keyword_documents
        ]
        excluded = len(
            {chunk.document_id for chunk in candidates} - keyword_documents
        )
        candidates = filtered

    chunks = group_by_document(
        candidates,
        chunks_per_document=per_document,
        max_documents=max_documents,
    )

    for position, chunk in enumerate(chunks, start=1):
        chunk.number = position

    documents = sorted({chunk.filename for chunk in chunks})

    logger.info(
        "Coverage search: %d chunks across %d documents",
        len(chunks),
        len(documents),
    )

    return {
        "chunks": chunks,
        "documents": documents,
        "semantic_candidates": len(semantic),
        "keyword_candidates": len(keyword),
        "documents_excluded": excluded,
        "topic_terms": topic,
    }


def build_grouped_context(
    chunks: list[RetrievedChunk],
) -> str:
    """Render sources grouped under their document.

    The flat numbered list gives no visual boundary between documents, so
    a model asked to enumerate them has to infer the grouping from
    repeated filenames. Making it explicit is most of what turns a vague
    answer into a per-document one.
    """

    grouped: dict[str, list[RetrievedChunk]] = {}

    for chunk in chunks:
        grouped.setdefault(chunk.filename, []).append(chunk)

    blocks = []

    for filename, group in grouped.items():

        lines = [f"=== DOCUMENT: {filename} ==="]

        for chunk in group:

            header = [f"[{chunk.number}]"]

            if chunk.section_path:
                header.append(f"section: {chunk.section_path}")

            if chunk.page_number is not None:
                header.append(f"page {chunk.page_number}")

            lines.append(" | ".join(header))
            lines.append(chunk.content)

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)
