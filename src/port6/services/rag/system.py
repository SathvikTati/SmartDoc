"""One entry point for all three retrieval modes.

    result = await query("What is the current maternity leave policy?",
                         mode="naive")

Every mode returns the same `RagResult`, which is what makes them
comparable on identical input.
"""

from __future__ import annotations

import logging
import time

from port6.services.llm.errors import classify as classify_provider_error
from port6.services.rag import agent, hybrid, naive
from port6.services.rag.base import RagMode, RagResult


logger = logging.getLogger(__name__)


RUNNERS = {
    RagMode.NAIVE: naive.run,
    RagMode.HYBRID: hybrid.run,
    RagMode.AGENTIC: agent.run,
}


def resolve_mode(
    mode: str | RagMode,
) -> RagMode:

    if isinstance(mode, RagMode):
        return mode

    try:
        return RagMode(str(mode).strip().lower())

    except ValueError:
        raise ValueError(
            f"Unknown RAG mode {mode!r}. "
            f"Choose one of: {', '.join(m.value for m in RagMode)}"
        )


async def query(
    question: str,
    mode: str | RagMode = RagMode.NAIVE,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> RagResult:
    """Answer a question, optionally restricted to specific documents.

    `document_ids` is a hard scope: retrieval cannot reach outside it in
    any mode. Passing none searches the whole library.
    """

    if not question or not question.strip():
        raise ValueError("Question cannot be empty")

    resolved = resolve_mode(mode)

    started = time.perf_counter()

    try:
        result = await RUNNERS[resolved](
            question,
            top_k=top_k,
            document_ids=document_ids,
        )

    except Exception as exc:
        # A mode failing should return a usable result, not a 500, so the
        # comparison view can still show the other modes.
        logger.exception(
            "Mode %s failed for question %r",
            resolved.value,
            question,
        )

        # An expired key or a stopped Ollama is an operator problem with an
        # obvious fix, and it looks nothing like a bad question. Say which
        # one it is rather than surfacing a raw traceback.
        provider_error = classify_provider_error(exc)

        answer = (
            provider_error.message
            if provider_error
            else f"The {resolved.value} pipeline failed: {exc}"
        )

        return RagResult(
            question=question,
            answer=answer,
            answered=False,
            retrieval_method=resolved.value,
            latency_ms=round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
            metadata={
                "mode": resolved.value,
                "error": str(exc),
                **(
                    {"provider_error": provider_error.as_dict()}
                    if provider_error
                    else {}
                ),
            },
            debug={
                "error": answer,
                **(
                    {"provider_error": provider_error.as_dict()}
                    if provider_error
                    else {}
                ),
            },
        )

    result.metadata.setdefault("mode", resolved.value)

    return result


async def compare_modes(
    question: str,
    modes: list[str | RagMode] | None = None,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> dict[str, RagResult]:
    """Run the same question through several modes for side-by-side review."""

    selected = [
        resolve_mode(mode)
        for mode in (modes or list(RagMode))
    ]

    # Sequential on purpose: a local model server handles one generation at
    # a time, so running them together only makes each one slower.
    results = {}

    for mode in selected:
        results[mode.value] = await query(
            question,
            mode=mode,
            top_k=top_k,
            document_ids=document_ids,
        )

    return results
