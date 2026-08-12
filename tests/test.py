from port6.services.chunking.service import chunk_document


text = """
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
PORT-6 is a document processing system.

Documents are uploaded through a FastAPI endpoint.
The system validates file size, MIME type and magic bytes.

Documents are parsed into text and stored in PostgreSQL.
The parsed content can later be divided into chunks.

Those chunks will be embedded using OpenAI
and stored in ChromaDB for semantic retrieval.
"""


chunks = chunk_document(
    document_id="test-document-id",
    filename="test.txt",
    content=text,
)


for chunk in chunks:
    print("=" * 80)
    print(chunk.metadata)
    print(chunk.page_content)