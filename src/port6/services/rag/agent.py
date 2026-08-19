"""Mode 3: Agentic RAG, as an explicit LangGraph state machine.

    retrieval_planner -> tool_execution
              ^                  |
              |                  v
              +--- (retry) -- evidence_validation
                                                |
                                                v
                                         context_builder
                                                |
                                                v
                                         answer_generation

The agent picks tools per question rather than always running the same
retrieval. If validation finds the evidence thin, it plans again with a
different strategy instead of answering anyway — bounded by the
`agent.max_attempts` setting so a question nothing can answer terminates.

Tool results are combined by rank, not by raw score: a Chroma distance is
better when lower and a BM25 score when higher, so sorting the two together
ranked keyword-only plans backwards.

Only the tools chosen and why are exposed, never the model's private
reasoning.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from port6.services.llm.service import get_chat_model
from port6.services.rag.aggregation import (
    build_grouped_context,
    group_by_document,
    is_aggregation_question,
)
from port6.services.rag.base import RagResult, RetrievedChunk
from port6.services.rag.conversation import merge_context
from port6.services.rag.generation import build_context, generate_answer
from port6.services.rag.tools import (
    TOOLS,
    available_tools,
    tool_catalogue,
)
from port6.services.rag.validation import validate_evidence
from port6.services.settings.service import get_float, get_int, get_prompt


logger = logging.getLogger(__name__)


# Reciprocal Rank Fusion constant, matching retrievers.fuse().
RRF_K = 60

RETRIEVAL_METHOD = (
    "LangGraph agent: plans and executes retrieval tools, "
    "validates evidence, retries with a different strategy"
)


def _keep_last(current, incoming):
    return incoming


class AgentState(TypedDict, total=False):
    query: str
    top_k: int
    document_ids: list[str]

    selected_tools: Annotated[list[str], _keep_last]
    plan_reason: Annotated[str, _keep_last]
    tool_runs: Annotated[list[dict], _keep_last]

    retrieved_chunks: Annotated[list[RetrievedChunk], _keep_last]
    retrieval_metadata: Annotated[dict, _keep_last]

    validation_result: Annotated[dict, _keep_last]
    attempts: Annotated[int, _keep_last]

    # True once a coverage tool has run, which changes how the context is
    # trimmed and how the answer is asked for.
    aggregated: Annotated[bool, _keep_last]

    # True once the web has been tried, so the fallback below runs once.
    web_attempted: Annotated[bool, _keep_last]

    # Chunks from the previous turn of a conversation, handed in rather
    # than retrieved. No node writes this, so `_keep_last` preserves it
    # across every attempt and the web fallback.
    carried_chunks: Annotated[list[RetrievedChunk], _keep_last]

    final_context: Annotated[list[RetrievedChunk], _keep_last]

    # Documents that gave different figures for the same thing, already
    # resolved by upload recency. Surfaced so the answer is not the only
    # place the disagreement is visible.
    conflicts: Annotated[list[str], _keep_last]

    # Set from the pipeline. `use_planner` false chooses tools by rule
    # instead of spending a model call on it; `max_attempts` bounds the
    # retry loop, so a variant can be a deliberate single pass.
    use_planner: bool
    max_attempts: int

    # The composition's tool allow-list. Turning the agent on must not
    # quietly widen what is searched, or a with-agent against
    # without-agent comparison would be varying two things.
    allowed_tools: tuple
    answer: Annotated[str, _keep_last]
    answered: Annotated[bool, _keep_last]
    citations: Annotated[list[RetrievedChunk], _keep_last]

    stages: Annotated[list[dict], _keep_last]


def rule_based_plan(
    attempt: int,
    query: str = "",
    web_pending: bool = False,
    allowed: tuple[str, ...] | None = None,
) -> tuple[list[str], str]:
    """Deterministic fallback, and the retry strategy.

    Used when the planner model is unavailable or returns unusable output,
    and always for the second attempt, where the goal is deliberately to
    widen rather than to re-plan.

    Every choice below is filtered through the composition's allow-list:
    the rules name the tools they would *like*, and `_permitted` keeps
    only the ones this composition actually has. A keyword-only
    composition cannot be handed `hybrid_search` by a rule any more than
    by the planner.
    """

    offered = list(available_tools(allowed))

    def _permitted(preferred: list[str]) -> list[str]:
        kept = [name for name in preferred if name in offered]

        # Nothing preferred survived — fall back to whatever retrieval
        # this composition does have, rather than planning nothing.
        return kept or [
            name for name in offered if name.endswith("_search")
        ][:2] or offered[:1]

    # A library-wide question needs breadth on every attempt. Widening to
    # a depth-ranked hybrid sweep would replace the per-document coverage
    # with the best chunks overall — the exact failure aggregation exists
    # to prevent.
    if is_aggregation_question(query):
        return (
            _permitted(["aggregate_search"]),
            "Question is about the library as a whole; covering each "
            "matching document.",
        )

    if attempt > 0:
        # The first attempt did not find enough; cast wider.
        #
        # This is also the only place web search is reached by rule. Its
        # description says "use only when the documents cannot answer",
        # and the planner decides *before* retrieval runs, so it cannot
        # know that. A failed attempt is the evidence — reaching outside
        # the library becomes a consequence of the documents coming up
        # short rather than a guess made up front.
        widened = ["hybrid_search", "keyword_search"]

        if "web_search" in available_tools(allowed) and web_pending:
            widened = ["web_search", "hybrid_search"]

            return (
                _permitted(widened),
                "The documents did not answer this; widening the search "
                "and checking the web.",
            )

        return (
            _permitted(widened),
            "First attempt found thin evidence; widening to a "
            "full hybrid sweep.",
        )

    return (
        _permitted(["hybrid_search", "hierarchical_search"]),
        "General question: hybrid retrieval with hierarchical narrowing.",
    )


async def plan_with_model(
    query: str,
    previous: str,
    allowed: tuple[str, ...] | None = None,
) -> tuple[list[str], str] | None:

    try:
        chain = get_prompt("retrieval_planner") | get_chat_model()

        response = await chain.ainvoke(
            {
                "catalogue": tool_catalogue(allowed),
                "query": query,
                "previous": previous or "none",
            }
        )

        content = response.content

        if not isinstance(content, str):
            content = str(content)

        content = content.strip()

        if content.startswith("```"):
            content = content.strip("`")
            content = content.split("\n", 1)[-1] if "\n" in content else content

        start = content.find("{")
        end = content.rfind("}")

        if start == -1 or end <= start:
            return None

        parsed = json.loads(content[start : end + 1])

        offered = available_tools(allowed)

        tools = [
            name
            for name in parsed.get("tools", [])
            if name in offered
        ]

        if not tools:
            return None

        return tools[:3], str(parsed.get("reason", "")).strip()

    except Exception as exc:
        logger.warning("Planner model failed: %s", exc)
        return None


# -------------------------------------------------------------------
# Nodes
# -------------------------------------------------------------------

async def node_retrieval_planner(state: AgentState) -> dict:

    attempt = state.get("attempts", 0)

    previous = ""

    if attempt > 0:
        validation = state.get("validation_result") or {}
        previous = (
            f"tools {state.get('selected_tools')} gave insufficient "
            f"evidence ({validation.get('reason', '')})"
        )

    plan = None

    # The retry is a deliberate widening, so it skips the model.
    #
    # `attempts` alone identifies the first pass: tool_execution
    # increments it, so any re-entry — including the web fallback — sees
    # a non-zero value. Testing `answered` here instead was a bug:
    # LangGraph initialises the bool channel to False, so the check never
    # passed and every question silently used the rule-based plan.
    if attempt == 0 and state.get("use_planner", True):
        plan = await plan_with_model(
            state["query"],
            previous,
            allowed=state.get("allowed_tools"),
        )

    if plan is None:
        tools, reason = rule_based_plan(
            attempt,
            state["query"],
            # True only once generation has actually run and reported
            # that the documents do not contain the answer. `answer`
            # being set is what distinguishes that from the channel's
            # initial value.
            web_pending=(
                bool(state.get("answer"))
                and state.get("answered") is False
                and not state.get("web_attempted")
            ),
            allowed=state.get("allowed_tools"),
        )
        source = "rules"

    else:
        tools, reason = plan
        source = "model"

    logger.info(
        "Attempt %d planned tools %s (%s)",
        attempt + 1,
        tools,
        source,
    )

    return {
        "selected_tools": tools,
        "plan_reason": reason,
        "attempts": attempt,
        "stages": [
            *state.get("stages", []),
            {
                "name": "retrieval_planner",
                "detail": f"{reason} (planned by {source})",
                "tools": tools,
                "attempt": attempt + 1,
            },
        ],
    }


async def node_tool_execution(state: AgentState) -> dict:

    top_k = state.get("top_k", 5)

    collected: list[RetrievedChunk] = []
    runs: list[dict] = []
    metadata: dict = dict(state.get("retrieval_metadata") or {})

    # chunk id -> [(tool, rank within that tool's results)]
    tool_ranks: dict[str, list[tuple[str, int]]] = {}

    aggregated = bool(state.get("aggregated"))
    web_attempted = bool(state.get("web_attempted"))

    for name in state["selected_tools"]:

        tool = TOOLS.get(name)

        if tool is None:
            continue

        try:
            # ainvoke rather than calling the function: the @tool wrapper
            # validates the arguments against its generated schema.
            outcome = await tool.ainvoke(
                {
                    "query": state["query"],
                    "top_k": max(top_k * 2, 8),
                    "document_ids": state.get("document_ids") or None,
                }
            )

        except Exception as exc:
            # One failing tool must not sink the whole query.
            logger.warning("Tool %s failed: %s", name, exc)
            runs.append({"tool": name, "error": str(exc)})
            continue

        chunks = outcome.get("chunks") or []

        # Each tool returns its own best-first ordering, so a chunk's
        # position within one tool's results is meaningful. Its raw score
        # is not comparable across tools — a Chroma distance is better when
        # lower, a BM25 score when higher — so rank is what gets fused.
        for rank, chunk in enumerate(chunks, start=1):
            tool_ranks.setdefault(chunk.chunk_id, []).append((name, rank))

        collected.extend(chunks)

        runs.append(
            {
                "tool": name,
                "chunks": len(chunks),
                "info": outcome.get("info") or {},
            }
        )

        if (outcome.get("info") or {}).get("aggregated"):
            aggregated = True

        if name == "web_search":
            web_attempted = True

        for key, value in (outcome.get("info") or {}).items():
            metadata.setdefault(key, value)

    # Keep one copy of any chunk several tools found, merging what each
    # one knew about it.
    unique: dict[str, RetrievedChunk] = {}

    for chunk in collected:

        existing = unique.get(chunk.chunk_id)

        if existing is None:
            unique[chunk.chunk_id] = chunk
            continue

        for source in chunk.sources:
            if source not in existing.sources:
                existing.sources.append(source)

        if existing.semantic_rank is None:
            existing.semantic_rank = chunk.semantic_rank

        if existing.keyword_rank is None:
            existing.keyword_rank = chunk.keyword_rank

    # Fuse by rank, not by raw score.
    #
    # Sorting these by `score` was a real bug: a Chroma distance is better
    # when lower and a BM25 score when higher, so a keyword-only plan was
    # ranked backwards and the agent answered from the *worst* matches it
    # had found. RRF over each tool's own ordering is comparable.
    for chunk_id, ranks in tool_ranks.items():

        chunk = unique.get(chunk_id)

        if chunk is None:
            continue

        chunk.fused_score = round(
            sum(1.0 / (RRF_K + rank) for _, rank in ranks),
            6,
        )

    chunks = list(unique.values())

    return {
        "retrieved_chunks": chunks,
        "aggregated": aggregated,
        "web_attempted": web_attempted,
        "tool_runs": [
            *(state.get("tool_runs") or []),
            *runs,
        ],
        "retrieval_metadata": metadata,
        "attempts": state.get("attempts", 0) + 1,
        "stages": [
            *state.get("stages", []),
            {
                "name": "tool_execution",
                "detail": (
                    f"ran {len(runs)} tool(s), "
                    f"{len(chunks)} unique chunks"
                ),
                "results": len(chunks),
            },
        ],
    }


async def node_evidence_validation(state: AgentState) -> dict:

    result = await validate_evidence(
        state["query"],
        state.get("retrieved_chunks") or [],
    )

    logger.info(
        "Evidence validation: %s (%s)",
        result.sufficient,
        result.reason,
    )

    return {
        "validation_result": result.as_dict(),
        "stages": [
            *state.get("stages", []),
            {
                "name": "evidence_validation",
                "detail": result.reason,
                "sufficient": result.sufficient,
            },
        ],
    }


def route_after_validation(state: AgentState) -> str:

    validation = state.get("validation_result") or {}

    if validation.get("sufficient"):
        return "context_builder"

    limit = state.get("max_attempts") or get_int("agent.max_attempts")

    if state.get("attempts", 0) >= limit:
        # Out of retries: go on to answer, where insufficient evidence
        # becomes an honest "not found" rather than a guess.
        return "context_builder"

    return "retrieval_planner"


async def node_context_builder(state: AgentState) -> dict:

    chunks = list(state.get("retrieved_chunks") or [])

    top_k = state.get("top_k", 5)

    # Coverage is the point of an aggregation answer, and a flat top_k cut
    # destroys it: eight chunks spanning four documents were being trimmed
    # to the five best, which collapsed back to two documents. Trim per
    # document instead, so breadth survives the context builder.
    if state.get("aggregated"):
        ordered = group_by_document(
            chunks,
            chunks_per_document=get_int("aggregation.chunks_per_document"),
            max_documents=get_int("aggregation.max_documents"),
            # Spread the requested budget across documents rather than
            # ignoring it: coverage decides the shape, top_k the size.
            budget=top_k,
        )["chunks"]

        ordered = merge_context(ordered, state.get("carried_chunks") or [])

        for position, chunk in enumerate(ordered, start=1):
            chunk.number = position

        return {
            "final_context": ordered,
            "stages": [
                *state.get("stages", []),
                {
                    "name": "context_builder",
                    "detail": (
                        f"kept {len(ordered)} of {len(chunks)} chunks, "
                        f"covering "
                        f"{len({c.document_id for c in ordered})} document(s)"
                    ),
                    "results": len(ordered),
                },
            ],
        }

    def sort_key(chunk: RetrievedChunk):
        # Fused rank first — it is the only figure comparable across tools.
        # Agreement between tools breaks ties, and the raw score is a last
        # resort for anything that arrived without a rank.
        return (
            -(chunk.fused_score or 0.0),
            -len(chunk.sources),
            chunk.score if chunk.score is not None else 1e9,
        )

    # After the trim, not before: carried chunks arrive without a fused
    # rank, so they sort last and `[:top_k]` would discard exactly the
    # context the follow-up was given them for.
    ordered = merge_context(
        sorted(chunks, key=sort_key)[:top_k],
        state.get("carried_chunks") or [],
    )

    for position, chunk in enumerate(ordered, start=1):
        chunk.number = position

    return {
        "final_context": ordered,
        "stages": [
            *state.get("stages", []),
            {
                "name": "context_builder",
                "detail": f"kept {len(ordered)} of {len(chunks)} chunks",
                "results": len(ordered),
            },
        ],
    }


async def node_answer_generation(state: AgentState) -> dict:

    chunks = state.get("final_context") or []

    validation = state.get("validation_result") or {}

    # Evidence was judged thin and the retries are spent: say so instead of
    # generating a confident answer from weak sources.
    if not validation.get("sufficient") and not chunks:
        return {
            "answer": (
                "I could not find enough supporting evidence in the "
                "document library to answer that question."
            ),
            "answered": False,
            "citations": [],
            "stages": [
                *state.get("stages", []),
                {
                    "name": "answer_generation",
                    "detail": "declined: insufficient evidence",
                },
            ],
        }

    aggregated = bool(state.get("aggregated"))
    web_attempted = bool(state.get("web_attempted"))

    result = await generate_answer(
        state["query"],
        chunks,
        # Same guards either way; only the instruction and how the sources
        # are laid out change.
        prompt_name="aggregate_answer" if aggregated else "answer_generation",
        context_builder=build_grouped_context if aggregated else build_context,
    )

    return {
        "answer": result["answer"],
        "answered": result["answered"],
        "citations": result["citations"],
        # Generation may have added a worked sum to the sources, so the
        # trace reports what the answer actually saw rather than what
        # retrieval handed over.
        "final_context": result["chunks"],
        "conflicts": [
            conflict.describe() for conflict in result["conflicts"]
        ],
        "stages": [
            *state.get("stages", []),
            {
                "name": "answer_generation",
                "detail": (
                    f"{len(result['citations'])} citations"
                    if result["answered"]
                    else "no answer found in sources"
                ),
            },
        ],
    }


# -------------------------------------------------------------------
# Graph
# -------------------------------------------------------------------

def route_after_answer(state: AgentState) -> str:
    """Try the web only once the documents have demonstrably failed.

    Evidence validation cannot make this call: it is lexical, and a
    question like "what is the UK statutory maternity entitlement?" shares
    every key term with an HR policy that does not contain the figure. It
    scores 100% and passes.

    The generator is the one that knows. `answered: false` means it read
    the sources and the answer was not in them — which is exactly the
    condition `web_search` is documented for, and the only honest trigger
    for reaching outside the library.
    """

    if state.get("answered"):
        return END

    if state.get("web_attempted"):
        return END

    if "web_search" not in available_tools(state.get("allowed_tools")):
        return END

    if not library_is_on_topic(state):
        logger.info(
            "Nothing in the library is close to %r; not reaching the web",
            state.get("query"),
        )
        return END

    logger.info("Documents did not answer; falling back to the web")

    return "retrieval_planner"


def library_is_on_topic(state) -> bool:
    """Whether anything in the library is even about this question.

    Retrieval always returns its nearest neighbours, so "found five
    chunks" says nothing about whether the subject exists in the library
    at all. Distance does: on the sample library, real questions put the
    nearest document at 0.86-0.89, while "what is python" sits at 1.26 and
    "what is redis" at 1.13.

    This is what separates a gap from a non-subject. "UK statutory
    maternity leave" is a gap — the library is full of leave policy and
    simply lacks that figure, so the web supplements it. "What is python"
    is not a gap; nothing in the library is remotely about it, and
    answering from the web would quietly turn a document assistant into a
    search engine.
    """

    chunks = state.get("final_context") or []

    # Only chunks semantic search actually found. `score` is whatever the
    # retriever that produced it puts there, and a keyword-only chunk
    # carries a BM25 score — 0.78 to 3.4 on this library, against semantic
    # distances of 1.14 to 1.24. Reading both as one number let a BM25
    # 0.861 pass as a near match and sent "what is kubernetes" to the web.
    #
    # A web chunk is excluded for the same reason it sounds wrong: on a
    # second pass its own results must not vouch for the library.
    distances = [
        chunk.score
        for chunk in chunks
        if chunk.score is not None
        and chunk.semantic_rank is not None
        and not chunk.is_web
    ]

    if not distances:
        return False

    return min(distances) <= get_float("web.max_topic_distance")


def build_graph():

    graph = StateGraph(AgentState)

    graph.add_node("retrieval_planner", node_retrieval_planner)
    graph.add_node("tool_execution", node_tool_execution)
    graph.add_node("evidence_validation", node_evidence_validation)
    graph.add_node("context_builder", node_context_builder)
    graph.add_node("answer_generation", node_answer_generation)

    graph.add_edge(START, "retrieval_planner")
    graph.add_edge("retrieval_planner", "tool_execution")
    graph.add_edge("tool_execution", "evidence_validation")

    graph.add_conditional_edges(
        "evidence_validation",
        route_after_validation,
        {
            "retrieval_planner": "retrieval_planner",
            "context_builder": "context_builder",
        },
    )

    graph.add_edge("context_builder", "answer_generation")

    graph.add_conditional_edges(
        "answer_generation",
        route_after_answer,
        {
            "retrieval_planner": "retrieval_planner",
            END: END,
        },
    )

    return graph.compile()


_graph = None


def get_graph():
    global _graph

    if _graph is None:
        _graph = build_graph()

    return _graph


async def run(
    question: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
    composition=None,
    carried: list[RetrievedChunk] | None = None,
) -> RagResult:

    started = time.perf_counter()

    # Called directly — and by every existing test — without one, which
    # means the full agent over every retriever: the behaviour this graph
    # had before compositions existed.
    if composition is None:
        from port6.services.rag.pipelines import PRESETS

        composition = PRESETS["agentic"]

    final = await get_graph().ainvoke(
        {
            "query": question,
            "top_k": top_k,
            "document_ids": document_ids or [],
            "use_planner": composition.planner,
            "max_attempts": get_int("agent.max_attempts")
            if composition.planner
            else 1,
            "allowed_tools": composition.allowed_tools,
            "carried_chunks": carried or [],
        }
    )

    tools_used = [
        run_record["tool"]
        for run_record in (final.get("tool_runs") or [])
    ]

    return RagResult(
        question=question,
        answer=final.get("answer", ""),
        answered=final.get("answered", False),
        citations=final.get("citations") or [],
        retrieved_chunks=final.get("final_context") or [],
        retrieval_method=composition.method or RETRIEVAL_METHOD,
        latency_ms=round(
            (time.perf_counter() - started) * 1000,
            2,
        ),
        metadata={
            "mode": "agentic",
            "pipeline": composition.id,
            "pipeline_label": composition.label,
            "retrievers": list(composition.ordered),
            "agent": True,
            "allowed_tools": list(composition.allowed_tools),
            "top_k": top_k,
            "tools_used": tools_used,
            "attempts": final.get("attempts", 0),
            "validation": final.get("validation_result"),
            "chunks_retrieved": len(final.get("final_context") or []),
            "conflicts": final.get("conflicts") or [],
            "scoped_to_documents": len(document_ids) if document_ids else 0,
        },
        debug={
            "plan_reason": final.get("plan_reason"),
            "tools_used": tools_used,
            "tool_runs": final.get("tool_runs") or [],
            "validation_result": final.get("validation_result"),
            "stages": final.get("stages") or [],
            "retrieval_metadata": final.get("retrieval_metadata") or {},
        },
    )
