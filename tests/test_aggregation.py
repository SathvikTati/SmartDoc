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

    covered = group_by_document(
        chunks, chunks_per_document=2, max_documents=8
    )["chunks"]

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

    covered = group_by_document(
        chunks, chunks_per_document=1, max_documents=8
    )["chunks"]

    assert [item.document_id for item in covered] == ["near", "far"]


def test_max_documents_caps_the_breadth():
    chunks = [
        chunk(f"d{index}", f"d{index}.md", index / 10, number=index)
        for index in range(1, 11)
    ]

    covered = group_by_document(
        chunks, chunks_per_document=1, max_documents=3
    )["chunks"]

    assert len(covered) == 3


def test_chunks_without_a_score_sink_rather_than_crash():
    chunks = [
        chunk("scored", "scored.md", 0.4, number=1),
        chunk("unscored", "unscored.md", None, number=2),
    ]

    covered = group_by_document(
        chunks, chunks_per_document=1, max_documents=8
    )["chunks"]

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


def test_the_grouped_context_carries_only_the_citation_marker():
    """Section and page are deliberately not in the grouped header.

    They were, and the model copied the header line straight into the
    answer — "[1] | section: Handbook > 5. Grievance | page 3" appearing
    in the middle of a sentence. Aggregation only needs the marker; the
    section and page are still on the chunk, so the citation and the
    evidence panel are unaffected.
    """

    source = chunk(
        "a",
        "handbook.pdf",
        0.1,
        content="Grievances go to HR.",
        number=1,
        section_path="Handbook > 5. Grievance",
        page_number=3,
    )

    context = build_grouped_context([source])

    assert "=== DOCUMENT: handbook.pdf ===" in context
    assert "[1] Grievances go to HR." in context

    assert "section:" not in context
    assert "page 3" not in context

    # Still available where citations are built from.
    assert source.section_path == "Handbook > 5. Grievance"
    assert source.page_number == 3


def test_a_long_chunk_is_clipped_so_the_model_summarises_it():
    """Given the full text of several documents the model transcribes."""

    from port6.services.rag.aggregation import _excerpt

    long_text = "This sentence is about probation. " * 60

    context = build_grouped_context(
        [chunk("a", "hr.md", 0.1, content=long_text, number=1)]
    )

    assert len(context) < len(long_text)
    assert len(_excerpt(long_text)) <= 460


def test_a_short_chunk_is_left_whole():
    from port6.services.rag.aggregation import _excerpt

    assert _excerpt("Probation lasts 3 months.") == "Probation lasts 3 months."


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


# --- coverage follows the pipeline ---------------------------------------

class TestCoverageRespectsThePipeline:
    """Every pipeline used to return byte-identical chunks here.

    `coverage_search` hardcoded semantic + keyword and ignored the
    caller, so a four-way comparison of a library-wide question showed
    four columns of the same result — implying four strategies had run
    when one had.
    """

    async def test_a_keyword_only_pipeline_uses_no_semantic_search(
        self,
        monkeypatch,
    ):
        from port6.services.rag import aggregation

        async def fail(*args, **kwargs):
            raise AssertionError("semantic_search should not have run")

        monkeypatch.setattr(aggregation, "semantic_search", fail)
        monkeypatch.setattr(
            aggregation,
            "keyword_search",
            lambda *a, **k: [
                chunk("a", "hr_policy.md", 0.1, content="Probation is 3 months.")
            ],
        )

        result = await aggregation.coverage_search(
            "which documents mention probation?",
            retrievers=("keyword",),
        )

        assert result["documents"] == ["hr_policy.md"]

    async def test_a_semantic_only_pipeline_uses_no_keyword_search(
        self,
        monkeypatch,
    ):
        from port6.services.rag import aggregation

        def fail(*args, **kwargs):
            raise AssertionError("keyword_search should not have run")

        async def semantic(*args, **kwargs):
            return [
                chunk("a", "hr_policy.md", 0.1, content="Probation is 3 months.")
            ]

        monkeypatch.setattr(aggregation, "semantic_search", semantic)
        monkeypatch.setattr(aggregation, "keyword_search", fail)

        result = await aggregation.coverage_search(
            "which documents mention probation?",
            retrievers=("semantic",),
        )

        assert result["documents"] == ["hr_policy.md"]

    async def test_without_a_keyword_signal_nothing_is_excluded(
        self,
        monkeypatch,
    ):
        """The weakness worth being able to see.

        The keyword retriever is what decides which documents genuinely
        *mention* the topic. A semantic-only pipeline has no such signal,
        so it covers documents that merely sit near the topic in
        embedding space.
        """

        from port6.services.rag import aggregation

        async def semantic(*args, **kwargs):
            return [
                chunk("a", "hr_policy.md", 0.1, content="Probation is 3 months."),
                chunk("b", "unrelated.md", 0.8, content="Coffee is provided."),
            ]

        monkeypatch.setattr(aggregation, "semantic_search", semantic)
        monkeypatch.setattr(aggregation, "keyword_search", lambda *a, **k: [])

        result = await aggregation.coverage_search(
            "which documents mention probation?",
            retrievers=("semantic",),
        )

        assert result["documents_excluded"] == 0
        assert "unrelated.md" in result["documents"]

    async def test_no_retrievers_named_means_both(self, monkeypatch):
        """What an agentic pipeline gets: the previous behaviour."""

        from port6.services.rag import aggregation

        calls = []

        async def semantic(*args, **kwargs):
            calls.append("semantic")
            return [chunk("a", "hr_policy.md", 0.1, content="Probation.")]

        def keyword(*args, **kwargs):
            calls.append("keyword")
            return [chunk("a", "hr_policy.md", 0.1, content="Probation.")]

        monkeypatch.setattr(aggregation, "semantic_search", semantic)
        monkeypatch.setattr(aggregation, "keyword_search", keyword)

        await aggregation.coverage_search("which documents mention probation?")

        assert calls == ["semantic", "keyword"]


# --- top_k is a budget, here as everywhere else -------------------------

class TestCoverageBudget:
    """Coverage decides how chunks are spread, not how many there are.

    It used to return max_documents x chunks_per_document regardless of
    what was asked for, so a request for 5 came back with 15 — three
    times the context the caller had budgeted, unexplained.
    """

    def _four_documents(self):
        return [
            chunk(f"d{i}", f"d{i}.md", i / 10, number=i)
            for i in range(1, 5)
        ] + [
            chunk(f"d{i}", f"d{i}.md", i / 10 + 0.01, number=i + 10)
            for i in range(1, 5)
        ]

    def test_the_budget_is_never_exceeded(self):
        covered = group_by_document(
            self._four_documents(),
            chunks_per_document=2,
            max_documents=8,
            budget=5,
        )

        assert len(covered["chunks"]) == 5

    def test_breadth_comes_before_depth(self):
        """Every document gets its first chunk before any gets a second."""

        covered = group_by_document(
            self._four_documents(),
            chunks_per_document=2,
            max_documents=8,
            budget=5,
        )

        documents = [c.document_id for c in covered["chunks"]]

        assert set(documents[:4]) == {"d1", "d2", "d3", "d4"}

    def test_a_budget_below_the_document_count_drops_the_weakest(self):
        covered = group_by_document(
            self._four_documents(),
            chunks_per_document=2,
            max_documents=8,
            budget=2,
        )

        assert len(covered["chunks"]) == 2
        assert {c.document_id for c in covered["chunks"]} == {"d1", "d2"}
        assert covered["documents_matched"] == 4

    def test_no_budget_keeps_the_previous_behaviour(self):
        covered = group_by_document(
            self._four_documents(),
            chunks_per_document=2,
            max_documents=8,
        )

        assert len(covered["chunks"]) == 8

    def test_a_budget_larger_than_the_candidates_takes_them_all(self):
        covered = group_by_document(
            self._four_documents(),
            chunks_per_document=2,
            max_documents=8,
            budget=100,
        )

        assert len(covered["chunks"]) == 8

    def test_truncation_is_reported_not_silent(self):
        covered = group_by_document(
            self._four_documents(),
            chunks_per_document=2,
            max_documents=8,
            budget=2,
        )

        assert covered["documents_matched"] == 4
        assert covered["documents_covered"] == 2
