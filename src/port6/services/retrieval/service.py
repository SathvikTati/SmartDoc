from port6.services.schemas.search import (
    SearchResult,
)
from port6.services.vector.chroma import (
    search_documents,
)


def search(
    query: str,
    top_k: int = 5,
) -> list[SearchResult]:

    results = search_documents(
        query=query,
        top_k=top_k,
    )

    response = []

    for document, score in results:

        response.append(
            SearchResult(
                document_id=document.metadata[
                    "document_id"
                ],
                filename=document.metadata[
                    "filename"
                ],
                chunk_index=document.metadata[
                    "chunk_index"
                ],
                content=document.page_content,
                score=float(score),
            )
        )

    return response