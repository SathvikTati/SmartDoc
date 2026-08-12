from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, UploadFile
from starlette import status

from port6.config import temporal_config
from port6.services.db.database import db_dependency
from port6.services.documents.service import (
    delete_document,
    get_document,
    get_document_content,
    get_documents,
)
from port6.services.files.filevalidator import (
    FileSave,
    validate_files,
)
from port6.services.schemas.document import (
    DocumentContentResponse,
    DocumentResponse,
)
from port6.services.schemas.search import (
    SearchRequest,
    SearchResponse,
)
from port6.services.schemas.query import (
    AskRequest,
    QueryInput,
)
from port6.services.retrieval.service import search
from port6.services.workflows.client import (
    get_temporal_client,
)
from port6.services.workflows.document_workflow import (
    DocumentProcessingWorkflow,
)
from port6.services.workflows.query_workflow import (
    DocumentQueryWorkflow,
)


app = FastAPI()


@app.post(
    "/upload",
    response_model=list[FileSave],
    status_code=status.HTTP_200_OK,
)
async def upload_files(
    files: Annotated[list[UploadFile], File(...)],
    db: db_dependency,
):
    documents = await validate_files(
        files,
        db,
    )

    temporal_client = await get_temporal_client()

    for document in documents:

        document_id = document["id"]

        await temporal_client.start_workflow(
            DocumentProcessingWorkflow.run,
            str(document_id),
            id=f"document-processing-{document_id}",
            task_queue=temporal_config["task_queue"],
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
    results = search(
        query=request.query,
        top_k=request.top_k,
    )

    return SearchResponse(
        query=request.query,
        results=results,
    )

@app.post("/ask")
async def ask(
    request: AskRequest,
):
    temporal_client = await get_temporal_client()

    workflow_id = (
        f"document-query-{uuid4()}"
    )

    result = await temporal_client.execute_workflow(
        DocumentQueryWorkflow.run,
        QueryInput(
            query=request.question,
            top_k=request.top_k,
        ),
        id=workflow_id,
        task_queue=temporal_config["task_queue"],
    )

    return {
        "question": request.question,
        "context": result,
    }