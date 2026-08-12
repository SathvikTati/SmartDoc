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

    vector_store._collection.upsert(
        ids=ids,
        documents=[
            chunk.page_content
            for chunk in chunks
        ],
        metadatas=[
            chunk.metadata
            for chunk in chunks
        ],
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


def search_documents(
    query: str,
    top_k: int = 5,
):
    vector_store = get_vector_store()

    results = vector_store.similarity_search_with_score(
        query,
        k=top_k,
    )

    return results