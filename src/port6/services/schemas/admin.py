"""Schemas for settings, prompts and query history."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from port6.services.schemas.common import UtcDatetime


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

class SettingResponse(BaseModel):
    key: str
    value: Any = None
    default_value: Any = None
    description: str | None = None
    is_default: bool


class SettingUpdate(BaseModel):
    # Deliberately Any: a setting can be a number, a string, a boolean or
    # null, and the accessor coerces at the point of use.
    value: Any = None


# -------------------------------------------------------------------
# Prompts
# -------------------------------------------------------------------

class PromptResponse(BaseModel):
    name: str
    system: str
    human: str
    version: int
    variables: list[str] = []
    description: str | None = None
    default_system: str
    default_human: str
    is_default: bool


class PromptUpdate(BaseModel):
    """Either half can be omitted to leave it unchanged."""

    system: str | None = Field(default=None, min_length=1)
    human: str | None = Field(default=None, min_length=1)


# -------------------------------------------------------------------
# Query history
# -------------------------------------------------------------------

class QueryRunSummary(BaseModel):
    """Enough to render a history list without shipping every chunk."""

    id: UUID
    question: str
    mode: str
    top_k: int
    answered: bool
    citation_count: int
    chunk_count: int
    latency_ms: float | None = None
    retrieval_method: str | None = None
    created_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class QueryRunDetail(QueryRunSummary):
    answer: str
    # The full RagResult as it was returned at the time.
    result: dict
    prompt_versions: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class QueryRunPage(BaseModel):
    total: int
    runs: list[QueryRunSummary]
