import logging
import threading

from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument

from port6.config import vector_config
from port6.services.embeddings.service import get_embeddings


logger = logging.getLogger(__name__)


# Ingestion runs in FastAPI background threads, so uploading several files at
# once used to build several Chroma clients against the same directory at the
# same time. That races inside Chroma's client registry and fails ingestion
# with errors like "'RustBindingsAPI' object has no attribute 'bindings'".
# One shared client, built once under a lock, avoids it — and avoids
# reopening the store on every call.
_vector_store: Chroma | None = None
_vector_store_lock = threading.Lock()


def get_vector_store() -> Chroma:

    global _vector_store

    if _vector_store is not None:
        return _vector_store

    with _vector_store_lock:

        # Another thread may have built it while this one waited.
        if _vector_store is None:
            _vector_store = Chroma(
                collection_name=vector_config.get(
                    "collection_name",
                    "port6_documents",
                ),
                embedding_function=get_embeddings(),
                persist_directory=vector_config.get(
                    "persist_directory",
                    "chroma_data",
                ),
            )

    return _vector_store


def store_chunks(
    chunks: list[LangChainDocument],
) -> int:

    if not chunks:
        return 0

    vector_store = get_vector_store()

    ids = [
        (
            f"{chunk.metadata['document_id']}:"
            f"{chunk.metadata['chunk_index']}"
        )
        for chunk in chunks
    ]

    # add_documents upserts by id through the configured embedding
    # function. Writing to _collection directly would make Chroma fall
    # back to its own default embedder and store the wrong dimension.
    vector_store.add_documents(
        chunks,
        ids=ids,
    )

    _invalidate_answers()

    return len(chunks)


def _invalidate_answers() -> None:
    """Drop every cached answer, because the index behind them moved.

    These two functions are the only places the index changes — upload,
    reprocess and delete all pass through one of them — so this is the
    whole of cache invalidation. Imported here rather than at module scope
    to keep the vector store from depending on the cache to load.
    """

    from port6.services.cache.service import clear_soon

    clear_soon()


def delete_document_chunks(
    document_id: str,
) -> None:

    vector_store = get_vector_store()

    vector_store._collection.delete(
        where={
            "document_id": document_id,
        }
    )

    _invalidate_answers()


def get_collection_count() -> int:
    vector_store = get_vector_store()

    return vector_store._collection.count()


def count_document_chunks(
    document_id: str,
) -> int:
    """How many chunks a single document currently has in the index."""

    vector_store = get_vector_store()

    stored = vector_store._collection.get(
        where={
            "document_id": document_id,
        },
        include=[],
    )

    return len(stored.get("ids") or [])


def count_chunks_by_document() -> dict[str, int]:
    """Chunk counts for every indexed document, in one pass.

    The document list needs a count per row, and calling
    `count_document_chunks` for each would be one Chroma round trip per
    document. This reads the metadata once and tallies in memory.

    The tradeoff is that it pulls every chunk's metadata, so it belongs on
    a list endpoint rather than on a hot path. It returns {} on failure:
    a count is a nicety, and losing the index should not take the
    document list down with it.
    """

    try:
        vector_store = get_vector_store()

        stored = vector_store._collection.get(include=["metadatas"])

    except Exception as exc:
        logger.warning("Could not count chunks by document: %s", exc)
        return {}

    counts: dict[str, int] = {}

    for metadata in stored.get("metadatas") or []:

        document_id = (metadata or {}).get("document_id")

        if not document_id:
            continue

        key = str(document_id)

        counts[key] = counts.get(key, 0) + 1

    return counts


def search_documents(
    query: str,
    top_k: int = 5,
):
    vector_store = get_vector_store()

    count = vector_store._collection.count()

    if count == 0:
        return []

    return vector_store.similarity_search_with_score(
        query,
        k=min(top_k, count),
    )