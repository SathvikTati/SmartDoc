"""Resolving a question against its conversation.

The expensive failure here is the false positive: carrying maternity-leave
context into a question about expenses produces a confident wrong answer.
So the rules below are biased toward "new topic", and the tests check that
bias as much as they check the detection.
"""

import pytest

from port6.services.rag.base import RetrievedChunk
from port6.services.rag.conversation import (
    COMBINE,
    FOLLOW_UP,
    FRESH,
    NEW_TOPIC,
    first_turn,
    looks_self_contained,
    merge_context,
    render_history,
)


def chunk(chunk_id, content="body", number=1):
    return RetrievedChunk(
        number=number,
        chunk_id=chunk_id,
        document_id="doc",
        filename="hr_policy.md",
        content=content,
    )


# --- the cheap half of the decision -----------------------------------

@pytest.mark.parametrize(
    "question",
    [
        "What about sick leave?",
        "Who is eligible?",
        "And the notice period?",
        "How about probation?",
        "Explain that more simply.",
        "What is it?",
        "Are they paid?",
        "Tell me more",
        "Why?",
    ],
)
def test_context_dependent_questions_go_to_the_classifier(question):
    assert not looks_self_contained(question)


@pytest.mark.parametrize(
    "question",
    [
        "What is the maternity leave policy?",
        "What is the expense limit for hotels?",
        "How much annual leave do employees get?",
        "What is control SEC-4412?",
        "Which documents mention probation?",
    ],
)
def test_complete_questions_skip_the_classifier(question):
    """A question that can be searched as written needs no model call,
    and treating it as a new topic can only fail safe."""

    assert looks_self_contained(question)


def test_a_first_question_never_pays_for_classification():
    resolution = first_turn("What is the maternity leave policy?")

    assert resolution.relation == NEW_TOPIC
    assert resolution.strategy == FRESH
    assert resolution.method == "no-history"
    assert resolution.search_question == "What is the maternity leave policy?"


# --- history rendering ------------------------------------------------

def test_history_is_limited_to_the_recent_turns():
    turns = [
        {"question": f"Q{index}", "answer": f"A{index}", "documents": []}
        for index in range(10)
    ]

    rendered = render_history(turns, max_turns=3)

    assert "Q9" in rendered and "Q7" in rendered
    # A topic from ten questions ago must not pull the answer off course.
    assert "Q6" not in rendered


def test_history_clips_long_answers():
    turns = [{"question": "Q", "answer": "x" * 900, "documents": []}]

    rendered = render_history(turns, max_turns=4)

    assert "…" in rendered
    assert len(rendered) < 400


def test_history_lists_the_documents_a_turn_used():
    turns = [
        {
            "question": "Maternity leave?",
            "answer": "26 weeks.",
            "documents": ["hr_policy.md", "policy.pdf"],
        }
    ]

    rendered = render_history(turns, max_turns=4)

    assert "Documents used: hr_policy.md, policy.pdf" in rendered


def test_history_survives_a_turn_with_no_answer():
    rendered = render_history(
        [{"question": "Q", "answer": None, "documents": None}],
        max_turns=4,
    )

    assert "(no answer)" in rendered


# --- merging previous context -----------------------------------------

def test_fresh_chunks_lead_and_prior_ones_fill_in():
    """The follow-up was rewritten to be searchable, so what it retrieved
    is the better evidence; prior chunks recover what the rewrite could
    not."""

    fresh = [chunk("new-1"), chunk("new-2")]
    previous = [chunk("old-1"), chunk("old-2")]

    merged = merge_context(fresh, previous, carry_over=3)

    assert [c.chunk_id for c in merged] == ["new-1", "new-2", "old-1", "old-2"]


def test_carry_over_is_capped_so_prior_context_cannot_dominate():
    fresh = [chunk("new-1")]
    previous = [chunk(f"old-{index}") for index in range(10)]

    merged = merge_context(fresh, previous, carry_over=2)

    assert len(merged) == 3


def test_a_chunk_retrieved_again_is_not_duplicated():
    fresh = [chunk("shared"), chunk("new")]
    previous = [chunk("shared"), chunk("old")]

    merged = merge_context(fresh, previous, carry_over=3)

    assert [c.chunk_id for c in merged] == ["shared", "new", "old"]


def test_merged_chunks_are_renumbered_for_citation():
    merged = merge_context(
        [chunk("a", number=7)],
        [chunk("b", number=9)],
        carry_over=1,
    )

    assert [c.number for c in merged] == [1, 2]


def test_no_previous_context_is_just_the_fresh_chunks():
    fresh = [chunk("a")]

    assert merge_context(fresh, [], carry_over=3) == fresh


# --- the shape the rest of the pipeline relies on ---------------------

def test_resolution_serialises_for_the_trace_and_the_stored_run():
    resolution = first_turn("Anything?")

    payload = resolution.as_dict()

    assert set(payload) == {
        "relation",
        "strategy",
        "search_question",
        "standalone_question",
        "reason",
        "method",
    }


def test_relation_and_strategy_constants_are_what_the_db_stores():
    assert (NEW_TOPIC, FOLLOW_UP) == ("new_topic", "follow_up")
    assert (FRESH, COMBINE) == ("fresh", "combine")
