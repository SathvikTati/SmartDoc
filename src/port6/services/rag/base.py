"""The contract every retrieval mode shares.

All three modes take a question and return a `RagResult`, so they can be
compared side by side on the same input.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class RagMode(str, Enum):
    NAIVE = "naive"
    HYBRID = "hybrid"
    AGENTIC = "agentic"


class RetrievedChunk(BaseModel):
    """One chunk offered to the model, with everything needed to cite it."""

    number: int
    chunk_id: str
    document_id: str
    filename: str
    content: str

    section_id: str | None = None
    section_title: str | None = None
    section_path: str | None = None
    parent_section_id: str | None = None
    page_number: int | None = None

    score: float | None = None

    # Which retrievers found this chunk: "semantic", "keyword", or both.
    sources: list[str] = Field(default_factory=list)
    semantic_rank: int | None = None
    keyword_rank: int | None = None
    fused_score: float | None = None

    def citation_label(self) -> str:
        """e.g. "hr_policy.md, Section 1.2 Maternity Leave, Page 12"."""

        parts = [self.filename]

        if self.section_title:
            parts.append(f"Section {self.section_title}")

        if self.page_number is not None:
            parts.append(f"Page {self.page_number}")

        return ", ".join(parts)


class RagResult(BaseModel):
    question: str
    answer: str
    answered: bool

    citations: list[RetrievedChunk] = Field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)

    retrieval_method: str = ""
    latency_ms: float | None = None

    metadata: dict = Field(default_factory=dict)

    # Mode-specific transparency: documents and sections considered, which
    # retriever produced what, tools the agent chose, validation outcome.
    debug: dict = Field(default_factory=dict)


def chunk_from_metadata(
    number: int,
    content: str,
    metadata: dict,
    score: float | None = None,
) -> RetrievedChunk:
    """Build a RetrievedChunk from a stored chunk's metadata.

    Metadata is tolerant by design: documents ingested before a field
    existed simply leave it None rather than failing retrieval.
    """

    def as_int(value) -> int | None:
        try:
            return int(value)

        except (TypeError, ValueError):
            return None

    document_id = str(metadata.get("document_id", "unknown"))

    return RetrievedChunk(
        number=number,
        chunk_id=str(
            metadata.get(
                "chunk_id",
                f"{document_id}:{metadata.get('chunk_index', number - 1)}",
            )
        ),
        document_id=document_id,
        filename=str(metadata.get("filename", "unknown")),
        content=content,
        section_id=metadata.get("section_id"),
        section_title=metadata.get("section_title"),
        section_path=metadata.get("section_path"),
        parent_section_id=metadata.get("parent_section_id"),
        page_number=as_int(metadata.get("page_number")),
        score=score,
    )
