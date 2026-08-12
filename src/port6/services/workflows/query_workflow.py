from datetime import timedelta

from temporalio import workflow

from port6.services.schemas.query import QueryInput


@workflow.defn
class DocumentQueryWorkflow:

    @workflow.run
    async def run(
        self,
        request: QueryInput,
    ) -> dict:

        # 1. EMBED QUERY
        query_embedding = await workflow.execute_activity(
            "embed_query",
            request.query,
            start_to_close_timeout=timedelta(
                minutes=2,
            ),
        )

        # 2. RETRIEVE
        chunks = await workflow.execute_activity(
            "retrieve_chunks",
            args=[
                query_embedding,
                request.top_k,
            ],
            start_to_close_timeout=timedelta(
                minutes=2,
            ),
        )

        # 3. BUILD CONTEXT
        context_data = await workflow.execute_activity(
            "build_context",
            chunks,
            start_to_close_timeout=timedelta(
                minutes=1,
            ),
        )

        # Temporary response while
        # GENERATE_ANSWER is not implemented.
        return {
            "chunks": context_data["chunks"],
        }