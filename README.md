# PORT-6

PORT-6 is a document ingestion and processing backend built with FastAPI.

The project is designed to accept multiple document formats, validate uploaded files, detect duplicate documents, extract their content, and persist document metadata in PostgreSQL.

The system is being built as a foundation for a future document intelligence / LLM processing pipeline.

---

## Asking Questions

`POST /ask` runs a Temporal workflow that embeds the question, retrieves the
closest chunks, and asks the model to answer from those chunks alone.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "How many days of annual leave do employees get?", "top_k": 5}'
```

```json
{
  "question": "How many days of annual leave do employees get?",
  "answer": "Employees accrue 20 days of paid annual leave per calendar year [1].",
  "answered": true,
  "citations": [
    {
      "number": 1,
      "document_id": "f8f392d1-4670-4a74-8662-e419701067f5",
      "filename": "leave_policy.txt",
      "chunk_index": 0,
      "content": "Acme Corp Leave Policy (2026) ...",
      "score": 0.4227
    }
  ],
  "sources": ["... every chunk that was retrieved ..."]
}
```

### How citations stay honest

- The model is instructed to mark every statement with the `[n]` of the source
  it came from. Those numbers index into `sources`.
- `citations` contains only the sources the answer actually referenced, so a
  caller can render footnotes without re-deriving them.
- A model can cite a number that does not exist. Any `[n]` outside the source
  list is dropped and logged rather than returned as a dead link.
- If the retrieved chunks do not contain the answer, the model replies
  `NOT_FOUND`. The API turns that into `answered: false` with no citations
  instead of guessing.
- If nothing is retrieved at all, the workflow short-circuits to the same
  shape — an empty library is a normal answer, not an error.

`retrieval.max_distance` in `config.yaml` drops weakly-matching chunks before
they ever reach the model. It is `null` (off) by default; tune it against your
own corpus, since the distance scale depends on the embedding model.

---

## Document Summaries

Ingestion generates a summary of each document with the configured chat model
and stores it on the document row.

```bash
curl http://localhost:8000/documents/{document_id}/summary
```

Summarisation is best-effort: if the model fails, the document still finishes
ingesting and stays queryable, with `summary` left null. Long documents are
truncated to `summary.max_input_characters` before being sent to the model.

---

## Model Providers

The chat model and the embedding model are selected independently in `.env`:

```bash
LLM_PROVIDER=ollama          # openai | ollama
EMBEDDINGS_PROVIDER=ollama   # openai | ollama
```

`openai` requires `OPENAI_API_KEY`. `ollama` requires a running Ollama server
(`OLLAMA_BASE_URL`, default `http://localhost:11434`) with the models pulled:

```bash
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
```

`qwen2.5-coder` is a chat model and cannot embed, so `OLLAMA_EMBEDDING_MODEL`
is configured separately.

Each embedding model writes to its own Chroma collection
(`port6_documents_<provider>_<model>`), because OpenAI and Ollama vectors have
different dimensions. Switching `EMBEDDINGS_PROVIDER` therefore requires
re-ingesting documents into the new collection.

See `.env.example` for the full list of settings.

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