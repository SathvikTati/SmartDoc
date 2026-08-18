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

    top_k: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description=(
            "Chunks to retrieve. Omit to use the configured default "
            "(`defaults.top_k`), which is what a new chat applies."
        ),
    )

    retrievers: list[str] | None = Field(
        default=None,
        description=(
            "Which retrievers to run: semantic, keyword, hierarchical, "
            "in any combination. Omit to fall back to `mode`, and omit "
            "both to use the configured default (`defaults.mode`)."
        ),
    )

    agent: bool = Field(
        default=False,
        description=(
            "Put the LangGraph agent on top of those retrievers. It may "
            "only plan over the retrievers chosen above, plus any "
            "`tools` selected — turning it on never widens what is "
            "searched."
        ),
    )

    tools: list[str] | None = Field(
        default=None,
        description=(
            "Extra tools the agent may use beyond its retrievers: "
            "document_lookup, calculate, web_search. Ignored when "
            "`agent` is false."
        ),
    )

    mode: RagMode | None = Field(
        default=None,
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


class Configuration(BaseModel):
    """One composition to run: retrievers, and optionally an agent."""

    retrievers: list[str] = Field(min_length=1)
    agent: bool = False
    planner: bool = True
    tools: list[str] | None = None


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
        description=(
            "The coarse three-way comparison. Ignored when `pipelines` "
            "is given."
        ),
    )

    configurations: list[Configuration] | None = Field(
        default=None,
        min_length=2,
        max_length=6,
        description=(
            "Compositions to run side by side. Two or more — a "
            "comparison of one is just a question."
        ),
    )

    document_ids: list[UUID] | None = Field(
        default=None,
        description=SCOPE_DESCRIPTION,
    )


class CompareResponse(BaseModel):
    question: str
    results: dict[str, RagResult]
