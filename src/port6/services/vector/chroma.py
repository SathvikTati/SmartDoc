from langchain_chroma import Chroma
from langchain_core.documents import Document as LangChainDocument

from port6.config import vector_config
from port6.services.embeddings.service import get_embeddings


def get_vector_store() -> Chroma:
    return Chroma(
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