"""Retrieval primitives shared by the modes.

- semantic_search: dense vector search over Chroma
- keyword_search:  BM25 over the same chunks
- fuse:            Reciprocal Rank Fusion of the two

Both retrievers read the same Chroma collection, so a chunk found by either
carries identical metadata and can be cited the same way.
"""

from __future__ import annotations

import logging
import re
import threading

from rank_bm25 import BM25Okapi

from port6.services.embeddings.service import get_embeddings
from port6.services.rag.base import RetrievedChunk, chunk_from_metadata
from port6.services.settings.service import get_setting
from port6.services.vector.chroma import get_vector_store


logger = logging.getLogger(__name__)


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def where_for_documents(
    document_ids: list[str] | None,
) -> dict | None:
    """A Chroma metadata filter restricting retrieval to some documents.

    None means the whole library. Chroma wants a bare equality for one id
    and `$in` for several.
    """

    if not document_ids:
        return None

    unique = sorted(set(document_ids))

    if len(unique) == 1:
        return {"document_id": unique[0]}

    return {"document_id": {"$in": unique}}


def combine_where(*clauses: dict | None) -> dict | None:
    """AND together the clauses that are actually present."""

    present = [clause for clause in clauses if clause]

    if not present:
        return None

    if len(present) == 1:
        return present[0]

    return {"$and": present}


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens.

    Deliberately keeps digits and short tokens: enterprise queries turn on
    exact terms like "26 weeks", "v4", "HR-2026" that stemming would blur.
    """

    return TOKEN_PATTERN.findall(text.lower())


# -------------------------------------------------------------------
# Semantic
# -------------------------------------------------------------------

async def semantic_search(
    query: str,
    top_k: int = 5,
    where: dict | None = None,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Dense retrieval, optionally restricted to some documents."""

    if not query.strip():
        raise ValueError("Query cannot be empty")

    if top_k < 1:
        raise ValueError("top_k must be greater than 0")

    collection = get_vector_store()._collection

    if collection.count() == 0:
        logger.warning("Vector collection is empty")
        return []

    embedding = await get_embeddings().aembed_query(query)

    query_args = {
        "query_embeddings": [embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }

    scoped = combine_where(where, where_for_documents(document_ids))

    if scoped:
        query_args["where"] = scoped

    results = collection.query(**query_args)

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]
    distances = (results.get("distances") or [[]])[0]

    chunks = []

    for index, content in enumerate(documents):

        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None

        chunk = chunk_from_metadata(
            number=index + 1,
            content=content,
            metadata=metadata or {},
            score=float(distance) if distance is not None else None,
        )

        chunk.sources = ["semantic"]
        chunk.semantic_rank = index + 1

        chunks.append(chunk)

    max_distance = get_setting("retrieval.max_distance")

    if max_distance is not None:
        chunks = [
            chunk
            for chunk in chunks
            if chunk.score is None or chunk.score <= max_distance
        ]

    logger.info(
        "Semantic search returned %d chunks (filter=%s)",
        len(chunks),
        scoped,
    )

    return chunks


# -------------------------------------------------------------------
# Keyword (BM25)
# -------------------------------------------------------------------

class KeywordIndex:
    """BM25 over every chunk in the collection.

    Chroma has no keyword index, so one is built in memory from the stored
    chunks. Two things make that affordable:

    - the *tokenised* corpus is cached per chunk id, so a rebuild after an
      upload re-tokenises only the new chunks rather than the whole library
    - the ids are fetched without documents or metadata first, which is a
      cheap way to find out whether anything actually changed

    BM25Okapi has no incremental update — its IDF table is computed over
    the whole corpus — so the scorer itself is still reconstructed. That is
    arithmetic over already-tokenised lists, not I/O and not re-parsing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bm25: BM25Okapi | None = None
        self._ids: list[str] = []
        self._documents: list[str] = []
        self._metadatas: list[dict] = []

        # chunk id -> (text, metadata, tokens), retained across rebuilds.
        self._cache: dict[str, tuple[str, dict, list[str]]] = {}
        self._built_for_ids: tuple[str, ...] | None = None

    def _build(self, current_ids: list[str]) -> None:

        collection = get_vector_store()._collection

        if not current_ids:
            self._bm25 = None
            self._ids = []
            self._documents = []
            self._metadatas = []
            self._cache = {}
            self._built_for_ids = ()
            return

        missing = [
            chunk_id
            for chunk_id in current_ids
            if chunk_id not in self._cache
        ]

        if missing:
            fetched = collection.get(
                ids=missing,
                include=["documents", "metadatas"],
            )

            fetched_ids = fetched.get("ids") or []
            fetched_documents = fetched.get("documents") or []
            fetched_metadatas = fetched.get("metadatas") or []

            for position, chunk_id in enumerate(fetched_ids):
                text = (
                    fetched_documents[position]
                    if position < len(fetched_documents)
                    else ""
                ) or ""
                metadata = (
                    fetched_metadatas[position]
                    if position < len(fetched_metadatas)
                    else {}
                ) or {}

                self._cache[chunk_id] = (text, metadata, tokenize(text))

        # Drop anything deleted since the last build so the cache cannot
        # grow forever across re-ingestions.
        live = set(current_ids)
        for stale in [key for key in self._cache if key not in live]:
            del self._cache[stale]

        self._ids = current_ids
        self._documents = [self._cache[i][0] for i in current_ids]
        self._metadatas = [self._cache[i][1] for i in current_ids]

        corpus = [self._cache[i][2] for i in current_ids]

        # BM25Okapi cannot be built from an empty corpus.
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self._built_for_ids = tuple(current_ids)

        logger.info(
            "Built BM25 index over %d chunks (%d newly tokenised)",
            len(corpus),
            len(missing),
        )

    def ensure_current(self) -> None:

        collection = get_vector_store()._collection

        # Ids only: no documents, no metadata, no embeddings. This is the
        # cheap question "has anything changed?", asked on every search.
        current_ids = collection.get(include=[]).get("ids") or []
        signature = tuple(current_ids)

        if self._bm25 is not None and self._built_for_ids == signature:
            return

        if not current_ids and self._built_for_ids == ():
            return

        with self._lock:
            # Re-check inside the lock; another thread may have just built it.
            if self._bm25 is not None and self._built_for_ids == signature:
                return

            self._build(current_ids)

    def search(
        self,
        query: str,
        top_k: int = 5,
        allowed_ids: set[str] | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:

        self.ensure_current()

        if self._bm25 is None:
            return []

        tokens = tokenize(query)

        if not tokens:
            return []

        scope = set(document_ids) if document_ids else None

        scores = self._bm25.get_scores(tokens)

        ranked = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )

        chunks: list[RetrievedChunk] = []

        for position in ranked:

            # BM25 gives 0 to documents sharing no query term; those are
            # not keyword matches at all.
            if scores[position] <= 0:
                break

            metadata = (
                self._metadatas[position]
                if position < len(self._metadatas)
                else {}
            ) or {}

            if allowed_ids is not None:
                chunk_id = str(
                    metadata.get("chunk_id", self._ids[position])
                )
                if chunk_id not in allowed_ids:
                    continue

            # BM25 scores the whole corpus, so a document scope is applied
            # by skipping non-matching hits as they are walked.
            if scope is not None:
                if str(metadata.get("document_id", "")) not in scope:
                    continue

            chunk = chunk_from_metadata(
                number=len(chunks) + 1,
                content=self._documents[position],
                metadata=metadata,
                score=float(scores[position]),
            )

            chunk.sources = ["keyword"]
            chunk.keyword_rank = len(chunks) + 1

            chunks.append(chunk)

            if len(chunks) >= top_k:
                break

        logger.info(
            "Keyword search returned %d chunks",
            len(chunks),
        )

        return chunks


_keyword_index = KeywordIndex()


def keyword_search(
    query: str,
    top_k: int = 5,
    allowed_ids: set[str] | None = None,
    document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    return _keyword_index.search(
        query,
        top_k=top_k,
        allowed_ids=allowed_ids,
        document_ids=document_ids,
    )


def reset_keyword_index() -> None:
    """Force a rebuild; used by tests and after bulk edits."""

    global _keyword_index
    _keyword_index = KeywordIndex()


# -------------------------------------------------------------------
# Fusion
# -------------------------------------------------------------------

def fuse(
    semantic: list[RetrievedChunk],
    keyword: list[RetrievedChunk],
    top_k: int = 5,
    k: int = 60,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion.

    Each list contributes 1/(k + rank) per chunk. RRF is used rather than
    score averaging because the two retrievers produce incomparable numbers:
    Chroma returns a distance where lower is better, BM25 returns an
    unbounded relevance score where higher is better. Ranks are comparable;
    raw scores are not.

    A chunk found by both retrievers accumulates both contributions, which
    is what pushes agreed-upon results to the top.
    """

    merged: dict[str, RetrievedChunk] = {}
    fused_scores: dict[str, float] = {}

    def contribute(
        chunks: list[RetrievedChunk],
        source: str,
    ) -> None:

        for rank, chunk in enumerate(chunks, start=1):

            key = chunk.chunk_id

            if key not in merged:
                # Copy so the caller's lists keep their own rank fields.
                merged[key] = chunk.model_copy(deep=True)
                merged[key].sources = []
                fused_scores[key] = 0.0

            existing = merged[key]

            if source not in existing.sources:
                existing.sources.append(source)

            if source == "semantic":
                existing.semantic_rank = rank
                # Keep the distance for display.
                existing.score = chunk.score

            else:
                existing.keyword_rank = rank

            fused_scores[key] += 1.0 / (k + rank)

    contribute(semantic, "semantic")
    contribute(keyword, "keyword")

    ordered = sorted(
        merged.values(),
        key=lambda chunk: fused_scores[chunk.chunk_id],
        reverse=True,
    )

    for position, chunk in enumerate(ordered, start=1):
        chunk.fused_score = round(fused_scores[chunk.chunk_id], 6)
        chunk.number = position

    logger.info(
        "RRF fused %d semantic + %d keyword into %d unique, keeping %d",
        len(semantic),
        len(keyword),
        len(ordered),
        min(top_k, len(ordered)),
    )

    return ordered[:top_k]
