"""Cross-document aggregation.

Detection, topic extraction and coverage grouping are pure functions, and
they decide whether an enumeration question is answerable at all: with
plain top-k every chunk can come from one document, so the model is never
shown the others.
"""

import pytest

from port6.services.rag.aggregation import (
    build_grouped_context,
    group_by_document,
    is_aggregation_question,
    matched_pattern,
    topic_terms,
)
from port6.services.rag.base import RetrievedChunk


def chunk(document_id, filename, score, content="body", number=1, **kwargs):
    return RetrievedChunk(
        number=number,
        chunk_id=f"{document_id}:{number}",
        document_id=document_id,
        filename=filename,
        content=content,
        score=score,
        **kwargs,
    )


# --- detection --------------------------------------------------------

@pytest.mark.parametrize(
    "question",
    [
        "Which documents mention probation?",
        "What documents cover annual leave?",
        "What does each policy say about notice periods?",
        "Compare the leave policies across all documents",
        "List all the documents about security",
        "How many documents mention SEC-4412?",
        "Do any policies discuss remote work?",
        "Is probation mentioned in any document?",
        "Summarise all the documents",
        "In every policy, what is the notice period?",
    ],
)
def test_library_wide_questions_are_detected(question):
    assert is_aggregation_question(question)
    assert matched_pattern(question)


@pytest.mark.parametrize(
    "question",
    [
        # The classic false positive: "how many" about a single fact.
        "How much annual leave do employees get?",
        "How many days of sick leave are there?",
        "What is control SEC-4412?",
        "What is the grievance procedure?",
        "Tell me about the probation period",
        "",
    ],
)
def test_ordinary_questions_are_not_treated_as_aggregation(question):
    """A false positive costs breadth on a question that needed depth."""

    assert not is_aggregation_question(question)


# --- topic extraction -------------------------------------------------

def test_topic_strips_the_asking_about_the_library_vocabulary():
    """"policy" and "say" appear in every document; "probation" does not."""

    assert topic_terms("What does each policy say about probation?") == [
        "probation"
    ]


def test_topic_survives_a_bare_enumeration():
    assert topic_terms("Which documents mention probation?") == ["probation"]


def test_topic_keeps_multi_word_subjects():
    assert topic_terms("Compare notice periods across all documents") == [
        "notice",
        "periods",
    ]


def test_topic_can_be_empty_when_a_question_is_only_scaffolding():
    # The caller falls back to the full query rather than matching nothing.
    assert topic_terms("List all the documents") == []


# --- coverage grouping ------------------------------------------------

def test_each_document_contributes_and_none_can_crowd_the_others_out():
    """The bug this exists to prevent: one document taking every slot."""

    chunks = [
        chunk("a", "verbose.md", 0.10, number=1),
        chunk("a", "verbose.md", 0.11, number=2),
        chunk("a", "verbose.md", 0.12, number=3),
        chunk("a", "verbose.md", 0.13, number=4),
        chunk("b", "quiet.md", 0.50, number=5),
    ]

    covered = group_by_document(chunks, chunks_per_document=2, max_documents=8)

    by_document = {}
    for item in covered:
        by_document.setdefault(item.document_id, 0)
        by_document[item.document_id] += 1

    assert by_document == {"a": 2, "b": 1}


def test_documents_are_ordered_by_their_best_chunk():
    chunks = [
        chunk("far", "far.md", 0.90, number=1),
        chunk("near", "near.md", 0.10, number=2),
    ]

    covered = group_by_document(chunks, chunks_per_document=1, max_documents=8)

    assert [item.document_id for item in covered] == ["near", "far"]


def test_max_documents_caps_the_breadth():
    chunks = [
        chunk(f"d{index}", f"d{index}.md", index / 10, number=index)
        for index in range(1, 11)
    ]

    covered = group_by_document(chunks, chunks_per_document=1, max_documents=3)

    assert len(covered) == 3


def test_chunks_without_a_score_sink_rather_than_crash():
    chunks = [
        chunk("scored", "scored.md", 0.4, number=1),
        chunk("unscored", "unscored.md", None, number=2),
    ]

    covered = group_by_document(chunks, chunks_per_document=1, max_documents=8)

    assert [item.document_id for item in covered] == ["scored", "unscored"]


# --- grouped context --------------------------------------------------

def test_context_marks_document_boundaries():
    """The model has to enumerate documents, so it must be able to see
    where one ends and the next begins."""

    context = build_grouped_context(
        [
            chunk("a", "hr_policy.md", 0.1, content="Probation is 3 months.", number=1),
            chunk("a", "hr_policy.md", 0.2, content="Notice is 30 days.", number=2),
            chunk("b", "travel_policy.md", 0.3, content="Probation needs approval.", number=3),
        ]
    )

    assert "=== DOCUMENT: hr_policy.md ===" in context
    assert "=== DOCUMENT: travel_policy.md ===" in context
    # Both of the first document's chunks sit under one heading.
    assert context.index("[1]") < context.index("[2]")
    assert context.index("[2]") < context.index("travel_policy.md")


def test_context_carries_section_and_page_for_citation():
    context = build_grouped_context(
        [
            chunk(
                "a",
                "handbook.pdf",
                0.1,
                content="Grievances go to HR.",
                number=1,
                section_path="Handbook > 5. Grievance",
                page_number=3,
            )
        ]
    )

    assert "section: Handbook > 5. Grievance" in context
    assert "page 3" in context


# --- validation scoring -----------------------------------------------

def test_validator_scores_on_content_words_not_the_question_frame():
    """"Which documents mention probation?" used to score 50% because
    "mention" never appears in a policy, which pushed a perfect retrieval
    into the band where the model is asked — and it then rejected it."""

    from port6.services.rag.validation import keyword_overlap

    chunks = [
        chunk("a", "hr_policy.md", 0.1, content="Probation lasts 3 months."),
    ]

    assert keyword_overlap("Which documents mention probation?", chunks) == 1.0


def test_validator_still_penalises_a_genuine_miss():
    from port6.services.rag.validation import keyword_overlap

    chunks = [chunk("a", "hr_policy.md", 0.1, content="Annual leave is 22 days.")]

    assert keyword_overlap("Which documents mention probation?", chunks) == 0.0
