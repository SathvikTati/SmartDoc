from pydantic import BaseModel, Field

from port6.services.rag.base import RagMode, RagResult


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    mode: RagMode = Field(
        default=RagMode.NAIVE,
        description=(
            "Retrieval strategy: naive (vector only), "
            "hybrid (semantic + BM25 + hierarchical + version aware), "
            "or agentic (LangGraph tool-planning agent)."
        ),
    )


class CompareRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    modes: list[RagMode] = Field(
        default_factory=lambda: list(RagMode),
    )


class CompareResponse(BaseModel):
    question: str
    results: dict[str, RagResult]
