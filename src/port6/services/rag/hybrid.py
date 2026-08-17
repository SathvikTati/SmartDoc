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

from port6.services.rag.base import RagResult, RetrievedChunk
from port6.services.rag.generation import generate_answer
from port6.services.rag.hierarchical import hierarchical_search
from port6.services.rag.retrievers import (
    fuse,
    keyword_search,
    semantic_search,
)


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
) -> RagResult:

    started = time.perf_counter()

    # Retrieve wider than top_k so fusion has candidates to choose between.
    candidate_k = max(top_k * 2, 8)

    # --- Hierarchical: document -> section -> chunk -------------------
    hierarchy = await hierarchical_search(
        question,
        top_k=candidate_k,
    )

    hierarchical_chunks = hierarchy["chunks"]

    # --- Flat hybrid over the whole index -----------------------------
    semantic_chunks = await semantic_search(
        question,
        top_k=candidate_k,
    )

    keyword_chunks = keyword_search(
        question,
        top_k=candidate_k,
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
