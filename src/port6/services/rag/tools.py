"""Retrieval tools the agent can choose between.

Each tool is an independently testable async callable returning
`{"chunks": [...], "info": {...}}`. The registry carries a description of
when each one is useful, which is what the planner reasons over.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from port6.services.db.database import SessionLocal
from port6.services.model.models import Document
from port6.services.rag.base import RetrievedChunk
from port6.services.rag.hierarchical import hierarchical_search
from port6.services.rag.retrievers import (
    fuse,
    keyword_search,
    semantic_search,
)
from port6.services.settings.service import get_int


logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    run: Callable[..., Awaitable[dict]]


# -------------------------------------------------------------------
# Tools
# -------------------------------------------------------------------

async def tool_semantic_search(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:

    chunks = await semantic_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )

    return {
        "chunks": chunks,
        "info": {"retrieved": len(chunks)},
    }


async def tool_keyword_search(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:

    chunks = keyword_search(
        query,
        top_k=top_k,
        document_ids=document_ids,
    )

    return {
        "chunks": chunks,
        "info": {"retrieved": len(chunks)},
    }


async def tool_hybrid_search(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:

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


async def tool_hierarchical_search(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:

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


async def tool_document_lookup(
    query: str,
    top_k: int = 8,
    document_ids: list[str] | None = None,
) -> dict:
    """List what is in the library.

    The catalogue is returned as a chunk, not only as `info`: only chunks
    reach the answer generator, so a tool that reported the library purely
    as metadata could never actually answer "what documents do we have?".
    """

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
            base.order_by(Document.created_at.desc())
            .limit(limit)
            .all()
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
            return {
                "chunks": [],
                "info": {"documents": []},
            }

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

            # The summary is the only thing that says what a file is about,
            # now that nothing classifies documents by type or department.
            # It is clipped so a long one cannot bury the filenames, which
            # are what a "what documents do we have?" answer should list.
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

TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            "semantic_search",
            "Vector similarity search over all chunks. Good for general "
            "questions phrased in natural language.",
            tool_semantic_search,
        ),
        Tool(
            "keyword_search",
            "BM25 keyword search. Good for exact terms, policy names, "
            "codes, numbers and rare words.",
            tool_keyword_search,
        ),
        Tool(
            "hybrid_search",
            "Semantic and keyword search fused with RRF. A safe default "
            "when the question mixes concepts and exact terms.",
            tool_hybrid_search,
        ),
        Tool(
            "hierarchical_search",
            "Narrows document, then section, then chunk. Good when the "
            "answer sits in a specific part of a known document.",
            tool_hierarchical_search,
        ),
        Tool(
            "document_lookup",
            "List the documents in the library. Use to find out what "
            "exists.",
            tool_document_lookup,
        ),
    ]
}


def tool_catalogue() -> str:
    """Tool names and descriptions, for the planner prompt."""

    return "\n".join(
        f"- {tool.name}: {tool.description}"
        for tool in TOOLS.values()
    )
