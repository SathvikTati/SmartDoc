# PORT-6 Codebase Map

What each file is and what it does.

The frontend has its own pair of documents:
[frontend/CODEBASE.md](frontend/CODEBASE.md) for the module map and
[frontend/WORKFLOW.md](frontend/WORKFLOW.md) for how a question travels
through the UI.

```
port6/
├── config.yaml                 tunable settings (non-secret)
├── .env                        secrets and provider selection
├── alembic/                    database migrations
├── demo/                       runnable demo: corpus, script, walkthrough
├── frontend/                   the React app — the primary UI
└── src/port6/
    ├── config.py               loads config.yaml + .env, resolves providers
    ├── main.py                 FastAPI app: all HTTP endpoints
    ├── frontend/               Streamlit UI, retained as a debugging surface
    └── services/
        ├── files/              upload validation
        ├── parsers/            file -> text + structured blocks
        ├── structure/          blocks -> section tree
        ├── chunking/           sections -> chunks with metadata
        ├── embeddings/         embedding model factory
        ├── llm/                chat model factory, provider error classifier
        ├── vector/             Chroma wrapper
        ├── web/                keyless web search, off by default
        ├── tracing/            Phoenix spans, off by default
        ├── ingestion/          the upload -> READY pipeline
        ├── rag/                pipelines, retrieval, generation, the agent
        ├── documents/          document CRUD
        ├── retrieval/          raw retrieval for /search
        ├── settings/           DB-backed prompts and runtime tuning
        ├── history/            persisted query runs and conversations
        ├── db/                 SQLAlchemy engine and session
        ├── model/              ORM models
        └── schemas/            Pydantic request/response models
```

---

## Entry points

| File | Lines | What it does |
|---|---:|---|
| [`src/port6/main.py`](src/port6/main.py) | 646 | FastAPI app and every endpoint. Documents, `/search`, `/ask`, `/ask/compare`, `/pipelines`, `/chats`, `/history`, `/settings`, `/prompts`. Upload hands ingestion to `BackgroundTasks`; `/ask` resolves a pipeline, then delegates to `rag.system.query_in_chat`. Starts Phoenix tracing in the lifespan, before the first chain is built. |
| [`src/port6/config.py`](src/port6/config.py) | 267 | Loads `config.yaml` and `.env`. Resolves `LLM_PROVIDER` / `EMBEDDINGS_PROVIDER`, requires `OPENAI_API_KEY` only when OpenAI is selected, and namespaces the Chroma collection per embedding model so two embedders never share vectors. |

---

## Retrieval

The centre of the system. A **pipeline** is a named composition of
retrievers; `RagMode` is the coarse family it belongs to.

| File | Lines | What it does |
|---|---:|---|
| [`rag/pipelines.py`](src/port6/services/rag/pipelines.py) | 560 | **The composition, and the runner.** A `Composition` is a set of retrievers plus an optional agent and its tools — not a fixed registry, because three retrievers combine seven ways and naming a handful makes the rest unreachable. `allowed_tools` is what stops the agent widening retrieval. `resolve()` decides what answers a request: an explicit composition, else the mode's historical equivalent, else `defaults.mode`. Presets are shortcuts. |
| [`rag/system.py`](src/port6/services/rag/system.py) | 405 | **The public entry point.** `query()` and `query_in_chat()`. Short-circuits small talk before retrieval, resolves the pipeline, and turns a pipeline failure into a `RagResult` carrying the error rather than raising — so a comparison still renders the others. |
| [`rag/base.py`](src/port6/services/rag/base.py) | 133 | The shared contract. `RagMode`, `RetrievedChunk` (content, provenance, which retriever found it, `url` for web, `uploaded_at` for recency, `derived_from` for a calculation's sources) and `RagResult`. |
| [`rag/retrievers.py`](src/port6/services/rag/retrievers.py) | 452 | The primitives. `semantic_search()` over Chroma, `KeywordIndex` (BM25, cached and rebuilt when the collection size changes, thread-safe) and `fuse()` — Reciprocal Rank Fusion, because a Chroma distance and a BM25 score are not comparable but their ranks are. |
| [`rag/hierarchical.py`](src/port6/services/rag/hierarchical.py) | 348 | Progressive narrowing. Ranks documents from Postgres without touching the chunk index, then searches only inside them, then only inside the chosen sections. |
| [`rag/agent.py`](src/port6/services/rag/agent.py) | 738 | The LangGraph state machine: plan → execute → validate → build context → answer, with a retry edge back to the planner and a one-shot web fallback. A composition with `planner: false` turns off the planner call and the retry, so the cost of planning is measurable. `allowed_tools` restricts what the graph may reach for, so turning the agent on never widens retrieval. |
| [`rag/tools.py`](src/port6/services/rag/tools.py) | 400 | Eight tools, each a LangChain `@tool` so its name, description and schema have one definition. Selected by prompt rather than function calling — the local model emits its choice as JSON content and leaves `tool_calls` empty. `available_tools(allowed)` applies two gates: the server's setting, and the composition's allow-list. |
| [`rag/generation.py`](src/port6/services/rag/generation.py) | 394 | Shared by every pipeline. Builds numbered sources, labels web and calculation sources distinctly, resolves `[n]` markers back to chunks, drops hallucinated numbers, handles `NOT_FOUND`, retries a citation-only answer once, and rewrites a bare topic into a question before generating. |
| [`rag/validation.py`](src/port6/services/rag/validation.py) | 196 | Evidence validation in three bands: reject below `validation.min_overlap`, accept above `validation.skip_model_above` without a model call, ask the model only in between. Scores content words, not the scaffolding of the question. |

### Question shaping

Applied before or around retrieval, in every pipeline.

| File | Lines | What it does |
|---|---:|---|
| [`rag/smalltalk.py`](src/port6/services/rag/smalltalk.py) | 371 | Greetings, thanks, farewells and "what can you do?" answered directly, with no retrieval and no model call. Matching is exact after normalisation, so "hi, how much annual leave?" is treated as the question it is. |
| [`rag/conversation.py`](src/port6/services/rag/conversation.py) | 320 | Decides whether a question continues the conversation or starts a new topic, rewrites a follow-up to stand alone, and picks `fresh` / `combine` / `reuse`. Rules first, so most questions cost no model call, and both the rules and the fallback are biased toward ignoring prior context. |
| [`rag/aggregation.py`](src/port6/services/rag/aggregation.py) | 316 | Cross-document questions. Detects them, separates the topic from the asking-about-the-library scaffolding, retrieves for coverage rather than depth, and groups the context by document with each excerpt clipped. |
| [`rag/calculator.py`](src/port6/services/rag/calculator.py) | 488 | Arithmetic, evaluated by walking an AST against an allow-list — never `eval`, because the expression is written by a model. Runs *after* retrieval so a formula living in a document is applied rather than guessed, records which chunks its figures came from, and rejects a bare literal as the model having done the sum itself. |
| [`rag/conflict.py`](src/port6/services/rag/conflict.py) | 308 | Two documents giving different figures for the same thing. Resolves by upload recency and reports what the older one said, because nothing in a file states that it supersedes another. |

---

## Ingestion path

| File | Lines | What it does |
|---|---:|---|
| [`files/filevalidator.py`](src/port6/services/files/filevalidator.py) | 320 | The upload gates: count, size, MIME, magic bytes, exact-hash duplicate, content-hash duplicate. Saves to `uploads/` with a UUID prefix and inserts the row. |
| [`files/magicbytevalidator.py`](src/port6/services/files/magicbytevalidator.py) | 29 | Reads the real file header. A declared `application/pdf` that does not start with `%PDF` is rejected. |
| [`files/filehash.py`](src/port6/services/files/filehash.py) | 28 | `calculate_sha256` (bytes) and `calculate_content_sha256` (extracted text). The second catches the same document uploaded as PDF and as DOCX. |
| [`parsers/parser.py`](src/port6/services/parsers/parser.py) | 399 | PDF / DOCX / TXT / MD → text **and** blocks, each carrying `page_number` and `heading_level`. Headings come from DOCX styles and Markdown levels where available, and from a shape heuristic otherwise. |
| [`structure/service.py`](src/port6/services/structure/service.py) | 152 | Walks blocks with a heading stack to build the document → section → subsection tree. Keeps heading-only sections so a child's `parent_section_id` never dangles. |
| [`chunking/service.py`](src/port6/services/chunking/service.py) | 197 | Splits **within each section**, so a chunk never straddles two unrelated parts of a policy, and maps offsets back to page numbers. |
| [`ingestion/service.py`](src/port6/services/ingestion/service.py) | 511 | `process_document()` — PROCESSING → chunks → embed → summarise → READY, FAILED on error with the reason recorded. Long documents are summarised map-reduce over windows so the tail is represented. Synchronous on purpose, so FastAPI runs it in a worker thread. |

---

## Shared infrastructure

| File | Lines | What it does |
|---|---:|---|
| [`embeddings/service.py`](src/port6/services/embeddings/service.py) | 27 | `OpenAIEmbeddings` or `OllamaEmbeddings`. Imports live inside the branch so the unused provider is never required. |
| [`llm/service.py`](src/port6/services/llm/service.py) | 30 | The same pattern for the chat model. |
| [`llm/errors.py`](src/port6/services/llm/errors.py) | 220 | Classifies a failure as auth / quota / rate limit / unreachable / missing model / timeout / server, by exception name and message rather than by importing provider SDKs. Turns "processing failed" into "your API key expired", and says whether retrying will help. |
| [`vector/chroma.py`](src/port6/services/vector/chroma.py) | 165 | Chroma wrapper. One shared client built under a lock — ingestion threads used to race constructing it. `count_chunks_by_document()` tallies the whole index in one pass for the document list. |
| [`web/search.py`](src/port6/services/web/search.py) | 131 | Keyless DuckDuckGo search. A web chunk carries a `url` and uses `"web"` as its document id, so it can never be mistaken for a row in the documents table. Returns `[]` on failure rather than raising. |
| [`tracing/service.py`](src/port6/services/tracing/service.py) | 100 | Phoenix spans for every model call. Emits only — the UI runs separately. Off unless `PHOENIX_ENABLED=true`, and every failure inside it is swallowed. |
| [`db/database.py`](src/port6/services/db/database.py) | 40 | SQLAlchemy `engine`, `SessionLocal`, `Base`, and the `db_dependency` FastAPI injects. |
| [`model/models.py`](src/port6/services/model/models.py) | 385 | `Document`, `Setting`, `Prompt`, `Chat`, `QueryRun`. |
| [`documents/service.py`](src/port6/services/documents/service.py) | 239 | List / get / content / summary / structure / reprocess / delete. The list attaches a chunk count from one bulk tally. |
| [`retrieval/service.py`](src/port6/services/retrieval/service.py) | 79 | Raw retrieval behind `/search`. No LLM — used to see what the answerer is being given. |

---

## Settings, prompts and history

| File | Lines | What it does |
|---|---:|---|
| [`settings/defaults.py`](src/port6/services/settings/defaults.py) | 573 | The shipped value for all 25 settings and 8 prompts. Each prompt is a single `template`, not a system/human pair. |
| [`settings/service.py`](src/port6/services/settings/service.py) | 477 | Reads and writes them, cached in process and invalidated on write. Seeding advances a row that still matches its shipped default and never touches an edited one. `_check_variables` rejects an edit that drops a placeholder the pipeline supplies — that failure would otherwise surface as a confidently wrong answer. |
| [`history/service.py`](src/port6/services/history/service.py) | 236 | Records each answered question with its result and the pipeline that produced it, and trims beyond `history.retain_runs`. Best-effort: a history write never turns a successful answer into an error. |
| [`history/chats.py`](src/port6/services/history/chats.py) | 280 | Conversations. Starts or finds the chat a question belongs to, loads the turns a follow-up is resolved against, and rebuilds the previous turn's chunks from its stored result. |

---

## Schemas

| File | Lines | Contents |
|---|---:|---|
| [`schemas/document.py`](src/port6/services/schemas/document.py) | 93 | `DocumentResponse` (with `chunk_count`), content, summary and structure responses |
| [`schemas/query.py`](src/port6/services/schemas/query.py) | 103 | `AskRequest` (question, **pipeline**, mode, top_k, document_ids, chat_id), `CompareRequest` (modes **or** pipelines), `CompareResponse` |
| [`schemas/admin.py`](src/port6/services/schemas/admin.py) | 126 | `PipelineResponse`, `SettingResponse`, `PromptResponse`, `QueryRunDetail`, `ChatSummary`, `ChatDetail` |
| [`schemas/search.py`](src/port6/services/schemas/search.py) | 64 | `SearchRequest`, `SearchResult`, `SearchResponse` |
| [`schemas/common.py`](src/port6/services/schemas/common.py) | 34 | `UtcDatetime` — serialises naive UTC with a zone, so a browser does not read it as local time |

---

## Configuration and migrations

| File | What it holds |
|---|---|
| `config.yaml` | `app`, `upload`, `database`, `parser`, `chunking`, `embeddings`, `llm`, `retrieval`, `summary`, `vector` |
| `.env` | `DATABASE_URL`, `LLM_PROVIDER`, `EMBEDDINGS_PROVIDER`, `OPENAI_API_KEY`, `OLLAMA_*`, `PHOENIX_*` |
| `.env.example` | Template with every supported variable |

| Migration | Adds |
|---|---|
| `189782ecc74c` … `1ea38146104c` | `documents`, then `content`, `status`, `error_message`, `summary` |
| `4535ca6eb9fe` | enterprise metadata columns |
| `cf61a0ac779f` | **drops** the versioning columns |
| `a7c4e1b93d02` | **drops** the descriptive metadata — a file is identified by its filename |
| `b8e2f4a10c37` | `settings`, `prompts`, `query_runs`; ingestion attempt columns |
| `c93a5f27e410` | `chats`, and the conversation columns on `query_runs` |
| `e1d7b40c5a92` | collapses the prompt system/human pair into one `template` |
| `f2a91c6d80b4` | `query_runs.pipeline` — which strategy answered |

---

## Tests

| File | Covers |
|---|---|
| `tests/test_pipelines.py` | The registry, mode compatibility, resolution, ranking |
| `tests/test_retrieval.py` | Fusion, scoping, topic-to-question rewriting |
| `tests/test_aggregation.py` | Detection, coverage, the grouped context |
| `tests/test_conversation.py` | Follow-up resolution and topic switches |
| `tests/test_conflict.py` | Disagreeing documents and recency |
| `tests/test_calculator.py` | The AST sandbox, the gate, provenance |
| `tests/test_smalltalk.py` | What must and must not short-circuit |
| `tests/test_tools_and_web.py` | Tool availability and the web boundary |
| `tests/test_chunking.py`, `test_structure.py` | Ingestion |
| `tests/test_errors_and_prompts.py` | Provider classification, the placeholder guard |
| `tests/test_schemas.py`, `test_chat_cleanup.py` | Serialisation, cascade deletes |

272 tests. The frontend has its own 17 — see
[frontend/CODEBASE.md](frontend/CODEBASE.md).

---

## Where to change things

| Goal | File |
|---|---|
| Add a retriever | `rag/pipelines.py` `RETRIEVERS` + a branch in `_retrieve()` |
| Add a preset | `rag/pipelines.py` `PRESETS` — a shortcut, not a new concept |
| Add an agent tool | `rag/tools.py`, decorate with `@tool` |
| Change the graph | `rag/agent.py` `build_graph()` |
| Change fusion | `rag/retrievers.py` `fuse()` |
| Change what a new chat defaults to | `PUT /settings/defaults.mode`, or the header dialog |
| Change a prompt | `PUT /prompts/{name}` — or `settings/defaults.py` for a new shipped default |
| Change a tuning value | `PUT /settings/{key}` — or `settings/defaults.py` to add one |
| Support a new file type | `parsers/parser.py` + `config.yaml` `allowed_types` |
| Change chunk size | `config.yaml` `chunking` |
| Add a document field | `model/models.py` + a migration + `schemas/document.py` |
| Change which model runs | `.env` only |
| Turn on tracing | `.env` `PHOENIX_ENABLED=true` |
