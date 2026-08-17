from enum import Enum

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    """Which retrievers to run.

    Search is the raw-retrieval view, so the modes are the retrievers
    themselves rather than the three answering pipelines — the point is to
    see what each one finds before any model is involved.
    """

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=1000,
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    mode: SearchMode = Field(
        default=SearchMode.HYBRID,
    )


class SearchResult(BaseModel):
    document_id: str
    filename: str
    chunk_id: str
    chunk_index: int
    content: str

    rank: int

    section_id: str | None = None
    section_title: str | None = None
    section_path: str | None = None
    page_number: int | None = None

    # Raw retriever score: a Chroma distance for semantic-only results, a
    # BM25 score for keyword-only ones. Not comparable across modes, which
    # is exactly why hybrid fuses ranks instead.
    score: float | None = None
    fused_score: float | None = None

    sources: list[str] = []
    semantic_rank: int | None = None
    keyword_rank: int | None = None


class SearchResponse(BaseModel):
    query: str
    mode: SearchMode = SearchMode.HYBRID
    results: list[SearchResult]
