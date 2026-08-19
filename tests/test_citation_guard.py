"""The guard on an answer that cites nothing.

The aggregate layout is where this bites. Asked what each document says, the
model writes a heading per document with points underneath and drops every
marker on the way — and an answer with no markers has no citations, so the
evidence panel reports every source as retrieved-but-unused. A good answer
over four documents arrives with nothing attached to any of it.

The markers cannot be added afterwards. A citation this system wrote rather
than read is a fabricated attribution, so the model is asked again instead —
and the retry is kept only if it actually fixed the problem.
"""

import pytest

from port6.services.rag import generation
from port6.services.rag.base import RetrievedChunk


class _Reply:
    def __init__(self, content):
        self.content = content


class _Chain:
    """Hands back scripted replies, and records what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.asked = []

    async def ainvoke(self, params):
        self.asked.append(params["query"])
        return _Reply(self.replies.pop(0) if self.replies else "")


class _Prompt:
    def __init__(self, chain):
        self.chain = chain

    def __or__(self, other):
        return self.chain


@pytest.fixture
def sources():
    return [
        RetrievedChunk(
            number=0,
            chunk_id="c1",
            document_id="d1",
            filename="leave_policy.md",
            content="Employees accrue 22 days of paid annual leave.",
        ),
        RetrievedChunk(
            number=0,
            chunk_id="c2",
            document_id="d2",
            filename="contractor_terms.md",
            content="Contractors accrue no annual leave.",
        ),
    ]


@pytest.fixture
def answer_with(monkeypatch):
    """Run generate_answer against scripted model replies."""

    def run(replies):
        chain = _Chain(replies)

        monkeypatch.setattr(
            generation, "get_prompt", lambda name: _Prompt(chain)
        )
        monkeypatch.setattr(generation, "get_chat_model", lambda: object())

        # Conflict detection and the calculator both reach for settings and
        # the model; neither is what these tests are about.
        from port6.services.settings import service as settings_service

        monkeypatch.setattr(
            settings_service, "get_setting", lambda key: False
        )

        return chain

    return run


@pytest.mark.asyncio
async def test_an_answer_citing_nothing_is_asked_again(answer_with, sources):
    chain = answer_with([
        "**leave_policy.md** - 22 days a year.\n\n"
        "**contractor_terms.md** - none at all.",
        "**leave_policy.md** - 22 days a year [1].\n\n"
        "**contractor_terms.md** - none at all [2].",
    ])

    result = await generation.generate_answer("what does each say?", sources)

    assert len(chain.asked) == 2
    assert "[1]" in result["answer"]
    assert len(result["citations"]) == 2
    assert result["answered"] is True


@pytest.mark.asyncio
async def test_the_retry_says_where_the_marker_goes(answer_with, sources):
    """Naming the document is what the model did instead of citing it."""

    chain = answer_with([
        "**leave_policy.md** - 22 days a year.",
        "**leave_policy.md** - 22 days a year [1].",
    ])

    await generation.generate_answer("what does each say?", sources)

    nudge = chain.asked[1].lower()

    assert "square brackets" in nudge
    assert "heading" in nudge


@pytest.mark.asyncio
async def test_a_bare_retry_does_not_replace_a_readable_answer(
    answer_with,
    sources,
):
    """Two bare answers means the model will not cite this one.

    The first is kept: it reads correctly, and the alternative is either an
    invented citation or throwing away a usable answer.
    """

    chain = answer_with([
        "**leave_policy.md** - 22 days a year, carried over up to 10.",
        "22 days.",
    ])

    result = await generation.generate_answer("what does each say?", sources)

    assert len(chain.asked) == 2
    assert result["answer"].startswith("**leave_policy.md**")
    assert result["citations"] == []
    assert result["answered"] is True


@pytest.mark.asyncio
async def test_an_answer_that_already_cites_is_not_retried(
    answer_with,
    sources,
):
    chain = answer_with([
        "Employees accrue 22 days [1], contractors none [2].",
    ])

    result = await generation.generate_answer("what does each say?", sources)

    assert len(chain.asked) == 1
    assert len(result["citations"]) == 2


@pytest.mark.asyncio
async def test_not_found_is_not_treated_as_a_missing_citation(
    answer_with,
    sources,
):
    """NOT_FOUND cites nothing by design, so retrying it wastes a call."""

    chain = answer_with(["NOT_FOUND"])

    result = await generation.generate_answer("what does each say?", sources)

    assert len(chain.asked) == 1
    assert result["answered"] is False
    assert result["citations"] == []
