from langchain_core.documents import Document as LangChainDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from port6.config import chunking_config


def chunk_document(
    document_id: str,
    filename: str,
    content: str,
) -> list[LangChainDocument]:

    if not content or not content.strip():
        raise ValueError(
            f"Document {document_id} has no content to chunk"
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunking_config.get(
            "chunk_size",
            1000,
        ),
        chunk_overlap=chunking_config.get(
            "chunk_overlap",
            200,
        ),
        length_function=len,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            "",
        ],
    )

    chunks = splitter.create_documents(
        [content],
    )

    for index, chunk in enumerate(chunks):
        chunk.metadata.update(
            {
                "document_id": document_id,
                "filename": filename,
                "chunk_index": index,
            }
        )

    return chunks