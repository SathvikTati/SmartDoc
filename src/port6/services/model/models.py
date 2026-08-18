from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from port6.services.db.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    filename = Column(
        String,
        nullable=False,
    )

    file_type = Column(
        String,
        nullable=False,
    )

    size_bytes = Column(
        BigInteger,
        nullable=False,
    )

    sha256 = Column(
        String(64),
        unique=True,
        nullable=False,
    )

    content_sha256 = Column(
        String(64),
        unique=True,
        nullable=False,
    )

    storage_path = Column(
        String,
        nullable=False,
    )

    content = Column(
        Text,
        nullable=False,
    )

    status = Column(
        String(20),
        nullable=False,
        default="UPLOADED",
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    summary = Column(
        Text,
        nullable=True,
    )

    error_message = Column(
        Text,
        nullable=True,
    )

    # -------------------------------------------------------------
    # Ingestion attempts
    #
    # A FAILED document is not a dead end: the file is still on disk, so
    # it can be reprocessed once whatever broke is fixed. These record
    # how many tries it has had and what went wrong last time.
    # -------------------------------------------------------------

    attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    last_attempt_at = Column(
        DateTime,
        nullable=True,
    )

    # Why it failed, coarsely: "provider" (the model or its key), "parse",
    # "storage", or "unknown". Drives whether retrying is worth offering.
    failure_kind = Column(
        String(32),
        nullable=True,
    )


class Setting(Base):
    """A runtime-tunable value, editable without a redeploy.

    Only settings that genuinely change behaviour at request time live
    here. Deploy-time facts (upload limits, the Chroma path) stay in
    config.yaml, and everything about which model to call stays in .env —
    a provider switch is not a runtime tweak.

    Values are stored as JSON so a setting can be a number, a string, a
    boolean or null without a column per type.
    """

    __tablename__ = "settings"

    key = Column(
        String(80),
        primary_key=True,
    )

    value = Column(
        JSONB,
        nullable=True,
    )

    # Shown by GET /settings so a caller knows what a key is for.
    description = Column(
        Text,
        nullable=True,
    )

    # The code default, kept so a setting can be reverted without
    # remembering what it used to be.
    default_value = Column(
        JSONB,
        nullable=True,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Prompt(Base):
    """An LLM prompt, stored so it can be changed without a redeploy.

    One `template` rather than a system/human pair. The split mirrored the
    two chat turns, but every prompt here ordered itself the same way
    anyway — instructions, then sources, then the question — so the second
    field only ever held the last line or two, and editing a prompt meant
    keeping two fields consistent by hand.

    `variables` records the placeholders the template must contain, which
    is what stops a malformed edit from breaking a pipeline at the worst
    possible moment.
    """

    __tablename__ = "prompts"

    name = Column(
        String(80),
        primary_key=True,
    )

    template = Column(
        Text,
        nullable=False,
    )

    description = Column(
        Text,
        nullable=True,
    )

    variables = Column(
        JSONB,
        nullable=False,
        default=list,
    )

    # Bumped on every edit, and recorded on each query so an answer can be
    # traced back to the exact prompt that produced it.
    version = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    # The shipped text, so an edit can always be reverted.
    default_template = Column(
        Text,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Chat(Base):
    """One conversation.

    A chat is the unit a follow-up is resolved against: "what about sick
    leave?" only means something relative to the turns before it. Runs
    outside a chat still work — every question creates one implicitly, so
    a caller never has to manage this to ask something.
    """

    __tablename__ = "chats"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    # Taken from the first question, so a chat is recognisable in a list
    # without opening it.
    title = Column(
        Text,
        nullable=False,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    # Bumped on every turn, so chats sort by recent activity rather than
    # by when they were started.
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class QueryRun(Base):
    """One question and everything the system did to answer it.

    Persisted rather than held in the browser so a question asked
    yesterday can still be opened, and so retrieval behaviour can be
    reviewed over time instead of only in the moment.
    """

    __tablename__ = "query_runs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # 0 for the first question in a chat.
    turn_index = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    question = Column(
        Text,
        nullable=False,
    )

    # "new_topic" | "follow_up". How the question was read in context.
    relation = Column(
        String(20),
        nullable=True,
    )

    # A follow-up rewritten to stand on its own, which is what retrieval
    # actually ran on. Null when the question already stood alone.
    standalone_question = Column(
        Text,
        nullable=True,
    )

    # "fresh" | "combine" | "reuse" — what was done about prior context.
    context_strategy = Column(
        String(20),
        nullable=True,
    )

    # Which named strategy answered. `mode` is still recorded alongside
    # it: it is the family, and every run before pipelines existed has
    # one of those and no pipeline.
    pipeline = Column(
        String(60),
        nullable=True,
        index=True,
    )

    mode = Column(
        String(20),
        nullable=False,
    )

    top_k = Column(
        Integer,
        nullable=False,
    )

    answer = Column(
        Text,
        nullable=False,
    )

    answered = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    citation_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    chunk_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    latency_ms = Column(
        Float,
        nullable=True,
    )

    retrieval_method = Column(
        Text,
        nullable=True,
    )

    # The full RagResult payload, so reopening a run shows exactly what was
    # shown the first time — citations, evidence and the retrieval trace.
    result = Column(
        JSONB,
        nullable=False,
    )

    # Which prompt versions were live for this run.
    prompt_versions = Column(
        JSONB,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
