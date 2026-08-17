"""Raw retrieval, with no answer generation.

This is the inspection path: it returns the chunks a retriever would hand to
the model, along with which retriever found them and at what rank, so the
retrieval step can be judged on its own rather than through an answer.
"""

from port6.services.rag.base import RetrievedChunk
from port6.services.rag.retrievers import (
    fuse,
    keyword_search,
    semantic_search,
)
from port6.services.schemas.search import SearchMode, SearchResult


def _chunk_index(
    chunk: RetrievedChunk,
) -> int:
    """Recover the chunk's position from its id (`<document_id>:<index>`)."""

    try:
        return int(chunk.chunk_id.rsplit(":", 1)[-1])

    except (ValueError, IndexError):
        return 0


def _to_result(
    rank: int,
    chunk: RetrievedChunk,
) -> SearchResult:

    return SearchResult(
        document_id=chunk.document_id,
        filename=chunk.filename,
        chunk_id=chunk.chunk_id,
        chunk_index=_chunk_index(chunk),
        content=chunk.content,
        rank=rank,
        section_id=chunk.section_id,
        section_title=chunk.section_title,
        section_path=chunk.section_path,
        page_number=chunk.page_number,
        score=chunk.score,
        fused_score=chunk.fused_score,
        sources=chunk.sources,
        semantic_rank=chunk.semantic_rank,
        keyword_rank=chunk.keyword_rank,
    )


async def search(
    query: str,
    top_k: int = 5,
    mode: SearchMode = SearchMode.HYBRID,
) -> list[SearchResult]:

    if mode == SearchMode.SEMANTIC:
        chunks = await semantic_search(query, top_k=top_k)

    elif mode == SearchMode.KEYWORD:
        chunks = keyword_search(query, top_k=top_k)

    else:
        # Retrieve wider than top_k so fusion has candidates to rank
        # against each other rather than merging two already-truncated lists.
        candidate_k = max(top_k * 2, 8)

        chunks = fuse(
            await semantic_search(query, top_k=candidate_k),
            keyword_search(query, top_k=candidate_k),
            top_k=top_k,
        )

    return [
        _to_result(rank, chunk)
        for rank, chunk in enumerate(chunks, start=1)
    ]
