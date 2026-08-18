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

class ChatSummary(BaseModel):
    id: UUID
    title: str
    turn_count: int
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = ConfigDict(from_attributes=True)


class ChatPage(BaseModel):
    total: int
    chats: list[ChatSummary]


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

    # Conversation position. `relation` is new_topic | follow_up, and
    # `standalone_question` is what retrieval actually ran on.
    chat_id: UUID | None = None
    turn_index: int = 0
    relation: str | None = None
    standalone_question: str | None = None
    context_strategy: str | None = None

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


class ChatDetail(BaseModel):
    id: UUID
    title: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    turns: list[QueryRunDetail]
