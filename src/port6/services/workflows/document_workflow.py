from datetime import timedelta

from temporalio import workflow


@workflow.defn
class DocumentProcessingWorkflow:

    @workflow.run
    async def run(
        self,
        document_id: str,
    ) -> str:

        await workflow.execute_activity(
            "mark_processing",
            document_id,
            start_to_close_timeout=timedelta(
                minutes=1,
            ),
        )

        try:

            chunk_count = await workflow.execute_activity(
                "chunk_document_activity",
                document_id,
                start_to_close_timeout=timedelta(
                    minutes=5,
                ),
            )

            embedding_count = await workflow.execute_activity(
                "embed_document",
                document_id,
                start_to_close_timeout=timedelta(
                    minutes=5,
                ),
            )

            await workflow.execute_activity(
                "mark_ready",
                document_id,
                start_to_close_timeout=timedelta(
                    minutes=1,
                ),
            )

            workflow.logger.info(
                "Document %s processed successfully: "
                "%d chunks, %d embeddings",
                document_id,
                chunk_count,
                embedding_count,
            )

            return document_id

        except Exception as exc:

            await workflow.execute_activity(
                "mark_failed",
                document_id,
                str(exc),
                start_to_close_timeout=timedelta(
                    minutes=1,
                ),
            )

            raise