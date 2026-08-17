"""Mode 1: Naive RAG.

Query -> vector search -> top-k chunks -> LLM -> answer + citations.

Deliberately unchanged from the original pipeline. No keyword search and no
hierarchy: this is the baseline the other two modes are measured against,
and its failures are the point of the comparison.
"""

from __future__ import annotations

import logging
import time

from port6.services.rag.base import RagResult
from port6.services.rag.generation import generate_answer
from port6.services.rag.retrievers import semantic_search


logger = logging.getLogger(__name__)


RETRIEVAL_METHOD = "semantic vector search (top-k)"


async def run(
    question: str,
    top_k: int = 5,
) -> RagResult:

    started = time.perf_counter()

    chunks = await semantic_search(
        question,
        top_k=top_k,
    )

    result = await generate_answer(question, chunks)

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
            "mode": "naive",
            "top_k": top_k,
            "chunks_retrieved": len(chunks),
        },
        debug={
            "stages": [
                {
                    "name": "semantic_search",
                    "detail": (
                        f"top {top_k} chunks by embedding distance, "
                        "no filtering"
                    ),
                    "results": len(chunks),
                }
            ],
            "semantic_matches": [
                {
                    "number": chunk.number,
                    "filename": chunk.filename,
                    "section": chunk.section_path,
                    "score": chunk.score,
                }
                for chunk in chunks
            ],
            "keyword_matches": [],
            "note": (
                "Naive mode ranks by embedding distance alone: no keyword "
                "matching and no hierarchical narrowing."
            ),
        },
    )
