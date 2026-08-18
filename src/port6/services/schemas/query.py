from uuid import UUID

from pydantic import BaseModel, Field

from port6.services.rag.base import RagMode, RagResult


SCOPE_DESCRIPTION = (
    "Restrict retrieval to these documents. A hard scope in every mode: "
    "nothing outside the list can be retrieved or cited. Omit to search "
    "the whole library."
)


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
            "hybrid (semantic + BM25 over hierarchical narrowing), "
            "or agentic (LangGraph tool-planning agent)."
        ),
    )

    document_ids: list[UUID] | None = Field(
        default=None,
        description=SCOPE_DESCRIPTION,
    )

    chat_id: UUID | None = Field(
        default=None,
        description=(
            "Continue an existing conversation. The question is resolved "
            "against its previous turns, so a follow-up like \"what about "
            "sick leave?\" is understood. Omit to start a new chat; the "
            "id is returned in the response metadata either way."
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

    document_ids: list[UUID] | None = Field(
        default=None,
        description=SCOPE_DESCRIPTION,
    )


class CompareResponse(BaseModel):
    question: str
    results: dict[str, RagResult]
