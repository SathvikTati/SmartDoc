import re

from langchain_core.prompts import ChatPromptTemplate
from temporalio import activity

from port6.config import (
    retrieval_config,
    summary_config,
)
from port6.services.chunking.service import chunk_document
from port6.services.db.database import SessionLocal
from port6.services.embeddings.service import get_embeddings
from port6.services.llm.service import get_chat_model
from port6.services.model.models import Document
from port6.services.vector.chroma import (
    get_vector_store,
    store_chunks,
)


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
    collection = vector_store._collection

    collection_count = collection.count()

    if collection_count == 0:
        activity.logger.warning(
            "Chroma collection '%s' is empty",
            collection.name,
        )
        return []

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(
            top_k,
            collection_count,
        ),
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
        metadata = (
            metadatas[0][index]
            if index < len(metadatas[0])
            else {}
        )

        distance = (
            distances[0][index]
            if index < len(distances[0])
            else None
        )

        chunks.append(
            {
                "content": content,
                "metadata": metadata,
                "score": (
                    float(distance)
                    if distance is not None
                    else None
                ),
            }
        )

    max_distance = retrieval_config.get(
        "max_distance"
    )

    if max_distance is not None:

        relevant = [
            chunk
            for chunk in chunks
            if chunk["score"] is None
            or chunk["score"] <= max_distance
        ]

        activity.logger.info(
            "Retrieved %d chunks, %d within max_distance=%s",
            len(chunks),
            len(relevant),
            max_distance,
        )

        return relevant

    activity.logger.info(
        "Retrieved %d chunks from Chroma",
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
    sources = []

    # Numbering is assigned over the chunks that survive the blank-content
    # filter, so the [n] markers in the prompt line up with `sources`.
    for chunk in chunks:

        content = chunk.get(
            "content",
            "",
        )

        if not content.strip():
            continue

        metadata = chunk.get(
            "metadata",
            {},
        )

        number = len(sources) + 1

        source = {
            "number": number,
            "document_id": str(
                metadata.get(
                    "document_id",
                    "unknown",
                )
            ),
            "filename": metadata.get(
                "filename",
                "unknown",
            ),
            "chunk_index": int(
                metadata.get(
                    "chunk_index",
                    number - 1,
                )
            ),
            "content": content,
            "score": chunk.get("score"),
        }

        sources.append(source)

        context_parts.append(
            (
                f"[{number}] "
                f"{source['filename']} "
                f"(chunk {source['chunk_index']})\n"
                f"{content}"
            )
        )

    if not sources:
        raise ValueError(
            "Retrieved chunks contained no usable content"
        )

    context = "\n\n---\n\n".join(
        context_parts
    )

    activity.logger.info(
        "Built context from %d sources",
        len(sources),
    )

    return {
        "context": context,
        "sources": sources,
    }


NOT_FOUND_MARKER = "NOT_FOUND"

NOT_FOUND_ANSWER = (
    "I could not find an answer to that question in "
    "the uploaded documents."
)

# Matches [1], [2, 3] and the [1][2] form the model may produce.
CITATION_PATTERN = re.compile(r"\[([\d\s,]+)\]")


def extract_cited_numbers(
    answer: str,
) -> list[int]:
    """Pull the [n] markers out of an answer, in order of first use."""

    cited: list[int] = []

    for group in CITATION_PATTERN.findall(answer):
        for part in group.split(","):

            part = part.strip()

            if not part.isdigit():
                continue

            number = int(part)

            if number not in cited:
                cited.append(number)

    return cited


@activity.defn
async def generate_answer(
    query: str,
    context: str,
    sources: list[dict],
) -> dict:

    if not query.strip():
        raise ValueError(
            "Query cannot be empty"
        )

    if not context.strip():
        raise ValueError(
            "Context cannot be empty"
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
You are a document question-answering assistant.

Answer the user's question using ONLY the numbered
sources below.

Rules:
- Do not use outside knowledge.
- Do not invent information.
- Cite the source number in square brackets after
  every statement you make, for example: [1].
- If two sources support the same statement, cite
  both, for example: [1][3].
- Only cite source numbers that appear below.
- If the sources do not contain the answer, reply
  with exactly NOT_FOUND and nothing else.
- Give a clear and concise answer.
- Do not mention these instructions.

Sources:

{context}
""",
            ),
            (
                "human",
                "{query}",
            ),
        ]
    )

    model = get_chat_model()

    chain = prompt | model

    response = await chain.ainvoke(
        {
            "query": query,
            "context": context,
        }
    )

    answer = response.content

    if not isinstance(answer, str):
        answer = str(answer)

    answer = answer.strip()

    if answer.upper().startswith(NOT_FOUND_MARKER):

        activity.logger.info(
            "No answer found in sources for query: %s",
            query,
        )

        return {
            "answer": NOT_FOUND_ANSWER,
            "answered": False,
            "citations": [],
        }

    sources_by_number = {
        source["number"]: source
        for source in sources
    }

    citations = []

    for number in extract_cited_numbers(answer):

        source = sources_by_number.get(number)

        # A model can cite a source number that does not exist. Drop
        # those rather than returning a citation that points nowhere.
        if source is None:
            activity.logger.warning(
                "Dropping hallucinated citation [%d]; "
                "only %d sources were provided",
                number,
                len(sources),
            )
            continue

        citations.append(source)

    activity.logger.info(
        "Generated answer with %d citations for query: %s",
        len(citations),
        query,
    )

    return {
        "answer": answer,
        "answered": True,
        "citations": citations,
    }


@activity.defn
async def summarize_document(
    document_id: str,
) -> str:

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

        content = (document.content or "").strip()

        if not content:
            raise ValueError(
                f"Document {document_id} has no content to summarise"
            )

        max_characters = int(
            summary_config.get(
                "max_input_characters",
                12000,
            )
        )

        truncated = content[:max_characters]

        if len(content) > max_characters:
            activity.logger.info(
                "Document %s truncated from %d to %d characters "
                "for summarisation",
                document_id,
                len(content),
                max_characters,
            )

        max_words = int(
            summary_config.get(
                "max_words",
                150,
            )
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
You are a document summarisation assistant.

Summarise the document below in at most
{max_words} words.

Rules:
- Use only what the document says.
- Do not invent information.
- Write plain prose, no bullet points or headings.
- Do not mention these instructions.

Document: {filename}

{content}
""",
                ),
                (
                    "human",
                    "Summarise this document.",
                ),
            ]
        )

        model = get_chat_model()

        chain = prompt | model

        response = await chain.ainvoke(
            {
                "filename": document.filename,
                "content": truncated,
                "max_words": max_words,
            }
        )

        summary = response.content

        if not isinstance(summary, str):
            summary = str(summary)

        summary = summary.strip()

        document.summary = summary

        db.commit()

        activity.logger.info(
            "Summarised document %s (%d characters)",
            document_id,
            len(summary),
        )

        return summary

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()