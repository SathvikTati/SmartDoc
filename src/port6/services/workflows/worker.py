import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from port6.config import temporal_config
from port6.services.workflows.activities import (
    build_context,
    mark_failed,
    mark_processing,
    chunk_document_activity,
    embed_document,
    mark_ready,
    embed_query,
    retrieve_chunks,
)
from port6.services.workflows.document_workflow import (
    DocumentProcessingWorkflow,
)
from port6.services.workflows.query_workflow import (
    DocumentQueryWorkflow,
)


async def main() -> None:

    client = await Client.connect(
        temporal_config["host"],
        namespace=temporal_config["namespace"],
    )

    worker = Worker(
        client,
        task_queue=temporal_config["task_queue"],
        workflows=[
            DocumentProcessingWorkflow,
            DocumentQueryWorkflow,
        ],
        activities=[
            # Document processing
            mark_processing,
            chunk_document_activity,
            embed_document,
            mark_ready,
            mark_failed,

            # RAG
            embed_query,
            retrieve_chunks,
            build_context,
        ],
    )

    print(
        "Temporal worker started on task queue: "
        f"{temporal_config['task_queue']}"
    )

    print("Registered workflows:")
    print(" - DocumentProcessingWorkflow")
    print(" - DocumentQueryWorkflow")

    print("Registered activities:")
    print(" - mark_processing")
    print(" - chunk_document_activity")
    print(" - embed_document")
    print(" - mark_ready")
    print(" - mark_failed")
    print(" - embed_query")
    print(" - retrieve_chunks")

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())