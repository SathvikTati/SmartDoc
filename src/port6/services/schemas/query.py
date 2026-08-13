from pydantic import BaseModel, Field


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


class QueryInput(BaseModel):
    query: str
    top_k: int = 5


class Citation(BaseModel):
    """A source the model actually referenced, by its [n] marker."""

    number: int
    document_id: str
    filename: str
    chunk_index: int
    content: str
    score: float | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    answered: bool
    citations: list[Citation]
    sources: list[Citation]
