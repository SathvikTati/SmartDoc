import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette import status

from port6.services.db.database import db_dependency
from port6.services.documents.service import (
    delete_document,
    documents_needing_attention,
    get_document,
    get_document_content,
    get_document_structure,
    get_document_summary,
    get_documents,
    prepare_reprocess,
)
from port6.services.history import service as history
from port6.services.schemas.admin import (
    PromptResponse,
    PromptUpdate,
    QueryRunDetail,
    QueryRunPage,
    SettingResponse,
    SettingUpdate,
)
from port6.services.settings import service as settings_service
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


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Seed settings and prompts before the first request.

    Only inserts rows that are missing, so an edited prompt survives a
    restart. A failure here is logged rather than fatal — the services fall
    back to the code defaults, which are the same values being seeded.
    """

    try:
        settings_service.seed()
        logger.info("Settings and prompts seeded")

    except Exception as exc:
        logger.warning(
            "Could not seed settings and prompts, using code defaults: %s",
            exc,
        )

    yield


app = FastAPI(
    title="PORT-6",
    description=(
        "Document ingestion and retrieval, with three selectable "
        "RAG strategies."
    ),
    lifespan=lifespan,
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
    "/documents/attention",
    response_model=list[DocumentResponse],
)
async def list_documents_needing_attention(
    db: db_dependency,
):
    """Documents that failed, or that indexed without a summary.

    Declared before `/documents/{document_id}` so "attention" is not
    parsed as a UUID.
    """

    return documents_needing_attention(db)


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


@app.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentResponse,
)
async def reprocess_document(
    document_id: UUID,
    db: db_dependency,
    background_tasks: BackgroundTasks,
):
    """Run a document through ingestion again.

    The uploaded file is kept even when processing fails, so a document
    that broke on a stopped model server or an expired key can be picked
    up again once that is fixed.
    """

    document = prepare_reprocess(db, document_id)

    background_tasks.add_task(
        process_document,
        str(document.id),
    )

    return document


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
    result = await rag_query(
        question=request.question,
        mode=request.mode,
        top_k=request.top_k,
        document_ids=(
            [str(value) for value in request.document_ids]
            if request.document_ids
            else None
        ),
    )

    # Recorded after the fact and best-effort: a history write must never
    # turn a successful answer into a failed request.
    run_id = history.record_run(
        question=request.question,
        mode=request.mode.value,
        top_k=request.top_k,
        result=result,
    )

    if run_id:
        result.metadata["run_id"] = run_id

    return result


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
        document_ids=(
            [str(value) for value in request.document_ids]
            if request.document_ids
            else None
        ),
    )

    return CompareResponse(
        question=request.question,
        results=results,
    )


# -------------------------------------------------------------------
# Query history
# -------------------------------------------------------------------

@app.get(
    "/history",
    response_model=QueryRunPage,
)
async def list_history(
    db: db_dependency,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    mode: str | None = None,
    answered: bool | None = None,
):
    """Past questions, newest first. Summaries only."""

    return history.list_runs(
        db,
        limit=limit,
        offset=offset,
        mode=mode,
        answered=answered,
    )


@app.get(
    "/history/{run_id}",
    response_model=QueryRunDetail,
)
async def get_history_run(
    run_id: UUID,
    db: db_dependency,
):
    """One past question with the full result it originally returned."""

    return history.get_run(db, run_id)


@app.delete(
    "/history/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_history_run(
    run_id: UUID,
    db: db_dependency,
):
    history.delete_run(db, run_id)


@app.delete("/history")
async def clear_history(
    db: db_dependency,
):
    return {"deleted": history.clear_runs(db)}


# -------------------------------------------------------------------
# Settings and prompts
# -------------------------------------------------------------------

@app.get(
    "/settings",
    response_model=list[SettingResponse],
)
async def list_settings():
    """Runtime-tunable values. Provider and model choices live in .env."""

    return settings_service.list_settings()


@app.put(
    "/settings/{key}",
    response_model=SettingResponse,
)
async def update_setting(
    key: str,
    request: SettingUpdate,
):
    try:
        return settings_service.update_setting(key, request.value)

    except settings_service.UnknownSetting:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No setting named {key!r}",
        )


@app.get(
    "/prompts",
    response_model=list[PromptResponse],
)
async def list_prompts():
    """The live prompts, with the text each one shipped with."""

    return settings_service.list_prompts()


@app.put(
    "/prompts/{name}",
    response_model=PromptResponse,
)
async def update_prompt(
    name: str,
    request: PromptUpdate,
):
    try:
        return settings_service.update_prompt(
            name,
            system=request.system,
            human=request.human,
        )

    except settings_service.UnknownPrompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No prompt named {name!r}",
        )

    except settings_service.InvalidPrompt as exc:
        # A prompt missing a placeholder would silently drop the context or
        # the question, so it is rejected here rather than at request time.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@app.post(
    "/prompts/{name}/reset",
    response_model=PromptResponse,
)
async def reset_prompt(name: str):
    """Restore a prompt to the text the release shipped with."""

    try:
        return settings_service.reset_prompt(name)

    except settings_service.UnknownPrompt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No prompt named {name!r}",
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