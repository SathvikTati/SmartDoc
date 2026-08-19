"""Retrieval tools the agent can choose between.

Each is a LangChain `@tool`, so its description lives in the docstring
beside the code rather than in a registry a hundred lines away, and its
argument schema is generated rather than restated.

**They are selected by prompt, not by function calling.** The configured
local model picks the right tool reliably but emits the choice as JSON in
its content, leaving `tool_calls` empty — so `bind_tools` and LangGraph's
`ToolNode` would see no call and silently do nothing. The planner in
`agent.py` parses that JSON instead. The `@tool` wrapper still earns its
place: one source of truth for names, descriptions and arguments, and
native function calling becomes available unchanged on a provider that
supports it.

Every tool returns `{"chunks": [...], "info": {...}}`. Chunks are
`RetrievedChunk` objects rather than text, because they flow into the
context builder and the citation list, not back into the model as a tool
message.
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from port6.services.db.database import SessionLocal
from port6.services.model.models import Document
from port6.services.rag.aggregation import coverage_search
from port6.services.rag.base import RetrievedChunk
from port6.services.rag.hierarchical import hierarchical_search
from port6.services.rag.retrievers import (
    fuse,
    keyword_search,
    semantic_search,
)
from port6.services.settings.service import get_int, get_setting
from port6.services.web import search as web


logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Tools
# -------------------------------------------------------------------

@tool("semantic_search")
async def semantic_search_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """Vector similarity search over all chunks. Good for general
    questions phrased in natural language."""

    chunks = await semantic_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )

    return {"chunks": chunks, "info": {"retrieved": len(chunks)}}


@tool("keyword_search")
async def keyword_search_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """BM25 keyword search. Good for exact terms, policy names, codes,
    numbers and rare words."""

    chunks = keyword_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )

    return {"chunks": chunks, "info": {"retrieved": len(chunks)}}


@tool("hybrid_search")
async def hybrid_search_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """Semantic and keyword search fused with RRF. A safe default when the
    question mixes concepts and exact terms."""

    semantic = await semantic_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )
    keyword = keyword_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )

    chunks = fuse(semantic, keyword, top_k=top_k)

    return {
        "chunks": chunks,
        "info": {
            "semantic": len(semantic),
            "keyword": len(keyword),
            "fused": len(chunks),
        },
    }


@tool("hierarchical_search")
async def hierarchical_search_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """Narrows document, then section, then chunk. Good when the answer
    sits in a specific part of a known document."""

    result = await hierarchical_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )

    return {
        "chunks": result["chunks"],
        "info": {
            "documents": result["documents"],
            "sections": result["sections"],
        },
    }


@tool("aggregate_search")
async def aggregate_search_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """Cover every document that mentions the topic, taking the best
    chunks from each. Use for questions about the library as a whole:
    which documents mention X, comparing across documents, or what each
    policy says."""

    # top_k is ignored on purpose: the shape of an aggregation answer is
    # set by how many documents match, not by a chunk budget.
    coverage = await coverage_search(query, document_ids=document_ids)

    return {
        "chunks": coverage["chunks"],
        "info": {
            "documents_covered": coverage["documents"],
            "aggregated": True,
        },
    }


@tool("web_search")
async def web_search_tool(
    query: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> dict:
    """Search the public web. Use ONLY when the uploaded documents cannot
    answer the question — current events, external standards, or
    background the library does not contain. Results come from the
    internet, not from the user's documents."""

    # A document scope is a statement about which *documents* may be
    # used; reaching outside the library would contradict it.
    if document_ids:
        logger.info("Web search skipped: the question is scoped to documents")
        return {
            "chunks": [],
            "info": {"skipped": "question is scoped to specific documents"},
        }

    chunks = web.search(query, top_k=top_k)

    return {
        "chunks": chunks,
        "info": {
            "retrieved": len(chunks),
            "web": True,
            "urls": [chunk.url for chunk in chunks],
        },
    }


@tool("calculate")
async def calculate_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """Evaluate an arithmetic expression. Use for any sum the answer
    depends on — remaining leave, a percentage of a cap, a pro-rated
    entitlement. Pass only the expression, for example "22 - 8" or
    "250 * 0.15". Do not pass a sentence."""

    from port6.services.rag.calculator import (
        UnsafeExpression,
        calculate,
        calculation_chunk,
        format_result,
    )

    try:
        value = calculate(query)

    except UnsafeExpression:
        # A sentence, not an expression — which is the normal case, since
        # the agent hands every tool the raw question.
        #
        # This used to ask the model to write the expression here. That
        # was a mistake: the planner runs *before* retrieval, so there
        # were no sources, and the model filled the gap from the worked
        # examples in the prompt. It answered "22 - 8" for a leave
        # question because 22 appears in an example, not because it had
        # read the policy — and it would have said 22 on a corpus where
        # the entitlement is 25.
        #
        # The sum is done after retrieval instead, in generation, where
        # the figures are actually on the table. Selecting this tool is
        # still meaningful: it is how the planner signals that the
        # question needs arithmetic.
        return {
            "chunks": [],
            "info": {
                "deferred": (
                    "the expression is written after retrieval, when the "
                    "sources are available"
                )
            },
        }

    result = format_result(value)

    return {
        "chunks": [calculation_chunk(1, query.strip(), result)],
        "info": {"expression": query.strip(), "result": result},
    }


@tool("document_lookup")
async def document_lookup_tool(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """List the documents in the library. Use to find out what exists."""

    # The catalogue is returned as a chunk, not only as `info`: only
    # chunks reach the answer generator, so a tool that reported the
    # library purely as metadata could never answer "what do we have?".
    db = SessionLocal()

    try:
        limit = get_int("agent.catalogue_limit")

        base = db.query(Document).filter(Document.status == "READY")

        # A scoped question is about those documents, so the catalogue
        # lists them rather than the whole library.
        if document_ids:
            base = base.filter(Document.id.in_(document_ids))

        total = base.count()

        # Bounded: a library of hundreds would otherwise be pasted whole
        # into the context window for a single catalogue question.
        documents = (
            base.order_by(Document.created_at.desc()).limit(limit).all()
        )

        catalogue = [
            {
                "document_id": str(document.id),
                "filename": document.filename,
                "summary": document.summary,
            }
            for document in documents
        ]

        if not catalogue:
            return {"chunks": [], "info": {"documents": []}}

        summary_characters = get_int("agent.catalogue_summary_characters")

        lines = [
            f"The document library contains {total} document(s)."
            + (
                f" Showing the {len(catalogue)} most recent:"
                if total > len(catalogue)
                else ""
            )
        ]

        for entry in catalogue:

            line = f"- {entry['filename']}"

            # The summary is the only thing that says what a file is
            # about. Clipped so a long one cannot bury the filenames,
            # which are what a "what documents do we have?" answer lists.
            if entry["summary"]:
                summary = " ".join(entry["summary"].split())

                if len(summary) > summary_characters:
                    summary = summary[:summary_characters].rstrip() + "…"

                line += f" — {summary}"

            lines.append(line)

        listing = RetrievedChunk(
            number=1,
            chunk_id="library:catalogue",
            document_id="library",
            filename="document library",
            content="\n".join(lines),
            sources=["catalogue"],
        )

        return {
            "chunks": [listing],
            "info": {
                "documents": catalogue,
                "total_documents": total,
                "truncated": total > len(catalogue),
            },
        }

    finally:
        db.close()


# -------------------------------------------------------------------
# Registry
# -------------------------------------------------------------------
#
# Names come from the decorators above, so there is one source of truth
# for each tool's name, description and arguments.

_ALL = [
    semantic_search_tool,
    keyword_search_tool,
    hybrid_search_tool,
    hierarchical_search_tool,
    aggregate_search_tool,
    web_search_tool,
    calculate_tool,
    document_lookup_tool,
]


# Every tool, offered or not. Execution resolves here, so a plan made a
# moment ago still runs even if a tool has since been switched off.
TOOLS: dict = {tool_fn.name: tool_fn for tool_fn in _ALL}


def _is_offered(name: str) -> bool:
    """Whether the planner may choose this tool right now.

    An unusable tool left in the catalogue is worse than a missing one:
    the planner picks it, the call returns nothing, and the agent spends
    a retry discovering that.
    """

    if name != "web_search":
        return True

    return web.is_available() and bool(get_setting("web.enabled"))


def available_tools(allowed: tuple[str, ...] | None = None) -> dict:
    """The tools the planner may choose from right now.

    Two gates, and both have to pass. `_is_offered` is the server's
    say — web search stays off unless it is switched on, whatever a
    request asks for. `allowed` is the composition's say: the retrieval
    tools it was built from, plus whatever extras were selected.

    None means no composition-level restriction, which is what a direct
    call to the agent gets.
    """

    return {
        name: tool_fn
        for name, tool_fn in TOOLS.items()
        if _is_offered(name) and (allowed is None or name in allowed)
    }


# The planner runs *before* retrieval, so it cannot know whether the
# documents can answer — and web_search is documented for exactly the case
# it cannot yet see. Offering it here let the model plan a web search on
# the first pass, which is how "what is python" came back sourced from
# python.org instead of reported as absent from the library.
#
# The rule-based planner already withheld it for this reason. This puts the
# model planner under the same discipline, leaving the web reachable only
# once an attempt has actually come up short.
PLANNER_WITHHELD = ("web_search",)


def tool_catalogue(
    allowed: tuple[str, ...] | None = None,
    include_withheld: bool = False,
) -> str:
    """Tool names and descriptions, for the planner prompt."""

    return "\n".join(
        f"- {name}: {' '.join(tool_fn.description.split())}"
        for name, tool_fn in available_tools(allowed).items()
        if include_withheld or name not in PLANNER_WITHHELD
    )
