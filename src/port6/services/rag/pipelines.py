"""How a question is answered: a composition, not a fixed pipeline.

There is one pipeline. What varies is what you put in it — which
retrievers run, whether an agent sits on top of them, and which tools
that agent may reach for.

This started as a registry of seven named pipelines, which was the wrong
shape. Seven names is an arbitrary sample of a space you should be able
to move around in: three retrievers combine seven ways, and the agent and
its tools multiply that again. Naming a handful of the combinations makes
the rest unreachable and implies the named ones are special. They are not.

So a `Composition` is the unit. Presets exist, but only as shortcuts that
fill one in — the way a colour picker has swatches without those being
the only colours.

**The agent is a layer, not an alternative.** With it off, the chosen
retrievers run once and their results are fused. With it on, the same
retrievers become the tools it may plan over, and it adds tool selection,
evidence validation and a retry. That is what makes "what does the agent
buy me?" answerable: hold retrieval constant and toggle one flag.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from port6.services.rag.aggregation import (
    build_grouped_context,
    coverage_search,
    is_aggregation_question,
)
from port6.services.rag.base import RagMode, RagResult, RetrievedChunk
from port6.services.rag.generation import generate_answer
from port6.services.rag.hierarchical import hierarchical_search
from port6.services.rag.retrievers import (
    fuse,
    keyword_search,
    semantic_search,
)
from port6.services.settings.service import get_setting


logger = logging.getLogger(__name__)


SEMANTIC = "semantic"
KEYWORD = "keyword"
HIERARCHICAL = "hierarchical"

RETRIEVERS: dict[str, dict] = {
    SEMANTIC: {
        "id": SEMANTIC,
        "label": "Semantic",
        "description": (
            "Embedding similarity. Finds a paraphrase that shares no "
            "words with the document, and misses an exact code that has "
            "no useful neighbourhood."
        ),
    },
    KEYWORD: {
        "id": KEYWORD,
        "label": "Keyword",
        "description": (
            "BM25. Finds codes, names and rare words exactly, and misses "
            "a question phrased in different vocabulary."
        ),
    },
    HIERARCHICAL: {
        "id": HIERARCHICAL,
        "label": "Hierarchical",
        "description": (
            "Narrows document, then section, then chunk. Sharper inside a "
            "long structured document; useless if the right document does "
            "not rank first."
        ),
    },
}

# The agent tool each retriever unlocks.
_TOOL_FOR = {
    SEMANTIC: "semantic_search",
    KEYWORD: "keyword_search",
    HIERARCHICAL: "hierarchical_search",
}

# Tools that are not a retriever, so they are not implied by the
# composition's retrievers and have to be asked for. `web_search` is
# additionally gated by its own setting, which stays authoritative —
# selecting it here cannot switch the web on.
EXTRA_TOOLS: dict[str, dict] = {
    "document_lookup": {
        "id": "document_lookup",
        "label": "Document lookup",
        "description": "Lists what is in the library. For \"what do we have?\".",
    },
    "calculate": {
        "id": "calculate",
        "label": "Calculator",
        "description": (
            "Arithmetic the answer depends on. Runs after retrieval "
            "regardless; selecting it lets the agent ask for it too."
        ),
    },
    "web_search": {
        "id": "web_search",
        "label": "Web search",
        "description": (
            "The public internet, when the library cannot answer. Also "
            "requires web.enabled — this cannot switch it on."
        ),
    },
}


class InvalidComposition(ValueError):
    """A composition that would retrieve nothing, or from nowhere."""


@dataclass(frozen=True)
class Composition:
    """One way of answering: some retrievers, optionally an agent."""

    retrievers: tuple[str, ...]
    agent: bool = False

    # Only meaningful with the agent on. Off means tools are chosen by
    # rule and there is no retry — the cheap end of the agent.
    planner: bool = True

    # Extra tools the agent may reach for, beyond the ones its retrievers
    # already imply. Empty is a real answer: retrieval only.
    extra_tools: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.retrievers:
            raise InvalidComposition(
                "Choose at least one retriever; there is nothing to "
                "search with otherwise."
            )

        unknown = set(self.retrievers) - set(RETRIEVERS)

        if unknown:
            raise InvalidComposition(
                f"Unknown retriever(s): {', '.join(sorted(unknown))}"
            )

        stray = set(self.extra_tools) - set(EXTRA_TOOLS)

        if stray:
            raise InvalidComposition(
                f"Unknown tool(s): {', '.join(sorted(stray))}. "
                "Retrieval tools come from the retrievers, not from here."
            )

    @property
    def ordered(self) -> tuple[str, ...]:
        """Canonical order, so two equivalent compositions share an id."""

        return tuple(
            name
            for name in (SEMANTIC, KEYWORD, HIERARCHICAL)
            if name in self.retrievers
        )

    @property
    def ordered_tools(self) -> tuple[str, ...]:
        return tuple(name for name in EXTRA_TOOLS if name in self.extra_tools)

    @property
    def id(self) -> str:
        """A stable slug, recorded on the query run — so a stored answer
        says exactly what produced it."""

        base = "+".join(self.ordered)

        if not self.agent:
            return base

        prefix = "agent" if self.planner else "agent-direct"

        if self.ordered_tools:
            return f"{prefix}[{','.join(self.ordered_tools)}]:{base}"

        return f"{prefix}:{base}"

    @property
    def label(self) -> str:
        names = " + ".join(RETRIEVERS[name]["label"] for name in self.ordered)

        if not self.agent:
            return names

        return (
            f"Agent · {names}" if self.planner else f"Agent (direct) · {names}"
        )

    @property
    def family(self) -> RagMode:
        """The coarse mode this counts as, for history and older clients."""

        if self.agent:
            return RagMode.AGENTIC

        return RagMode.NAIVE if len(self.ordered) == 1 else RagMode.HYBRID

    @property
    def method(self) -> str:
        """How the retrieval reads in the trace."""

        if len(self.ordered) == 1:
            base = {
                SEMANTIC: "semantic vector search (top-k)",
                KEYWORD: "BM25 keyword search (top-k)",
                HIERARCHICAL: "hierarchical document -> section -> chunk",
            }[self.ordered[0]]

        else:
            base = " + ".join(self.ordered) + ", RRF fused"

        if not self.agent:
            return base

        if self.planner:
            return (
                f"LangGraph agent over {base}: plans tools, validates "
                "evidence, retries once if thin"
            )

        return f"LangGraph agent over {base}: rule-chosen tools, single pass"

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        """Exactly what the planner may choose from.

        The retrieval tools come from the retrievers, so turning the agent
        on cannot quietly widen what is searched — that is what makes a
        with-agent and without-agent comparison hold retrieval constant.
        Everything else has to be selected.
        """

        tools = [_TOOL_FOR[name] for name in self.ordered]

        # Only offer the fused tool when both halves are in the
        # composition; otherwise it reaches a retriever left out on
        # purpose.
        if SEMANTIC in self.ordered and KEYWORD in self.ordered:
            tools.append("hybrid_search")

        # Coverage is how any composition answers a library-wide
        # question, with or without the agent, so it is always available.
        tools.append("aggregate_search")

        tools.extend(self.ordered_tools)

        return tuple(tools)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "retrievers": list(self.ordered),
            "agent": self.agent,
            "planner": self.planner,
            "extra_tools": list(self.ordered_tools),
            "allowed_tools": list(self.allowed_tools),
            "family": self.family.value,
            "method": self.method,
        }


# -------------------------------------------------------------------
# Shortcuts
# -------------------------------------------------------------------
#
# Swatches, not the whole palette. Each fills the builder in; none is
# reachable in a way a hand-built composition is not.

PRESETS: dict[str, Composition] = {
    "semantic": Composition(retrievers=(SEMANTIC,)),
    "keyword": Composition(retrievers=(KEYWORD,)),
    "hybrid": Composition(retrievers=(SEMANTIC, KEYWORD, HIERARCHICAL)),
    # `web_search` is offered here, not withheld: without it the Ask
    # page — the only surface that reaches this preset — could never use
    # the web, so switching `web.enabled` on had no observable effect and
    # the agent declined questions the internet answers. Asking is safe
    # because the setting still decides: `_is_offered` drops the tool
    # from the catalogue while `web.enabled` is false, which is the
    # default, so the library-only promise holds unless it is opted out
    # of deliberately.
    "agentic": Composition(
        retrievers=(SEMANTIC, KEYWORD, HIERARCHICAL),
        agent=True,
        extra_tools=("document_lookup", "calculate", "web_search"),
    ),
}

PRESET_LABELS = {
    "semantic": "Semantic only",
    "keyword": "Keyword only",
    "hybrid": "Hybrid",
    "agentic": "Agentic",
}


# What each mode meant before compositions existed. A chat still picks
# between these three, and a stored run or an older client keeps working.
MODE_DEFAULTS: dict[RagMode, Composition] = {
    RagMode.NAIVE: PRESETS["semantic"],
    RagMode.HYBRID: PRESETS["hybrid"],
    RagMode.AGENTIC: PRESETS["agentic"],
}


def list_options() -> dict:
    """Everything the builder needs: retrievers, tools, and shortcuts."""

    from port6.services.rag.tools import available_tools

    offered = available_tools()

    return {
        "retrievers": list(RETRIEVERS.values()),
        "tools": [
            # `enabled` is false for a tool switched off server-side, so
            # the UI can show it greyed rather than pretending it works.
            {**spec, "enabled": name in offered}
            for name, spec in EXTRA_TOOLS.items()
        ],
        "presets": [
            {
                "name": name,
                "label": PRESET_LABELS[name],
                **PRESETS[name].summary(),
            }
            for name in PRESETS
        ],
        "default_mode": default_mode(),
    }


def default_mode() -> str:
    """The configured default, falling back if the setting is stale."""

    configured = get_setting("defaults.mode")

    if configured in {mode.value for mode in RagMode}:
        return configured

    logger.warning(
        "defaults.mode is %r, which is not a known mode; falling back "
        "to hybrid",
        configured,
    )

    return RagMode.HYBRID.value


def resolve(
    retrievers: list[str] | None = None,
    agent: bool | None = None,
    planner: bool | None = None,
    extra_tools: list[str] | None = None,
    mode: str | RagMode | None = None,
) -> Composition:
    """Decide what answers a request.

    An explicit composition wins. A bare mode maps to the composition
    reproducing what that mode used to do. Neither means the configured
    default, which is what makes the header settings reach a new chat
    *and* an API call that names nothing.
    """

    if retrievers:
        return Composition(
            retrievers=tuple(retrievers),
            agent=bool(agent),
            planner=True if planner is None else bool(planner),
            extra_tools=tuple(extra_tools or ()),
        )

    if mode is not None:
        from port6.services.rag.system import resolve_mode

        return MODE_DEFAULTS[resolve_mode(mode)]

    return MODE_DEFAULTS[RagMode(default_mode())]


# -------------------------------------------------------------------
# Running one
# -------------------------------------------------------------------

def rerank(
    chunks: list[RetrievedChunk],
    top_k: int,
) -> list[RetrievedChunk]:
    """Order by fused score, preferring chunks two retrievers agreed on.

    Chunks found by more than one retriever are stronger evidence than
    either alone, so agreement breaks ties ahead of raw distance.
    """

    def sort_key(chunk: RetrievedChunk):
        return (
            -(chunk.fused_score or 0.0),
            -len(chunk.sources),
            chunk.score if chunk.score is not None else 1e9,
        )

    ordered = sorted(chunks, key=sort_key)

    for position, chunk in enumerate(ordered[:top_k], start=1):
        chunk.number = position

    return ordered[:top_k]


@dataclass
class _Retrieved:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    stages: list[dict] = field(default_factory=list)
    documents_considered: int = 0


async def _retrieve(
    composition: Composition,
    question: str,
    top_k: int,
    document_ids: list[str] | None,
) -> _Retrieved:
    """Run the composition's retrievers and combine what they return."""

    # Retrieve wider than top_k so fusion has candidates to choose
    # between; a single retriever has nothing to fuse with, so it takes
    # exactly what was asked for.
    plural = len(composition.ordered) > 1
    candidate_k = max(top_k * 2, 8) if plural else top_k

    found = _Retrieved()

    # The dense side of the fusion. Hierarchical results join it because
    # both rank by embedding distance, which is what makes them
    # comparable to each other and not to BM25.
    dense: list[RetrievedChunk] = []
    sparse: list[RetrievedChunk] = []

    for name in composition.ordered:

        if name == SEMANTIC:
            chunks = await semantic_search(
                question, top_k=candidate_k, document_ids=document_ids
            )
            dense.extend(chunks)
            found.stages.append(
                {"name": "semantic_search", "detail": f"{len(chunks)} chunks"}
            )

        elif name == KEYWORD:
            chunks = keyword_search(
                question, top_k=candidate_k, document_ids=document_ids
            )
            sparse.extend(chunks)
            found.stages.append(
                {"name": "keyword_search", "detail": f"{len(chunks)} chunks"}
            )

        elif name == HIERARCHICAL:
            hierarchy = await hierarchical_search(
                question, top_k=candidate_k, document_ids=document_ids
            )
            chunks = hierarchy["chunks"]
            dense.extend(chunks)
            found.documents_considered = len(hierarchy["documents"])
            found.stages.append(
                {
                    "name": "hierarchical_search",
                    "detail": (
                        f"{found.documents_considered} documents, "
                        f"{len(hierarchy['sections'])} sections, "
                        f"{len(chunks)} chunks"
                    ),
                }
            )

    if dense and sparse:
        found.chunks = rerank(fuse(dense, sparse, top_k=candidate_k), top_k)
        found.stages.append(
            {"name": "rrf_fusion", "detail": f"{len(found.chunks)} kept"}
        )

    else:
        # One side only, so its own ordering is the ranking.
        single = (dense or sparse)[:top_k]

        for position, chunk in enumerate(single, start=1):
            chunk.number = position

        found.chunks = single

    return found


async def run(
    composition: Composition,
    question: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> RagResult:
    """Answer a question with one composition."""

    if composition.agent:
        from port6.services.rag import agent

        return await agent.run(
            question,
            top_k=top_k,
            document_ids=document_ids,
            composition=composition,
        )

    started = time.perf_counter()

    # A question about the library as a whole needs breadth, not depth,
    # whichever retrievers were chosen. Ordinary top-k can return five
    # chunks from one document, which makes "which documents mention X"
    # unanswerable however it is prompted.
    if get_setting("aggregation.enabled") and is_aggregation_question(
        question
    ):
        return await _run_aggregated(
            composition, question, started, document_ids, top_k=top_k
        )

    found = await _retrieve(composition, question, top_k, document_ids)

    result = await generate_answer(question, found.chunks)

    agreed = [chunk for chunk in found.chunks if len(chunk.sources) > 1]

    return RagResult(
        question=question,
        answer=result["answer"],
        answered=result["answered"],
        citations=result["citations"],
        retrieved_chunks=result["chunks"],
        retrieval_method=composition.method,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        metadata={
            "mode": composition.family.value,
            "pipeline": composition.id,
            "pipeline_label": composition.label,
            "retrievers": list(composition.ordered),
            "agent": False,
            "top_k": top_k,
            "chunks_retrieved": len(found.chunks),
            "documents_considered": found.documents_considered,
            "found_by_both": len(agreed),
            "conflicts": [
                conflict.describe() for conflict in result["conflicts"]
            ],
            "scoped_to_documents": len(document_ids) if document_ids else 0,
        },
        debug={
            "pipeline": composition.id,
            "retrievers": list(composition.ordered),
            "stages": found.stages,
        },
    )


async def _run_aggregated(
    composition: Composition,
    question: str,
    started: float,
    document_ids: list[str] | None,
    top_k: int = 5,
) -> RagResult:
    """Answer by covering documents rather than ranking chunks."""

    coverage = await coverage_search(
        question,
        document_ids=document_ids,
        retrievers=composition.ordered,
        # Top K is a chunk budget here as everywhere else. Coverage
        # decides how those chunks are spread across documents, not how
        # many of them there are.
        top_k=top_k,
    )

    chunks = coverage["chunks"]

    result = await generate_answer(
        question,
        chunks,
        prompt_name="aggregate_answer",
        context_builder=build_grouped_context,
    )

    return RagResult(
        question=question,
        answer=result["answer"],
        answered=result["answered"],
        citations=result["citations"],
        retrieved_chunks=result["chunks"],
        retrieval_method=(
            "cross-document aggregation over "
            + " + ".join(composition.ordered)
            + ": best chunks from each matching document"
        ),
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        metadata={
            "mode": composition.family.value,
            "pipeline": composition.id,
            "pipeline_label": composition.label,
            "retrievers": list(composition.ordered),
            "agent": composition.agent,
            "top_k": top_k,
            "aggregated": True,
            "documents_covered": coverage["documents"],
            "documents_matched": coverage["documents_matched"],
            "documents_dropped_for_budget": coverage[
                "documents_dropped_for_budget"
            ],
            "chunks_retrieved": len(chunks),
            "conflicts": [
                conflict.describe() for conflict in result["conflicts"]
            ],
            "scoped_to_documents": len(document_ids) if document_ids else 0,
        },
        debug={
            "pipeline": composition.id,
            "retrievers": list(composition.ordered),
            "aggregated": True,
            "stages": [
                {
                    "name": "coverage_search",
                    "detail": (
                        f"{len(coverage['documents'])} documents, "
                        f"{len(chunks)} chunks"
                    ),
                }
            ],
        },
    )
