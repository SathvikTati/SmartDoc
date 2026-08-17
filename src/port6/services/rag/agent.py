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
from port6.services.rag.base import RagResult, RetrievedChunk
from port6.services.rag.generation import generate_answer
from port6.services.rag.tools import TOOLS, tool_catalogue
from port6.services.rag.validation import validate_evidence
from port6.services.settings.service import get_int, get_prompt


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

    final_context: Annotated[list[RetrievedChunk], _keep_last]
    answer: Annotated[str, _keep_last]
    answered: Annotated[bool, _keep_last]
    citations: Annotated[list[RetrievedChunk], _keep_last]

    stages: Annotated[list[dict], _keep_last]


def rule_based_plan(
    attempt: int,
) -> tuple[list[str], str]:
    """Deterministic fallback, and the retry strategy.

    Used when the planner model is unavailable or returns unusable output,
    and always for the second attempt, where the goal is deliberately to
    widen rather than to re-plan.
    """

    if attempt > 0:
        # The first attempt did not find enough; cast wider.
        return (
            ["hybrid_search", "keyword_search"],
            "First attempt found thin evidence; widening to a "
            "full hybrid sweep.",
        )

    return (
        ["hybrid_search", "hierarchical_search"],
        "General question: hybrid retrieval with hierarchical narrowing.",
    )


async def plan_with_model(
    query: str,
    previous: str,
) -> tuple[list[str], str] | None:

    try:
        chain = get_prompt("retrieval_planner") | get_chat_model()

        response = await chain.ainvoke(
            {
                "catalogue": tool_catalogue(),
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

        tools = [
            name
            for name in parsed.get("tools", [])
            if name in TOOLS
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
    if attempt == 0:
        plan = await plan_with_model(
            state["query"],
            previous,
        )

    if plan is None:
        tools, reason = rule_based_plan(attempt)
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

    for name in state["selected_tools"]:

        tool = TOOLS.get(name)

        if tool is None:
            continue

        try:
            outcome = await tool.run(
                query=state["query"],
                top_k=max(top_k * 2, 8),
                document_ids=state.get("document_ids") or None,
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

    if state.get("attempts", 0) >= get_int("agent.max_attempts"):
        # Out of retries: go on to answer, where insufficient evidence
        # becomes an honest "not found" rather than a guess.
        return "context_builder"

    return "retrieval_planner"


async def node_context_builder(state: AgentState) -> dict:

    chunks = list(state.get("retrieved_chunks") or [])

    top_k = state.get("top_k", 5)

    def sort_key(chunk: RetrievedChunk):
        # Fused rank first — it is the only figure comparable across tools.
        # Agreement between tools breaks ties, and the raw score is a last
        # resort for anything that arrived without a rank.
        return (
            -(chunk.fused_score or 0.0),
            -len(chunk.sources),
            chunk.score if chunk.score is not None else 1e9,
        )

    ordered = sorted(chunks, key=sort_key)[:top_k]

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

    result = await generate_answer(state["query"], chunks)

    return {
        "answer": result["answer"],
        "answered": result["answered"],
        "citations": result["citations"],
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
    graph.add_edge("answer_generation", END)

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
) -> RagResult:

    started = time.perf_counter()

    final = await get_graph().ainvoke(
        {
            "query": question,
            "top_k": top_k,
            "document_ids": document_ids or [],
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
        retrieval_method=RETRIEVAL_METHOD,
        latency_ms=round(
            (time.perf_counter() - started) * 1000,
            2,
        ),
        metadata={
            "mode": "agentic",
            "top_k": top_k,
            "tools_used": tools_used,
            "attempts": final.get("attempts", 0),
            "validation": final.get("validation_result"),
            "chunks_retrieved": len(final.get("final_context") or []),
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
