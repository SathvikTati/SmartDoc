"""Mode 2: Hybrid + Hierarchical RAG.

Adds two things to the naive baseline:

- keyword (BM25) retrieval alongside vector search, fused with RRF, so exact
  terms — policy names, codes, "26 weeks" — are not lost to embedding
  similarity
- hierarchical narrowing, document -> section -> chunk

The hierarchical candidates and the hybrid candidates are fused rather than
one replacing the other: hierarchy is precise but can narrow onto the wrong
document, and the flat hybrid pass is the safety net.
"""

from __future__ import annotations

import logging
import time

from port6.services.rag.aggregation import (
    build_grouped_context,
    coverage_search,
    is_aggregation_question,
    matched_pattern,
)
from port6.services.rag.base import RagResult, RetrievedChunk
from port6.services.rag.generation import generate_answer
from port6.services.rag.hierarchical import hierarchical_search
from port6.services.rag.retrievers import (
    fuse,
    keyword_search,
    semantic_search,
)
from port6.services.settings.service import get_setting


logger = logging.getLogger(__name__)


RETRIEVAL_METHOD = (
    "hybrid (semantic + BM25, RRF fused) over hierarchical "
    "document -> section -> chunk narrowing"
)


def _rerank(
    chunks: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """Order by fused score, preferring chunks two retrievers agreed on.

    Chunks found by both semantic and keyword search are stronger evidence
    than either alone, so agreement breaks ties ahead of raw distance.
    """

    def sort_key(chunk: RetrievedChunk):
        return (
            -(chunk.fused_score or 0.0),
            -len(chunk.sources),
            chunk.score if chunk.score is not None else 1e9,
        )

    ordered = sorted(chunks, key=sort_key)

    for position, chunk in enumerate(ordered[:top_k], start=1):
        chunk.number = position

    return ordered[:top_k]


async def run(
    question: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> RagResult:

    started = time.perf_counter()

    # A question about the library as a whole needs breadth, not depth.
    # Ordinary top-k can return five chunks from one document, which makes
    # "which documents mention X" unanswerable however it is prompted.
    if get_setting("aggregation.enabled") and is_aggregation_question(question):
        return await _run_aggregated(question, started, document_ids)

    # Retrieve wider than top_k so fusion has candidates to choose between.
    candidate_k = max(top_k * 2, 8)

    # --- Hierarchical: document -> section -> chunk -------------------
    hierarchy = await hierarchical_search(
        question,
        top_k=candidate_k,
        document_ids=document_ids,
    )

    hierarchical_chunks = hierarchy["chunks"]

    # --- Flat hybrid over the whole index -----------------------------
    semantic_chunks = await semantic_search(
        question,
        top_k=candidate_k,
        document_ids=document_ids,
    )

    keyword_chunks = keyword_search(
        question,
        top_k=candidate_k,
        document_ids=document_ids,
    )

    fused = fuse(
        semantic_chunks + hierarchical_chunks,
        keyword_chunks,
        top_k=candidate_k,
    )

    chunks = _rerank(fused, top_k)

    result = await generate_answer(question, chunks)

    both = [
        chunk
        for chunk in chunks
        if len(chunk.sources) > 1
    ]

    return RagResult(
        question=question,
        answer=result["answer"],
        answered=result["answered"],
        citations=result["citations"],
        retrieved_chunks=chunks,
        retrieval_method=RETRIEVAL_METHOD,
        latency_ms=round(
            (time.perf_counter() - started) * 1000,
            2,
        ),
        metadata={
            "mode": "hybrid",
            "top_k": top_k,
            "documents_considered": len(hierarchy["documents"]),
            "sections_considered": len(hierarchy["sections"]),
            "chunks_retrieved": len(chunks),
            "scoped_to_documents": len(document_ids) if document_ids else 0,
        },
        debug={
            "stages": [
                {
                    "name": "document_selection",
                    "detail": "stage 1: rank documents, ignore chunk index",
                    "results": len(hierarchy["documents"]),
                },
                {
                    "name": "section_selection",
                    "detail": (
                        "stage 2: search only inside selected documents"
                    ),
                    "results": len(hierarchy["sections"]),
                },
                {
                    "name": "chunk_retrieval",
                    "detail": "stage 3: retrieve only inside selected sections",
                    "results": len(hierarchical_chunks),
                },
                {
                    "name": "hybrid_fusion",
                    "detail": (
                        f"RRF over {len(semantic_chunks)} semantic + "
                        f"{len(hierarchical_chunks)} hierarchical + "
                        f"{len(keyword_chunks)} keyword candidates"
                    ),
                    "results": len(chunks),
                },
            ],
            "retrieved_documents": hierarchy["documents"],
            "retrieved_sections": hierarchy["sections"],
            "semantic_matches": _summarise(semantic_chunks),
            "keyword_matches": _summarise(keyword_chunks),
            "matched_by_both": _summarise(both),
        },
    )


async def _run_aggregated(
    question: str,
    started: float,
    document_ids: list[str] | None,
) -> RagResult:
    """Answer by covering documents rather than ranking chunks."""

    coverage = await coverage_search(question, document_ids=document_ids)

    chunks = coverage["chunks"]

    result = await generate_answer(
        question,
        chunks,
        prompt_name="aggregate_answer",
        context_builder=build_grouped_context,
    )

    documents = coverage["documents"]

    return RagResult(
        question=question,
        answer=result["answer"],
        answered=result["answered"],
        citations=result["citations"],
        retrieved_chunks=chunks,
        retrieval_method=(
            "cross-document aggregation: best chunks from each matching "
            "document, grouped by document"
        ),
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        metadata={
            "mode": "hybrid",
            "aggregated": True,
            "documents_covered": len(documents),
            "chunks_retrieved": len(chunks),
            "scoped_to_documents": len(document_ids) if document_ids else 0,
        },
        debug={
            "stages": [
                {
                    "name": "aggregation_detected",
                    "detail": (
                        "question asks about the library as a whole "
                        f"(matched {matched_pattern(question)!r})"
                    ),
                },
                {
                    "name": "coverage_retrieval",
                    "detail": (
                        f"topic {coverage['topic_terms']}; "
                        f"{coverage['semantic_candidates']} semantic + "
                        f"{coverage['keyword_candidates']} keyword candidates, "
                        f"grouped into {len(documents)} document(s); "
                        f"{coverage['documents_excluded']} document(s) had no "
                        "keyword match and were excluded"
                    ),
                    "results": len(chunks),
                },
                {
                    "name": "answer_generation",
                    "detail": f"{len(result['citations'])} citations",
                },
            ],
            "documents_covered": documents,
            "note": (
                "Retrieved for breadth rather than depth: each document "
                "contributes its best chunks, so no single document can "
                "crowd the others out of the answer."
            ),
        },
    )


def _summarise(
    chunks: list[RetrievedChunk],
) -> list[dict]:

    return [
        {
            "chunk_id": chunk.chunk_id,
            "filename": chunk.filename,
            "section": chunk.section_path,
            "page": chunk.page_number,
            "score": chunk.score,
            "fused_score": chunk.fused_score,
            "sources": chunk.sources,
            "semantic_rank": chunk.semantic_rank,
            "keyword_rank": chunk.keyword_rank,
        }
        for chunk in chunks
    ]
