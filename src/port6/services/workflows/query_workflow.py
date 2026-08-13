from datetime import timedelta

from temporalio import workflow

from port6.services.schemas.query import QueryInput


NO_RESULTS_ANSWER = (
    "I could not find anything relevant to that question "
    "in the document library."
)


@workflow.defn
class DocumentQueryWorkflow:

    @workflow.run
    async def run(
        self,
        request: QueryInput,
    ) -> dict:

        # -------------------------
        # 1. EMBED QUERY
        # -------------------------

        query_embedding = await workflow.execute_activity(
            "embed_query",
            request.query,
            start_to_close_timeout=timedelta(
                minutes=2,
            ),
        )

        # -------------------------
        # 2. RETRIEVE
        # -------------------------

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

        # An empty library, or a question nothing matches, is a normal
        # outcome rather than a workflow failure.
        if not chunks:

            workflow.logger.info(
                "No chunks retrieved for query: %s",
                request.query,
            )

            return {
                "answer": NO_RESULTS_ANSWER,
                "answered": False,
                "citations": [],
                "sources": [],
            }

        # -------------------------
        # 3. BUILD CONTEXT
        # -------------------------

        context_data = await workflow.execute_activity(
            "build_context",
            chunks,
            start_to_close_timeout=timedelta(
                minutes=1,
            ),
        )

        # -------------------------
        # 4. GENERATE ANSWER
        # -------------------------

        result = await workflow.execute_activity(
            "generate_answer",
            args=[
                request.query,
                context_data["context"],
                context_data["sources"],
            ],
            start_to_close_timeout=timedelta(
                minutes=5,
            ),
        )

        return {
            "answer": result["answer"],
            "answered": result["answered"],
            "citations": result["citations"],
            "sources": context_data["sources"],
        }
