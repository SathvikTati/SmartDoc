import os
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette import status

from port6.services.db.database import db_dependency
from port6.services.documents.service import (
    delete_document,
    get_document,
    get_document_content,
    get_document_structure,
    get_document_summary,
    get_documents,
)
from port6.services.files.filevalidator import (
    FileSave,
    validate_files,
)
from port6.services.schemas.document import (
    DocumentContentResponse,
    DocumentResponse,
    DocumentStructureResponse,
    DocumentSummaryResponse,
)
from port6.services.schemas.search import (
    SearchRequest,
    SearchResponse,
)
from port6.services.schemas.query import (
    AskRequest,
    CompareRequest,
    CompareResponse,
)
from port6.services.ingestion.service import process_document
from port6.services.rag.base import RagResult
from port6.services.rag.system import compare_modes, query as rag_query
from port6.services.retrieval.service import search


app = FastAPI(
    title="PORT-6",
    description=(
        "Document ingestion and retrieval, with three selectable "
        "RAG strategies."
    ),
)


# The React frontend is served from its own origin (the Vite dev server in
# development, a static host in production), so the browser needs these
# headers before it will make any call at all. Origins are explicit rather
# than "*": credentials aside, an allowlist is the honest default for an
# internal tool.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "PORT6_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Cheap liveness check, so the UI can tell "API down" from "no data"."""

    return {"status": "ok"}


@app.post(
    "/upload",
    response_model=list[FileSave],
    status_code=status.HTTP_200_OK,
)
async def upload_files(
    files: Annotated[list[UploadFile], File(...)],
    db: db_dependency,
    background_tasks: BackgroundTasks,
):
    documents = await validate_files(
        files,
        db,
    )

    # Ingestion is slow (embedding and summarising), so it runs after the
    # response is sent. process_document is sync, which means FastAPI runs
    # it in a worker thread rather than on the event loop.
    for document in documents:
        background_tasks.add_task(
            process_document,
            str(document["id"]),
        )

    return documents


@app.get(
    "/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(
    db: db_dependency,
):
    return get_documents(db)


@app.get(
    "/documents/{document_id}",
    response_model=DocumentResponse,
)
async def get_document_by_id(
    document_id: UUID,
    db: db_dependency,
):
    return get_document(
        db,
        document_id,
    )


@app.get(
    "/documents/{document_id}/content",
    response_model=DocumentContentResponse,
)
async def get_document_content_by_id(
    document_id: UUID,
    db: db_dependency,
):
    return get_document_content(
        db,
        document_id,
    )


@app.get(
    "/documents/{document_id}/summary",
    response_model=DocumentSummaryResponse,
)
async def get_document_summary_by_id(
    document_id: UUID,
    db: db_dependency,
):
    return get_document_summary(
        db,
        document_id,
    )


@app.get(
    "/documents/{document_id}/structure",
    response_model=DocumentStructureResponse,
)
async def get_document_structure_by_id(
    document_id: UUID,
    db: db_dependency,
):
    return get_document_structure(
        db,
        document_id,
    )


@app.delete(
    "/documents/{document_id}",
    response_model=DocumentResponse,
)
async def delete_document_by_id(
    document_id: UUID,
    db: db_dependency,
):
    return delete_document(
        db,
        document_id,
    )


@app.post(
    "/search",
    response_model=SearchResponse,
)
async def search_documents(
    request: SearchRequest,
):
    results = await search(
        query=request.query,
        top_k=request.top_k,
        mode=request.mode,
    )

    return SearchResponse(
        query=request.query,
        mode=request.mode,
        results=results,
    )


@app.post(
    "/ask",
    response_model=RagResult,
)
async def ask(
    request: AskRequest,
):
    return await rag_query(
        question=request.question,
        mode=request.mode,
        top_k=request.top_k,
    )


@app.post(
    "/ask/compare",
    response_model=CompareResponse,
)
async def ask_compare(
    request: CompareRequest,
):
    """Run one question through several modes for side-by-side comparison."""

    results = await compare_modes(
        question=request.question,
        modes=list(request.modes),
        top_k=request.top_k,
    )

    return CompareResponse(
        question=request.question,
        results=results,
    )


@app.get("/modes")
async def list_modes():
    """The retrieval modes available, for populating a UI selector."""

    from port6.services.rag import agent, hybrid, naive

    return [
        {
            "mode": "naive",
            "label": "Naive RAG",
            "retrieval_method": naive.RETRIEVAL_METHOD,
        },
        {
            "mode": "hybrid",
            "label": "Hybrid + Hierarchical RAG",
            "retrieval_method": hybrid.RETRIEVAL_METHOD,
        },
        {
            "mode": "agentic",
            "label": "Agentic RAG",
            "retrieval_method": agent.RETRIEVAL_METHOD,
        },
    ]