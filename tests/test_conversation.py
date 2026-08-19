"""Resolving a question against its conversation.

The expensive failure here is the false positive: carrying maternity-leave
context into a question about expenses produces a confident wrong answer.
So the rules below are biased toward "new topic", and the tests check that
bias as much as they check the detection.
"""

import pytest

from port6.services.rag.base import RagMode, RagResult, RetrievedChunk
from port6.services.rag.conversation import (
    Resolution,
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


# --- reporting the family on the reuse path ---------------------------

class TestReuseReportsItsFamily:
    """`/ask` names a composition and leaves `mode` unset.

    The reuse branch is the one path in `query_in_chat` that does not go
    through `query()`, so it built its own metadata — and read the family
    from `mode`, which is None on every request the API makes. Any
    follow-up that reused the previous turn's sources returned a 500.
    """

    def test_a_composition_supplies_the_family(self):
        from port6.services.rag import pipelines
        from port6.services.rag.system import _family_of

        agentic = pipelines.resolve(mode="agentic")

        assert _family_of(None, agentic) is RagMode.AGENTIC

    def test_a_bare_mode_still_works(self):
        from port6.services.rag.system import _family_of

        assert _family_of("hybrid", None) is RagMode.HYBRID

    def test_neither_falls_back_to_the_configured_default(self):
        """Same fallback `query()` uses, rather than a second opinion."""

        from port6.services.rag import pipelines
        from port6.services.rag.system import _family_of

        assert _family_of(None, None) is pipelines.resolve().family


# --- a question that needs history, but does not look like it ----------

class TestBareInterrogativesNeedContext:
    """The cheap gate decides whether the classifier runs at all.

    It was described as failing safe — worst case, prior context is
    ignored. It does not. "Which benefits are restricted?" was let through
    as self-contained, searched as written, and came back "not in the
    library" one turn after the conversation had answered exactly that.
    The question after it then reused those empty sources and failed too.
    """

    def test_a_short_which_question_is_treated_as_dependent(self):
        from port6.services.rag.conversation import looks_self_contained

        assert not looks_self_contained("Which benefits are restricted?")

    def test_others_of_the_same_shape_too(self):
        from port6.services.rag.conversation import looks_self_contained

        for question in (
            "Which ones are excluded?",
            "Which sections apply?",
            "When does it end?",
            "Who approves that?",
        ):
            assert not looks_self_contained(question), question

    def test_a_genuinely_complete_question_is_left_alone(self):
        """Widening the gate must not send every question to the model."""

        from port6.services.rag.conversation import looks_self_contained

        for question in (
            "Which policy covers international travel expenses?",
            "When must carried-over annual leave be taken by?",
            "Who must approve a trip over 1,200 GBP?",
            "How many days of annual leave do employees get?",
            "What is the notice period?",
        ):
            assert looks_self_contained(question), question

    def test_a_library_wide_question_stays_self_contained(self):
        """It names its own scope, even opening with a bare interrogative."""

        from port6.services.rag.conversation import looks_self_contained

        assert looks_self_contained("Which documents mention probation?")


# --- what a reused turn reuses ----------------------------------------

class TestReuseTakesTheLastAnsweredTurn:

    class Run:
        def __init__(self, turn_index, answered):
            self.turn_index = turn_index
            self.answered = answered

    def test_the_newest_answered_turn_wins(self):
        """Not simply the newest. A turn that answered nothing still stored
        the chunks retrieval happened to return, and reusing those
        guarantees the next turn answers nothing either."""

        from port6.services.history.chats import pick_reusable

        runs = [self.Run(3, False), self.Run(2, True), self.Run(1, True)]

        assert pick_reusable(runs).turn_index == 2

    def test_the_newest_turn_is_the_fallback(self):
        """Better thin context than none when nothing has answered yet."""

        from port6.services.history.chats import pick_reusable

        runs = [self.Run(3, False), self.Run(2, False)]

        assert pick_reusable(runs).turn_index == 3

    def test_no_turns_at_all_is_not_an_error(self):
        from port6.services.history.chats import pick_reusable

        assert pick_reusable([]) is None


# --- carried context has to reach the model ---------------------------

class TestCarriedContextReachesGeneration:
    """Merging it into the finished result is not the same as using it.

    `combine` is documented as searching the rewritten question and merging
    a few chunks from the previous turn. The merge ran on the result *after*
    generation, so the model never read them: "compare it with our company
    policy" could not see the previous turn's web figures, answered "not in
    the library", and then listed those chunks as retrieved-but-unused —
    unused because nothing had read them.
    """

    def chunk(self, number, chunk_id, score=None, fused=None, web=False):
        return RetrievedChunk(
            number=number,
            chunk_id=chunk_id,
            document_id="web" if web else "d1",
            filename="pazcare.com" if web else "hr_policy.md",
            content=f"content {chunk_id}",
            url="https://example.test/x" if web else None,
            score=score,
            fused_score=fused,
        )

    def test_an_uncapped_merge_keeps_every_distinct_chunk(self):
        fresh = [self.chunk(1, "a"), self.chunk(2, "b")]
        carried = [self.chunk(1, "b"), self.chunk(2, "c")]

        merged = merge_context(fresh, carried)

        assert [c.chunk_id for c in merged] == ["a", "b", "c"]

    async def test_the_top_k_trim_does_not_discard_carried_chunks(self):
        """Carried chunks arrive without a fused rank, so they sort last.

        Appending them before the trim meant `[:top_k]` threw away exactly
        the context the follow-up had been given them for.
        """

        from port6.services.rag.agent import node_context_builder

        retrieved = [
            self.chunk(i, f"fresh-{i}", fused=0.02 - i / 1000)
            for i in range(1, 6)
        ]
        carried = [self.chunk(1, "web:1", web=True)]

        out = await node_context_builder(
            {
                "retrieved_chunks": retrieved,
                "carried_chunks": carried,
                "top_k": 5,
            }
        )

        context = out["final_context"]

        assert len(context) == 6, "the carried chunk was trimmed away"
        assert context[-1].chunk_id == "web:1"
        assert [c.number for c in context] == [1, 2, 3, 4, 5, 6]

    async def test_no_carried_context_leaves_the_trim_alone(self):
        from port6.services.rag.agent import node_context_builder

        retrieved = [
            self.chunk(i, f"fresh-{i}", fused=0.02 - i / 1000)
            for i in range(1, 9)
        ]

        out = await node_context_builder(
            {"retrieved_chunks": retrieved, "top_k": 5}
        )

        assert len(out["final_context"]) == 5


# --- reuse is a bet, and a lost bet must not cost the answer -----------

class TestReuseFallsBackToRetrieval:
    """Reuse answers from the previous turn's sources without retrieving.

    That is a bet those sources cover the new question too. When they do
    not, the turn used to fail outright: "how many leaves?" after a turn
    whose chunks happened to miss the entitlement section reported the
    library empty, while retrieving on the rewritten question — "How many
    days of annual leave are employees entitled to?" — finds 22 days first
    time.
    """

    def _chunk(self):
        return RetrievedChunk(
            number=1,
            chunk_id="c1",
            document_id="d1",
            filename="hr_policy.md",
            content="Leave is administered through the People Portal.",
        )

    async def _run(self, monkeypatch, reuse_answers):
        from port6.services.rag import system

        monkeypatch.setattr(system, "get_setting", lambda key: True)
        monkeypatch.setattr(
            system.smalltalk, "classify", lambda question: None
        )

        async def fake_resolve(question, turns):
            return Resolution(
                relation="follow_up",
                strategy="reuse",
                search_question="How many days of annual leave?",
                reason="test",
                method="test",
            )

        monkeypatch.setattr(system, "resolve", fake_resolve)

        async def fake_generate(question, chunks, *args, **kwargs):
            return {
                "answer": "22 days" if reuse_answers else "not found",
                "answered": reuse_answers,
                "citations": [],
                "chunks": chunks,
                "conflicts": [],
            }

        monkeypatch.setattr(system, "generate_answer", fake_generate)

        retrieved = {"called": False}

        async def fake_query(question, **kwargs):
            retrieved["called"] = True
            return RagResult(
                question=question,
                answer="Employees accrue 22 days of paid annual leave.",
                answered=True,
                retrieval_method="fresh",
            )

        monkeypatch.setattr(system, "query", fake_query)

        result, _ = await system.query_in_chat(
            question="how many leaves?",
            turns=[{"question": "annual leave", "answer": "a", "documents": []}],
            previous_chunks=[self._chunk()],
            top_k=5,
        )

        return result, retrieved["called"]

    async def test_a_won_bet_skips_retrieval(self, monkeypatch):
        result, retrieved = await self._run(monkeypatch, reuse_answers=True)

        assert not retrieved, "reuse answered, so nothing should be retrieved"
        assert result.answered

    async def test_a_lost_bet_retrieves_instead_of_giving_up(self, monkeypatch):
        result, retrieved = await self._run(monkeypatch, reuse_answers=False)

        assert retrieved, "reuse failed and nothing was retrieved"
        assert result.answered
        assert "22 days" in result.answer


# --- short questions lean on the turn before them ----------------------

class TestShortQuestionsAreNeverSelfContained:
    """The signal list is a list of shapes, and questions kept arriving in
    shapes nobody had listed.

    "total how many?", "same for annual?", "for annual leave?" carry no
    pronoun, open with no interrogative in the list, and are plainly about
    the turn before them. Each was searched as written and reported the
    library empty. Length is the property they share.
    """

    def test_a_four_word_question_goes_to_the_classifier(self):
        from port6.services.rag.conversation import looks_self_contained

        for question in (
            "total how many?",
            "same for annual?",
            "for annual leave?",
            "will they carry",
            "and probation?",
            "tell abt it",
        ):
            assert not looks_self_contained(question), question

    def test_a_full_question_is_still_searched_as_written(self):
        from port6.services.rag.conversation import looks_self_contained

        for question in (
            "What is the notice period for resignation?",
            "How many days of annual leave do employees get?",
            "What is the expense limit for hotels?",
            "Does sick leave carry over?",
        ):
            assert looks_self_contained(question), question

    def test_a_library_wide_question_is_exempt(self):
        """It names its own scope, however short it is."""

        from port6.services.rag.conversation import looks_self_contained

        assert looks_self_contained("which documents mention probation?")


class TestCorrectionsAreFollowUps:
    """"no the annual leaves" is the most unmistakable follow-up there is.

    Every corrective phrasing used to be searched as written, so the
    correction was answered as a fresh question about the words "no the
    annual leaves" — and failed.
    """

    def test_corrections_are_dependent(self):
        from port6.services.rag.conversation import looks_self_contained

        for question in (
            "no the annual leaves",
            "not sick leave, the annual one",
            "i meant annual leave entitlement",
            "actually the annual leave policy",
        ):
            assert not looks_self_contained(question), question

    def test_a_question_that_merely_starts_with_no_is_still_asked(self):
        """"Notice" must not be read as "not"."""

        from port6.services.rag.conversation import looks_self_contained

        assert looks_self_contained("Notice periods for termination of employment?")
