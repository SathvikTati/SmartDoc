from temporalio import activity

from port6.services.chunking.service import chunk_document
from port6.services.db.database import SessionLocal
from port6.services.embeddings.service import get_embeddings
from port6.services.model.models import Document
from port6.services.vector.chroma import get_vector_store, store_chunks

@activity.defn
async def mark_processing(
    document_id: str,
) -> None:

    db = SessionLocal()

    try:
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .first()
        )

        if document is None:
            raise ValueError(
                f"Document {document_id} not found"
            )

        document.status = "PROCESSING"

        db.commit()

        activity.logger.info(
            "Document %s marked as PROCESSING",
            document_id,
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


@activity.defn
async def chunk_document_activity(
    document_id: str,
) -> int:

    db = SessionLocal()

    try:
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .first()
        )

        if document is None:
            raise ValueError(
                f"Document {document_id} not found"
            )

        chunks = chunk_document(
            document_id=str(document.id),
            filename=document.filename,
            content=document.content,
        )

        activity.logger.info(
            "Document %s split into %d chunks",
            document_id,
            len(chunks),
        )

        return len(chunks)

    finally:
        db.close()


@activity.defn
async def embed_document(
    document_id: str,
) -> int:

    db = SessionLocal()

    try:
        document = (
            db.query(Document)
            .filter(
                Document.id == document_id
            )
            .first()
        )

        if document is None:
            raise ValueError(
                f"Document {document_id} not found"
            )

        chunks = chunk_document(
            document_id=str(document.id),
            filename=document.filename,
            content=document.content,
        )

        if not chunks:
            raise ValueError(
                f"Document {document_id} produced no chunks"
            )

        stored_count = store_chunks(
            chunks
        )

        activity.logger.info(
            "Stored %d chunks in ChromaDB "
            "for document %s",
            stored_count,
            document_id,
        )

        return stored_count

    finally:
        db.close()

@activity.defn
async def mark_ready(
    document_id: str,
) -> None:

    db = SessionLocal()

    try:
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .first()
        )

        if document is None:
            raise ValueError(
                f"Document {document_id} not found"
            )

        document.status = "READY"

        db.commit()

        activity.logger.info(
            "Document %s marked as READY",
            document_id,
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

@activity.defn
async def mark_failed(
    document_id: str,
    error_message: str,
) -> None:
    db = SessionLocal()

    try:
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .first()
        )

        if document is None:
            activity.logger.warning(
                "Cannot mark missing document %s as FAILED",
                document_id,
            )
            return

        document.status = "FAILED"
        document.error_message = error_message

        db.commit()

        activity.logger.error(
            "Document %s marked as FAILED: %s",
            document_id,
            error_message,
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


@activity.defn
async def embed_query(
    query: str,
) -> list[float]:

    if not query.strip():
        raise ValueError(
            "Query cannot be empty"
        )

    embeddings = get_embeddings()

    vector = await embeddings.aembed_query(
        query
    )

    activity.logger.info(
        "Generated query embedding"
    )

    return vector

@activity.defn
async def retrieve_chunks(
    query_embedding: list[float],
    top_k: int,
) -> list[dict]:

    if not query_embedding:
        raise ValueError(
            "Query embedding cannot be empty"
        )

    if top_k < 1:
        raise ValueError(
            "top_k must be greater than 0"
        )

    vector_store = get_vector_store()

    results = vector_store._collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=[
            "documents",
            "metadatas",
            "distances",
        ],
    )

    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]
    distances = results.get("distances") or [[]]

    chunks = []

    for index, content in enumerate(documents[0]):

        chunks.append(
            {
                "content": content,
                "metadata": metadatas[0][index],
                "score": float(distances[0][index]),
            }
        )

    activity.logger.info(
        "Retrieved %d chunks",
        len(chunks),
    )

    return chunks

@activity.defn
async def build_context(
    chunks: list[dict],
) -> dict:

    if not chunks:
        raise ValueError(
            "No chunks were retrieved"
        )

    context_parts = []

    for index, chunk in enumerate(
        chunks,
        start=1,
    ):
        metadata = chunk.get(
            "metadata",
            {},
        )

        filename = metadata.get(
            "filename",
            "unknown",
        )

        document_id = metadata.get(
            "document_id",
            "unknown",
        )

        chunk_index = metadata.get(
            "chunk_index",
            index - 1,
        )

        content = chunk.get(
            "content",
            "",
        )

        if not content.strip():
            continue

        context_parts.append(
            (
                f"[Source {index}]\n"
                f"Document: {filename}\n"
                f"Document ID: {document_id}\n"
                f"Chunk: {chunk_index}\n"
                f"Content:\n{content}"
            )
        )

    if not context_parts:
        raise ValueError(
            "Retrieved chunks contained no usable content"
        )

    context = "\n\n---\n\n".join(
        context_parts
    )

    activity.logger.info(
        "Built context from %d chunks",
        len(context_parts),
    )

    return {
        "context": context,
        "chunks": chunks,
    }