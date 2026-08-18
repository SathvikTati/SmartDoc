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
from port6.services.rag import smalltalk
from port6.services.rag.base import RagMode, RagResult, RetrievedChunk
from port6.services.rag.conversation import (
    REUSE,
    Resolution,
    merge_context,
    resolve,
)
from port6.services.rag.generation import generate_answer
from port6.services.settings.service import get_int, get_setting


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


def smalltalk_result(
    question: str,
    reply,
    mode: RagMode,
    started: float,
) -> RagResult:
    """A pleasantry, answered without touching the index."""

    return RagResult(
        question=question,
        answer=reply.answer,
        # Answered, because it was: there is simply nothing to cite. The
        # `kind` is what lets the UI drop the evidence panels rather than
        # showing a reader four empty ones.
        answered=True,
        citations=[],
        retrieved_chunks=[],
        retrieval_method="no retrieval: conversational message",
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        metadata={
            "mode": mode.value,
            "kind": "smalltalk",
            "smalltalk": reply.kind,
            "chunks_retrieved": 0,
        },
        debug={
            "stages": [
                {
                    "name": "smalltalk",
                    "detail": (
                        f"recognised as {reply.kind}; retrieval skipped"
                    ),
                }
            ]
        },
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

    # Before retrieval: "hello" would otherwise embed, return the five
    # least-unrelated chunks and be refused, which reads as a fault.
    reply = smalltalk.classify(question)

    if reply is not None:
        logger.info("Answering %r as %s without retrieving", question, reply.kind)
        return smalltalk_result(question, reply, resolved, started)

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


# -------------------------------------------------------------------
# Conversational queries
# -------------------------------------------------------------------

async def query_in_chat(
    question: str,
    turns: list[dict],
    previous_chunks: list[RetrievedChunk],
    mode: str | RagMode = RagMode.HYBRID,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> tuple[RagResult, Resolution]:
    """Answer a question in the context of the conversation it arrived in.

    Resolution decides what retrieval sees:

    - a new topic searches the question as written and ignores everything
      before it, which is the behaviour that keeps an unrelated question
      from inheriting the wrong documents
    - a follow-up is rewritten to stand on its own, searched on that, and
      merged with a few chunks from the previous turn
    - `reuse` answers from the previous turn's chunks without retrieving,
      for questions that are about the material rather than the subject
    """

    reply = smalltalk.classify(question)

    if reply is not None:
        logger.info("Answering %r as %s without retrieving", question, reply.kind)

        return (
            smalltalk_result(
                question,
                reply,
                resolve_mode(mode),
                time.perf_counter(),
            ),
            Resolution(
                relation="new_topic",
                strategy="fresh",
                search_question=question,
                reason=f"Conversational message ({reply.kind}).",
                method="smalltalk",
            ),
        )

    if not get_setting("conversation.enabled") or not turns:
        result = await query(
            question,
            mode=mode,
            top_k=top_k,
            document_ids=document_ids,
        )
        return result, Resolution(
            relation="new_topic",
            strategy="fresh",
            search_question=question,
            reason="Conversation resolution not applied.",
            method="disabled" if turns else "no-history",
        )

    resolution = await resolve(question, turns)

    logger.info(
        "Conversation: %s / %s (%s) -> %r",
        resolution.relation,
        resolution.strategy,
        resolution.method,
        resolution.search_question,
    )

    # "Explain that more simply" is about what was already retrieved, so
    # retrieving again would be wasted work and could drift off the thing
    # being discussed.
    if resolution.strategy == REUSE and previous_chunks:
        started = time.perf_counter()

        chunks = list(previous_chunks)

        for position, chunk in enumerate(chunks, start=1):
            chunk.number = position

        # The rewritten question, not the original: "explain that more
        # simply" gives the generator nothing to work with, and the
        # answer prompt would correctly reply NOT_FOUND.
        generated = await generate_answer(resolution.search_question, chunks)

        result = RagResult(
            question=question,
            answer=generated["answer"],
            answered=generated["answered"],
            citations=generated["citations"],
            retrieved_chunks=generated["chunks"],
            retrieval_method="reused the previous turn's sources",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            metadata={
                "mode": resolve_mode(mode).value,
                "top_k": top_k,
                "chunks_retrieved": len(chunks),
                # Reported even when the answer reads cleanly, so a figure
                # chosen over another is visible rather than implied.
                "conflicts": [
                    conflict.describe() for conflict in generated["conflicts"]
                ],
            },
            debug={
                "stages": [
                    {
                        "name": "conversation_resolution",
                        "detail": resolution.reason,
                    },
                    {
                        "name": "context_reuse",
                        "detail": (
                            "answered from the previous turn's sources; "
                            "no retrieval ran"
                        ),
                        "results": len(chunks),
                    },
                ]
            },
        )

        _attach_resolution(result, resolution)
        return result, resolution

    result = await query(
        resolution.search_question,
        mode=mode,
        top_k=top_k,
        document_ids=document_ids,
    )

    # The user asked their question, not the rewritten one.
    result.question = question

    if resolution.is_follow_up and previous_chunks:
        result.retrieved_chunks = merge_context(
            result.retrieved_chunks,
            previous_chunks,
            carry_over=get_int("conversation.carry_over_chunks"),
        )

    _attach_resolution(result, resolution)

    return result, resolution


def _attach_resolution(
    result: RagResult,
    resolution: Resolution,
) -> None:
    """Surface how the question was read, in metadata and the trace."""

    result.metadata["conversation"] = resolution.as_dict()

    stages = result.debug.setdefault("stages", [])

    detail = resolution.reason

    if resolution.standalone_question:
        detail = f"{detail} Searched as: {resolution.standalone_question!r}"

    stages.insert(
        0,
        {
            "name": "conversation_resolution",
            "detail": detail,
        },
    )
