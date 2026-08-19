"""One entry point for all three retrieval modes.

    result = await query("What is the current maternity leave policy?",
                         mode="naive")

Every mode returns the same `RagResult`, which is what makes them
comparable on identical input.
"""

from __future__ import annotations

import logging
import time

from port6.services.cache import service as answer_cache
from port6.services.embeddings.service import get_embeddings
from port6.services.llm.errors import classify as classify_provider_error
from port6.services.rag import pipelines, smalltalk
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


# A web answer expires sooner than a library answer. Clearing the cache on
# document changes cannot cover the public internet, so time is the only
# guard there is on a result that came off it.
WEB_CACHE_TTL_SECONDS = 3600


async def _embed_for_cache(question: str):
    """The question as a vector, or None if it cannot be had.

    Best-effort: the similarity tier is an optimisation, and an embedding
    call that fails should cost the lookup, not the answer.
    """

    try:
        return await get_embeddings().aembed_query(
            answer_cache.normalise(question)
        )

    except Exception as exc:
        logger.warning(
            "Could not embed %r for the cache: %s",
            question,
            exc,
        )
        return None


async def _cache_lookup(question: str, scope: str):
    """`(cached result or None, embedding or None)`.

    The exact tier is tried first precisely so a repeat question costs one
    `GET` and no embedding call. The embedding is handed back on a miss so
    that storing the answer afterwards does not compute it a second time.
    """

    exact = await answer_cache.lookup_exact(question, scope)

    if exact is not None:
        return exact, None

    embedding = await _embed_for_cache(question)

    if embedding is None:
        return None, None

    return await answer_cache.lookup_similar(embedding, scope), embedding


def _cache_ttl(result: RagResult) -> int:

    ttl = get_int("cache.ttl_seconds")

    if "web_search" in (result.metadata.get("tools_used") or []):
        return min(ttl, WEB_CACHE_TTL_SECONDS)

    return ttl


async def query(
    question: str,
    mode: str | RagMode = RagMode.NAIVE,
    top_k: int = 5,
    document_ids: list[str] | None = None,
    composition=None,
) -> RagResult:
    """Answer a question, optionally restricted to specific documents.

    `document_ids` is a hard scope: retrieval cannot reach outside it in
    any pipeline. Passing none searches the whole library.

    `composition` is what actually answers: which retrievers run, and
    whether an agent sits on them. `mode` is the coarser control a chat
    uses, and still works — it maps to the composition reproducing what
    that mode used to do.
    """

    if not question or not question.strip():
        raise ValueError("Question cannot be empty")

    selected = composition or pipelines.resolve(mode=mode)

    resolved = selected.family

    started = time.perf_counter()

    # Before retrieval: "hello" would otherwise embed, return the five
    # least-unrelated chunks and be refused, which reads as a fault.
    reply = smalltalk.classify(question)

    if reply is not None:
        logger.info("Answering %r as %s without retrieving", question, reply.kind)
        return smalltalk_result(question, reply, resolved, started)

    # Below smalltalk on purpose: a greeting never retrieved anything, so
    # there is nothing about it worth keeping.
    scope = answer_cache.scope_digest(selected.id, top_k, document_ids)

    caching = answer_cache.enabled()
    embedding = None

    if caching:
        cached, embedding = await _cache_lookup(question, scope)

        if cached is not None:
            # The stored latency belongs to the run that produced the
            # answer, not to this lookup. Reporting it unchanged made a
            # cache hit claim the 27 seconds it had just avoided; the
            # original figure is kept under `cache.original_latency_ms`,
            # which is where it is a saving rather than a lie.
            cached.latency_ms = round(
                (time.perf_counter() - started) * 1000,
                2,
            )

            logger.info(
                "Answered %r from cache (%s hit) in %.1fms",
                question,
                cached.metadata["cache"]["hit"],
                cached.latency_ms,
            )
            return cached

    try:
        result = await pipelines.run(
            selected,
            question,
            top_k=top_k,
            document_ids=document_ids,
        )

    except Exception as exc:
        # A mode failing should return a usable result, not a 500, so the
        # comparison view can still show the other modes.
        logger.exception(
            "Pipeline %s failed for question %r",
            selected.id,
            question,
        )

        # An expired key or a stopped Ollama is an operator problem with an
        # obvious fix, and it looks nothing like a bad question. Say which
        # one it is rather than surfacing a raw traceback.
        provider_error = classify_provider_error(exc)

        answer = (
            provider_error.message
            if provider_error
            else f"The {selected.label} pipeline failed: {exc}"
        )

        return RagResult(
            question=question,
            answer=answer,
            answered=False,
            retrieval_method=selected.method or selected.label,
            latency_ms=round(
                (time.perf_counter() - started) * 1000,
                2,
            ),
            metadata={
                "mode": resolved.value,
                "pipeline": selected.id,
                "pipeline_label": selected.label,
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
    result.metadata.setdefault("pipeline", selected.id)
    result.metadata.setdefault("pipeline_label", selected.label)

    # Only here, never on the failure path above: a stopped Ollama or an
    # expired key is a passing condition, and caching its message would
    # keep serving it after the fix. "No answer in the library" is stored,
    # though — that is a real finding, and uploading the missing document
    # clears the cache anyway.
    if caching:
        await answer_cache.store(
            question,
            scope,
            result,
            embedding=embedding,
            ttl_seconds=_cache_ttl(result),
        )

    return result


async def compare_modes(
    question: str,
    modes: list[str | RagMode] | None = None,
    top_k: int = 5,
    document_ids: list[str] | None = None,
    compositions: list | None = None,
) -> dict[str, RagResult]:
    """Run one question through several strategies, side by side.

    Keyed by pipeline id when pipelines are named, and by mode otherwise,
    so the existing three-mode comparison keeps the shape it had.
    """

    if compositions:
        chosen = list(compositions)

    else:
        chosen = [
            pipelines.MODE_DEFAULTS[resolve_mode(mode)]
            for mode in (modes or list(RagMode))
        ]

    # Sequential on purpose: a local model server handles one generation at
    # a time, so running them together only makes each one slower.
    results = {}

    for one in chosen:

        key = one.id if compositions else one.family.value

        results[key] = await query(
            question,
            top_k=top_k,
            document_ids=document_ids,
            composition=one,
        )

    return results


# -------------------------------------------------------------------
# Conversational queries
# -------------------------------------------------------------------

async def query_in_chat(
    question: str,
    turns: list[dict],
    previous_chunks: list[RetrievedChunk],
    mode: str | RagMode | None = None,
    top_k: int = 5,
    document_ids: list[str] | None = None,
    composition=None,
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
                resolve_mode(mode or RagMode.HYBRID),
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
            composition=composition,
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
        composition=composition,
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
