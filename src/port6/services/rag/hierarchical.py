"""Hierarchical retrieval: document -> section -> chunk.

Each stage narrows the space the next one searches:

1. Documents are scored from the database (titles, types, summaries). The
   chunk index is not touched.
2. Sections are found by searching only inside the documents that survived
   stage 1, then scoring each section by its best chunk.
3. Chunks are retrieved only from the sections that survived stage 2.

The point is that stage 3 never sees a chunk from an unrelated document, so
a question about maternity leave cannot pull in a chunk from an expense
policy just because the wording is close.
"""

from __future__ import annotations

import logging

from rank_bm25 import BM25Okapi

from port6.services.db.database import SessionLocal
from port6.services.embeddings.service import get_embeddings
from port6.services.model.models import Document
from port6.services.rag.base import RetrievedChunk, chunk_from_metadata
from port6.services.rag.retrievers import tokenize
from port6.services.vector.chroma import get_vector_store


logger = logging.getLogger(__name__)


DEFAULT_MAX_DOCUMENTS = 3
DEFAULT_MAX_SECTIONS = 4

# Content used in place of a missing summary when ranking documents.
PROFILE_FALLBACK_CHARACTERS = 2000


def select_documents(
    query: str,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    document_ids: list[str] | None = None,
) -> list[dict]:
    """Stage 1. Pick candidate documents without touching the chunk index.

    `document_ids` restricts the candidate pool to an explicit scope. The
    ranking still runs inside it, so asking about four documents still
    narrows to the ones that look relevant — it just cannot wander outside.
    """

    db = SessionLocal()

    try:
        candidates = (
            db.query(Document)
            .filter(Document.status == "READY")
        )

        if document_ids:
            candidates = candidates.filter(Document.id.in_(document_ids))

        documents = candidates.all()

        if not documents:
            return []

        # The summary carries the signal: a filename is a couple of tokens,
        # so ranking on it alone is close to arbitrary.
        #
        # When a document has no summary — summarisation is best-effort and
        # can fail — the opening of its content stands in. Cruder than a
        # summary, but it keeps the document reachable at stage 1 instead
        # of dropping it out of document-level ranking entirely.
        corpus = []

        for document in documents:
            profile = " ".join(
                part
                for part in [
                    document.filename or "",
                    document.summary
                    or (document.content or "")[:PROFILE_FALLBACK_CHARACTERS],
                ]
                if part
            )
            corpus.append(tokenize(profile))

        scores = [0.0] * len(documents)

        if any(corpus):
            bm25 = BM25Okapi(corpus)
            scores = list(bm25.get_scores(tokenize(query)))

        ranked = sorted(
            range(len(documents)),
            key=lambda index: scores[index],
            reverse=True,
        )

        # An explicit scope is the user's choice, so never drop part of it
        # just because the default budget is smaller.
        if document_ids:
            max_documents = max(max_documents, len(documents))

        selected = []

        for index in ranked[:max_documents]:

            document = documents[index]

            selected.append(
                {
                    "document_id": str(document.id),
                    "filename": document.filename,
                    "score": round(float(scores[index]), 4),
                }
            )

        logger.info(
            "Stage 1 selected %d/%d documents",
            len(selected),
            len(documents),
        )

        return selected

    finally:
        db.close()


def _where_for_documents(
    document_ids: list[str],
) -> dict:

    if len(document_ids) == 1:
        return {"document_id": document_ids[0]}

    return {"document_id": {"$in": document_ids}}


async def select_sections(
    query: str,
    document_ids: list[str],
    max_sections: int = DEFAULT_MAX_SECTIONS,
    candidates_per_document: int = 8,
) -> list[dict]:
    """Stage 2. Score sections using only chunks from the chosen documents."""

    if not document_ids:
        return []

    collection = get_vector_store()._collection

    if collection.count() == 0:
        return []

    embedding = await get_embeddings().aembed_query(query)

    results = collection.query(
        query_embeddings=[embedding],
        n_results=max(
            candidates_per_document * len(document_ids),
            max_sections,
        ),
        where=_where_for_documents(document_ids),
        include=["metadatas", "distances"],
    )

    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    # A section is worth as much as its single best chunk.
    best: dict[tuple[str, str], dict] = {}

    for index, metadata in enumerate(metadatas):

        metadata = metadata or {}

        document_id = str(metadata.get("document_id", "unknown"))

        # Documents ingested before structure extraction have no sections;
        # treat the whole document as one section so they stay reachable.
        section_id = str(metadata.get("section_id") or "whole-document")

        distance = (
            float(distances[index])
            if index < len(distances)
            else None
        )

        key = (document_id, section_id)

        if key in best and distance is not None:
            if best[key]["score"] is not None and distance >= best[key]["score"]:
                continue

        best[key] = {
            "document_id": document_id,
            "section_id": section_id,
            "section_title": metadata.get("section_title"),
            "section_path": metadata.get("section_path"),
            "parent_section_id": metadata.get("parent_section_id"),
            "filename": metadata.get("filename"),
            "page_number": metadata.get("page_number"),
            "score": distance,
        }

    ordered = sorted(
        best.values(),
        key=lambda section: (
            section["score"] if section["score"] is not None else 1e9
        ),
    )

    selected = ordered[:max_sections]

    logger.info(
        "Stage 2 selected %d/%d sections from %d documents",
        len(selected),
        len(ordered),
        len(document_ids),
    )

    return selected


async def retrieve_in_sections(
    query: str,
    sections: list[dict],
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Stage 3. Retrieve chunks only from the selected sections."""

    if not sections:
        return []

    collection = get_vector_store()._collection

    embedding = await get_embeddings().aembed_query(query)

    document_ids = sorted(
        {section["document_id"] for section in sections}
    )

    section_ids = sorted(
        {
            section["section_id"]
            for section in sections
            if section["section_id"] != "whole-document"
        }
    )

    clauses: list[dict] = [_where_for_documents(document_ids)]

    if section_ids:
        clauses.append(
            {"section_id": {"$in": section_ids}}
            if len(section_ids) > 1
            else {"section_id": section_ids[0]}
        )

    where = clauses[0] if len(clauses) == 1 else {"$and": clauses}

    results = collection.query(
        query_embeddings=[embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    chunks = []

    for index, content in enumerate(documents):

        chunk = chunk_from_metadata(
            number=index + 1,
            content=content,
            metadata=(metadatas[index] if index < len(metadatas) else {}) or {},
            score=(
                float(distances[index])
                if index < len(distances)
                else None
            ),
        )

        chunk.sources = ["hierarchical"]
        chunk.semantic_rank = index + 1

        chunks.append(chunk)

    logger.info(
        "Stage 3 retrieved %d chunks from %d sections",
        len(chunks),
        len(sections),
    )

    return chunks


async def hierarchical_search(
    query: str,
    top_k: int = 5,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_sections: int = DEFAULT_MAX_SECTIONS,
    document_ids: list[str] | None = None,
) -> dict:
    """Run all three stages and report what each one narrowed to."""

    documents = select_documents(
        query,
        max_documents=max_documents,
        document_ids=document_ids,
    )

    if not documents:
        return {
            "chunks": [],
            "documents": [],
            "sections": [],
        }

    document_ids = [
        document["document_id"]
        for document in documents
    ]

    sections = await select_sections(
        query,
        document_ids=document_ids,
        max_sections=max_sections,
    )

    chunks = await retrieve_in_sections(
        query,
        sections=sections,
        top_k=top_k,
    )

    return {
        "chunks": chunks,
        "documents": documents,
        "sections": sections,
    }
