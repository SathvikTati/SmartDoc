"""Deleting questions must not leave conversations behind.

The reported symptom: "Clear all" emptied the history page, but the sidebar
kept listing conversations. `query_runs.chat_id` cascades one way only —
deleting a chat removes its turns, but deleting the turns left the chat as
an empty shell, and the sidebar lists chats.

These run against the real database rather than SQLite, because the tables
use JSONB and Postgres UUIDs. Everything happens inside a transaction that
is rolled back, so existing history is untouched.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from port6.config import DATABASE_URL
from port6.services.history import chats as chat_service
from port6.services.history.service import (
    clear_runs,
    delete_run,
    prune_empty_chats,
)
from port6.services.model.models import Chat, QueryRun


def _database_available() -> bool:
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="needs the Postgres database",
)


@pytest.fixture
def db():
    """A session whose work is always rolled back."""

    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()

    # The functions under test commit; a savepoint keeps those commits
    # inside the outer transaction so the rollback below still undoes them.
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def add_chat(db, title, turns):
    chat = Chat(title=title)
    db.add(chat)
    db.flush()

    for index in range(turns):
        db.add(
            QueryRun(
                chat_id=chat.id,
                turn_index=index,
                question=f"{title} #{index}",
                mode="hybrid",
                top_k=5,
                answer="answer",
                answered=True,
                citation_count=0,
                chunk_count=0,
                result={},
            )
        )

    db.commit()
    return chat


def chats_in(db):
    return db.query(Chat).count()


def runs_in(db):
    return db.query(QueryRun).count()


def test_clearing_history_removes_the_conversations_too(db):
    """The exact reported bug: history emptied, sidebar still populated."""

    add_chat(db, "Maternity leave", turns=2)
    add_chat(db, "SEC-4412", turns=1)

    clear_runs(db)

    assert runs_in(db) == 0
    assert chats_in(db) == 0


def test_deleting_the_last_turn_removes_its_conversation(db):
    before = chats_in(db)

    chat = add_chat(db, "Only question", turns=1)
    run = db.query(QueryRun).filter(QueryRun.chat_id == chat.id).one()

    delete_run(db, run.id)

    assert chats_in(db) == before


def test_deleting_one_turn_of_several_keeps_the_conversation(db):
    before = chats_in(db)

    chat = add_chat(db, "Two questions", turns=2)
    run = (
        db.query(QueryRun)
        .filter(QueryRun.chat_id == chat.id)
        .order_by(QueryRun.turn_index)
        .first()
    )

    delete_run(db, run.id)

    assert chats_in(db) == before + 1
    assert (
        db.query(QueryRun).filter(QueryRun.chat_id == chat.id).count() == 1
    )


def test_prune_sweeps_conversations_left_behind_earlier(db):
    """Rows created before this was handled still need clearing."""

    add_chat(db, "Has turns", turns=1)
    db.add(Chat(title="Orphan A"))
    db.add(Chat(title="Orphan B"))
    db.commit()

    assert prune_empty_chats(db) >= 2
    assert (
        db.query(Chat).filter(Chat.title.like("Orphan%")).count() == 0
    )


def test_an_empty_conversation_is_never_listed(db):
    """Defensive: even if one survives a delete, it is not shown."""

    add_chat(db, "Real conversation", turns=1)
    db.add(Chat(title="Orphan"))
    db.commit()

    titles = [chat["title"] for chat in chat_service.list_chats(db)["chats"]]

    assert "Real conversation" in titles
    assert "Orphan" not in titles


def test_turn_counts_are_reported_per_conversation(db):
    add_chat(db, "Three turns", turns=3)
    add_chat(db, "One turn", turns=1)

    counts = {
        chat["title"]: chat["turn_count"]
        for chat in chat_service.list_chats(db)["chats"]
    }

    assert counts["Three turns"] == 3
    assert counts["One turn"] == 1
