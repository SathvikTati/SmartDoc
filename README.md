# PORT-6

PORT-6 is a document ingestion and processing backend built with FastAPI.

The project is designed to accept multiple document formats, validate uploaded files, detect duplicate documents, extract their content, and persist document metadata in PostgreSQL.

The system is being built as a foundation for a future document intelligence / LLM processing pipeline.

---

## Current Features

### File Upload

- Upload multiple files through a FastAPI endpoint.
- Maximum of 5 files per request.
- Maximum file size of 5 MB per file.
- Safe filename handling.
- Uploaded files are stored on disk with UUID-based filenames.

### File Validation

Uploaded files go through multiple validation stages:

1. File count validation
2. File size validation
3. MIME type validation
4. Magic-byte validation
5. Exact file duplicate detection
6. Document content duplicate detection

Supported formats:

- PDF
- DOCX
- DOC
- TXT
- Markdown

### Magic-Byte Validation

The declared MIME type is not trusted by itself.

The application checks the actual file header for supported binary formats.

For example:

```text
PDF
    ↓
%PDF