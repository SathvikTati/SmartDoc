# PORT-6 Codebase Map

What each file is and what it does.

```
port6/
├── config.yaml                 tunable settings (non-secret)
├── .env                        secrets and provider selection
├── alembic/                    database migrations
├── demo/                       runnable demo: corpus + run_demo.py
└── src/port6/
    ├── config.py               loads config.yaml + .env, resolves providers
    ├── main.py                 FastAPI app: all HTTP endpoints
    ├── frontend/               Streamlit UI, internal (talks to the API over HTTP)
    └── services/
        ├── files/              upload validation
        ├── parsers/            file -> text + structured blocks
        ├── structure/          blocks -> section tree
        ├── chunking/           sections -> chunks with metadata
        ├── embeddings/         embedding model factory
        ├── llm/                chat model factory
        ├── vector/             Chroma wrapper
        ├── ingestion/          the upload -> READY pipeline
        ├── rag/                the three retrieval modes
        ├── documents/          document CRUD
        ├── retrieval/          raw retrieval for /search (semantic|keyword|hybrid)
        ├── db/                 SQLAlchemy engine and session
        ├── model/              ORM model
        └── schemas/            Pydantic request/response models
```

---

## Entry points

| File | Lines | What it does |
|---|---:|---|
| [`src/port6/main.py`](src/port6/main.py) | 209 | FastAPI app. Endpoints: `/health`, `/upload`, `/documents`, `/documents/{id}`, `/documents/{id}/content`, `/documents/{id}/summary`, `/documents/{id}/structure`, `DELETE /documents/{id}`, `/search`, `/ask`, `/ask/compare`, `/modes`. Sets CORS from `PORT6_CORS_ORIGINS` so the React app can call it. Upload hands ingestion to `BackgroundTasks`; `/ask` delegates to `rag.system.query`. |
| [`src/port6/config.py`](src/port6/config.py) | 307 | Loads `config.yaml` and `.env`. Resolves `LLM_PROVIDER` / `EMBEDDINGS_PROVIDER` (openai \| ollama), requires `OPENAI_API_KEY` only when OpenAI is actually selected, and namespaces the Chroma collection per embedding model so OpenAI and Ollama vectors never share a collection. Exports the `*_config` dicts every service reads. |

---

## Frontend

The **React app in [`frontend/`](frontend/)** is the primary UI — plain
JavaScript, Vite, Tailwind, React Router. It is documented separately in
[frontend/README.md](frontend/README.md), which covers its routes, its module
layout, and how the flat file explorer works.

The Streamlit app below is retained as an internal debugging surface.

| File | Lines | What it does |
|---|---:|---|
| [`frontend/app.py`](src/port6/frontend/app.py) | ~925 | Streamlit UI. Five tabs: **Ask** (mode selector, cited answer, retrieval trace), **Compare modes** (all three side by side with a summary table), **Library** (summaries, delete), **Upload**, **Search**. Renders `[n]` markers as superscript pills, and escapes all document text before display. |
| [`frontend/api.py`](src/port6/frontend/api.py) | 262 | HTTP client. No database or model access of its own, so the UI can point at a remote API via `PORT6_API_URL`. Maps file extensions to MIME types (browsers under-report Markdown) and turns FastAPI error bodies into readable messages. |

---

## Ingestion path

| File | Lines | What it does |
|---|---:|---|
| [`files/filevalidator.py`](src/port6/services/files/filevalidator.py) | 320 | `validate_files()` — the five upload gates: count, size, MIME, magic bytes, exact-hash duplicate, content-hash duplicate. Saves to `uploads/` with a UUID prefix and inserts the document row. |
| [`files/magicbytevalidator.py`](src/port6/services/files/magicbytevalidator.py) | 29 | Reads the real file header. A declared `application/pdf` that does not start with `%PDF` is rejected. |
| [`files/filehash.py`](src/port6/services/files/filehash.py) | 28 | `calculate_sha256` (bytes) and `calculate_content_sha256` (extracted text). The second catches the same document uploaded as PDF and DOCX. |
| [`parsers/parser.py`](src/port6/services/parsers/parser.py) | 399 | PDF / DOCX / TXT / MD → `ParsedDocument` with `.text` **and** `.blocks`. Each `ParsedBlock` carries `page_number` and `heading_level`. Headings come from DOCX styles and Markdown levels where available, and from `detect_heading_level()` (numbered, ALL CAPS, Title Case) for PDF and TXT. |
| [`structure/service.py`](src/port6/services/structure/service.py) | 152 | `build_sections()` — walks blocks with a heading stack to build the document → section → subsection tree. Keeps heading-only sections so children's `parent_section_id` never dangles; `content_sections()` filters to the ones worth chunking. |
| [`chunking/service.py`](src/port6/services/chunking/service.py) | 154 | Splits **within each section**, so a chunk never straddles two unrelated parts of a policy. Stamps the section hierarchy onto every chunk and drops `None` values that Chroma would reject. |
| [`ingestion/service.py`](src/port6/services/ingestion/service.py) | ~330 | `process_document()` — the background pipeline: PROCESSING → chunks → embed → summarise → READY, with FAILED on error. Synchronous on purpose so FastAPI runs it in a worker thread instead of on the event loop. |

---

## Retrieval — the three modes

| File | Lines | What it does |
|---|---:|---|
| [`rag/base.py`](src/port6/services/rag/base.py) | 122 | The shared contract. `RagMode` enum, `RetrievedChunk` (content + full provenance + which retriever found it), `RagResult` (answer, citations, retrieved_chunks, retrieval_method, latency_ms, metadata, debug). `chunk_from_metadata()` tolerates missing fields so older documents still retrieve. |
| [`rag/system.py`](src/port6/services/rag/system.py) | 120 | **The public entry point.** `query(question, mode, top_k)` dispatches to a mode; `compare_modes()` runs several. A failing mode returns a `RagResult` carrying the error rather than raising, so a comparison still renders the others. |
| [`rag/retrievers.py`](src/port6/services/rag/retrievers.py) | 358 | The primitives. `semantic_search()` (Chroma, optional `where`), `KeywordIndex` (BM25 built from stored chunks, cached and rebuilt when the collection size changes, thread-safe), and `fuse()` — Reciprocal Rank Fusion. |
| [`rag/hierarchical.py`](src/port6/services/rag/hierarchical.py) | 325 | Progressive narrowing. `select_documents()` ranks documents from Postgres without touching the chunk index; `select_sections()` searches only inside them; `retrieve_in_sections()` retrieves only inside the chosen sections. |
| [`rag/generation.py`](src/port6/services/rag/generation.py) | 291 | Shared by all modes. Builds numbered sources with document/section/page headers, prompts for `[n]` citations, resolves them back to chunks, drops hallucinated numbers, handles the `NOT_FOUND` sentinel, and retries citation-only answers once. |
| [`rag/validation.py`](src/port6/services/rag/validation.py) | 190 | Evidence validation. Lexical overlap check first, then a model verdict of `SUFFICIENT` / `INSUFFICIENT`. Falls back to the lexical signal if the validator itself fails. |
| [`rag/naive.py`](src/port6/services/rag/naive.py) | 82 | **Mode 1.** Vector search → top-k → LLM. Unchanged baseline, kept deliberately limited. |
| [`rag/hybrid.py`](src/port6/services/rag/hybrid.py) | 183 | **Mode 2.** Runs hierarchical and flat hybrid retrieval, fuses everything with RRF, and reranks so chunks two retrievers agreed on come first. |
| [`rag/tools.py`](src/port6/services/rag/tools.py) | 228 | The agent's five tools, each an independently testable async callable returning `{"chunks", "info"}`, plus a registry with descriptions the planner reasons over. `document_lookup` returns the catalogue — filenames with clipped summaries — **as a chunk**, since only chunks reach the answer generator. |
| [`rag/agent.py`](src/port6/services/rag/agent.py) | 540 | **Mode 3.** The LangGraph state machine: `retrieval_planner → tool_execution → evidence_validation → context_builder → answer_generation`, with a retry edge back to the planner. Model-driven planning with a rule-based fallback; retries always widen by rule. |

---

## Shared infrastructure

| File | Lines | What it does |
|---|---:|---|
| [`embeddings/service.py`](src/port6/services/embeddings/service.py) | 27 | Returns `OpenAIEmbeddings` or `OllamaEmbeddings` based on `EMBEDDINGS_PROVIDER`. Imports are inside the branch so the unused provider is never required. |
| [`llm/service.py`](src/port6/services/llm/service.py) | 30 | Same pattern for the chat model: `ChatOpenAI` or `ChatOllama`. |
| [`llm/client.py`](src/port6/services/llm/client.py) | 7 | **Dead code — recommend deleting.** Creates a bare `AsyncOpenAI` client. Nothing imports it, and it raises `OpenAIError` on import when running Ollama-only, because `OPENAI_API_KEY` is legitimately unset. |
| [`vector/chroma.py`](src/port6/services/vector/chroma.py) | 107 | Chroma wrapper. `get_vector_store()` returns one shared client built under a lock — ingestion threads used to race constructing it. `store_chunks()` writes via `add_documents` so the configured embedder is used; `delete_document_chunks()`, `search_documents()`, `get_collection_count()`. |
| [`db/database.py`](src/port6/services/db/database.py) | 40 | SQLAlchemy `engine`, `SessionLocal`, `Base`, and the `db_dependency` FastAPI injects. |
| [`model/models.py`](src/port6/services/model/models.py) | 76 | The `Document` ORM model: identity, hashes, storage path, content, processing status, summary. A file is identified by its filename — nothing classifies it further. |
| [`documents/service.py`](src/port6/services/documents/service.py) | 95 | List / get / content / summary / delete. Delete removes the chunks, the file and the row. |
| [`retrieval/service.py`](src/port6/services/retrieval/service.py) | 38 | Plain semantic search behind `/search`. No LLM, used to inspect what the answerer is being given. |

---

## Schemas

| File | Lines | Contents |
|---|---:|---|
| [`schemas/document.py`](src/port6/services/schemas/document.py) | 47 | `DocumentResponse`, `DocumentContentResponse`, `DocumentSummaryResponse` |
| [`schemas/query.py`](src/port6/services/schemas/query.py) | 47 | `AskRequest` (question, top_k, **mode**), `CompareRequest`, `CompareResponse` |
| [`schemas/search.py`](src/port6/services/schemas/search.py) | 26 | `SearchRequest`, `SearchResult`, `SearchResponse` |

---

## Configuration and migrations

| File | What it holds |
|---|---|
| `config.yaml` | `app`, `upload` (limits, allowed types), `database`, `parser`, `chunking` (size/overlap), `embeddings`, `llm`, `retrieval` (`max_distance`), `summary`, `vector` |
| `.env` | `DATABASE_URL`, `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER`, `OPENAI_API_KEY`, `OLLAMA_*`, `LLM_TEMPERATURE` |
| `.env.example` | Template with every supported variable |

| Migration | Adds |
|---|---|
| `189782ecc74c` | `documents` table |
| `fdec5876f889` | `content` |
| `25c5298b624a` | `status` |
| `3ceb3fc9e653` | `error_message` |
| `1ea38146104c` | `summary` |
| `4535ca6eb9fe` | `document_title`, `document_type`, `document_key`, `version`, `effective_from`, `effective_to`, `lifecycle_status`, `department` + indexes |
| `cf61a0ac779f` | **drops** `document_key`, `version`, `effective_from`, `effective_to`, `lifecycle_status` (versioning removed) |
| `a7c4e1b93d02` | **drops** `document_title`, `document_type`, `department` (a file is identified by its filename) |

---

## Where to change things

| Goal | File |
|---|---|
| Add a retrieval mode | `rag/` + register in `rag/system.py` `RUNNERS` |
| Add an agent tool | `rag/tools.py` `TOOLS` registry |
| Change the graph | `rag/agent.py` `build_graph()` |
| Change the answer prompt | `rag/generation.py` `ANSWER_PROMPT` |
| Change fusion | `rag/retrievers.py` `fuse()` |
| Support a new file type | `parsers/parser.py` `parsers` dict + `config.yaml` `allowed_types` |
| Change chunk size | `config.yaml` `chunking` |
| Add a document field | `model/models.py` + a migration + `schemas/document.py` |
| Swap model provider | `.env` `LLM_PROVIDER` / `EMBEDDINGS_PROVIDER` |
