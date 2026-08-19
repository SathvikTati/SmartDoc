"""Fitting the sources to the model's context window.

A large `top_k` against a small window has to lose something, and the only
question is what. Left alone llama.cpp shifts the oldest tokens out of the
prompt, which is the *front* — the highest-ranked source, the one most
likely to hold the answer. The model then answers from what remained and
says nothing about the gap.

Measured on the sample library at top_k=16 against a 2048-token window:
four answers out of four, none of them correct. The same question against
8192 was correct four out of four. So the trim is done here instead, from
the bottom, and logged.
"""

from __future__ import annotations

from port6.services.rag.base import RetrievedChunk
from port6.services.rag.generation import build_context, fit_to_context


def chunk(number: int, size: int = 400) -> RetrievedChunk:
    return RetrievedChunk(
        number=number,
        chunk_id=f"c{number}",
        document_id="d1",
        filename="hr_policy.md",
        content=f"source {number}. " + ("policy text " * (size // 12)),
    )


class TestWhatSurvives:

    def test_everything_is_kept_when_it_fits(self):
        chunks = [chunk(i) for i in range(1, 5)]

        assert fit_to_context(chunks, budget_tokens=8192) == chunks

    def test_the_weakest_go_first(self):
        """Rank order is the whole point: [1] is the likeliest answer."""

        chunks = [chunk(i) for i in range(1, 21)]

        kept = fit_to_context(chunks, budget_tokens=2048)

        assert len(kept) < len(chunks)

        # The survivors are a prefix of the original ranking.
        assert kept == chunks[: len(kept)]

        # And the best-ranked source is never the one dropped.
        assert kept[0] is chunks[0]

    def test_the_result_fits_the_allowance(self):
        chunks = [chunk(i) for i in range(1, 21)]

        kept = fit_to_context(chunks, budget_tokens=2048)

        # 3.5 characters per token, less the reserve for prompt and answer.
        allowance = (2048 - 1200) * 3.5

        assert len(build_context(kept)) <= allowance

    def test_one_source_is_kept_even_if_it_cannot_fit(self):
        """Something is better than an empty context, and far better than
        a crash on a single oversized chunk."""

        kept = fit_to_context([chunk(1, size=40_000)], budget_tokens=2048)

        assert len(kept) == 1

    def test_an_empty_list_is_left_alone(self):
        assert fit_to_context([], budget_tokens=2048) == []


class TestTheBudgetTracksTheWindow:

    def test_a_larger_window_keeps_more(self):
        chunks = [chunk(i) for i in range(1, 21)]

        small = fit_to_context(chunks, budget_tokens=2048)
        large = fit_to_context(chunks, budget_tokens=8192)

        assert len(large) > len(small)

    def test_the_default_comes_from_the_configured_window(self, monkeypatch):
        """So the trim follows what the model was actually asked for,
        rather than a number repeated in two places."""

        from port6.services.rag import generation

        monkeypatch.setattr(generation, "OLLAMA_NUM_CTX", 2048)
        chunks = [chunk(i) for i in range(1, 21)]
        tight = fit_to_context(chunks)

        monkeypatch.setattr(generation, "OLLAMA_NUM_CTX", 32768)
        roomy = fit_to_context([chunk(i) for i in range(1, 21)])

        assert len(tight) < len(roomy)


def test_the_drop_is_reported(caplog):
    """A silently shorter context is how this went unnoticed in the model."""

    import logging

    chunks = [chunk(i) for i in range(1, 21)]

    with caplog.at_level(logging.WARNING):
        fit_to_context(chunks, budget_tokens=2048)

    assert "lowest-ranked" in caplog.text
