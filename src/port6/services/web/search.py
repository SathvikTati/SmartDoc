"""Web search, as a retrieval source alongside the documents.

**Why not Google.** Google has no keyless search API. The official route is
the Custom Search JSON API, which needs a Cloud project, an API key and a
separately-created search engine id before it returns a single result, and
scraping google.com directly gets rate-limited and blocked. DuckDuckGo does
the same job with no configuration at all, so this uses that and works the
moment it is installed.

This deliberately changes what PORT-6 promises. Every other retriever can
only return text from a file someone uploaded, which is what makes "answers
come only from your documents" true. A web result is not that.

So the separation is kept explicit rather than blurred:

- a web chunk carries a `url`, and nothing else in the system sets one, so
  `chunk.is_web` is an exact test
- its `document_id` is the literal string "web", so it can never be mistaken
  for a row in the documents table or linked to as one
- the context handed to the model labels it `WEB` with its URL, so a
  citation that came off the internet says so
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from port6.services.rag.base import RetrievedChunk


logger = logging.getLogger(__name__)


WEB_DOCUMENT_ID = "web"

# Long enough to fail fast when there is no network, short enough that a
# slow search cannot hold up an answer the documents could have given.
TIMEOUT_SECONDS = 10


def is_available() -> bool:
    """True when the search package is installed.

    No credentials to check — that is the point of using a keyless
    provider. Still guarded, because the dependency is optional.
    """

    try:
        import ddgs  # noqa: F401

        return True

    except ImportError:
        return False


def domain_of(url: str) -> str:
    """"https://acme.com/hr/leave" -> "acme.com". Used as the source name."""

    try:
        host = urlparse(url).netloc
    except Exception:
        return "web"

    return host[4:] if host.startswith("www.") else host or "web"


def to_chunks(results: list[dict]) -> list[RetrievedChunk]:
    """Turn search results into chunks the rest of the pipeline can use."""

    chunks = []

    for position, result in enumerate(results, start=1):

        # Providers disagree on the key; accept either.
        link = result.get("href") or result.get("link") or ""
        snippet = (result.get("body") or result.get("snippet") or "").strip()
        title = (result.get("title") or "").strip()

        if not snippet and not title:
            continue

        chunks.append(
            RetrievedChunk(
                number=position,
                # The URL is the identity, so the same page found twice
                # deduplicates to one source.
                chunk_id=f"web:{link}",
                document_id=WEB_DOCUMENT_ID,
                filename=domain_of(link),
                url=link,
                # The title is part of the evidence: a snippet alone is
                # often meaningless without knowing what page it is from.
                content=f"{title}\n\n{snippet}" if title else snippet,
                section_title=title or None,
                sources=["web"],
                semantic_rank=position,
            )
        )

    return chunks


def search(
    query: str,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Search the web. Returns [] when unavailable rather than raising."""

    if not is_available():
        logger.info("Web search requested but the ddgs package is not installed")
        return []

    try:
        from ddgs import DDGS

        with DDGS(timeout=TIMEOUT_SECONDS) as client:
            results = list(client.text(query, max_results=top_k))

    except Exception as exc:
        # A failing web search must not sink a question the documents
        # could still answer.
        logger.warning("Web search failed: %s", exc)
        return []

    chunks = to_chunks(results)

    logger.info("Web search returned %d result(s)", len(chunks))

    return chunks
