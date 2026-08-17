import threading

from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument

from port6.config import vector_config
from port6.services.embeddings.service import get_embeddings


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

    return len(chunks)


def delete_document_chunks(
    document_id: str,
) -> None:

    vector_store = get_vector_store()

    vector_store._collection.delete(
        where={
            "document_id": document_id,
        }
    )


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