# PORT-6

PORT-6 is a document ingestion and processing backend built with FastAPI.

The project is designed to accept multiple document formats, validate uploaded files, detect duplicate documents, extract their content, and persist it in PostgreSQL. A document is identified by its filename — nothing tries to classify it further.

The system is being built as a foundation for a future document intelligence / LLM processing pipeline.

## Documentation

| Document | What it covers |
|---|---|
| [WORKFLOW.md](WORKFLOW.md) | How data flows: the ingestion pipeline and all three query pipelines, stage by stage |
| [CODEBASE.md](CODEBASE.md) | What every file is and does, plus where to change things |
| [WALKTHROUGH.md](WALKTHROUGH.md) | One document and one question traced end to end, with real observed values |
| [demo/README.md](demo/README.md) | Runnable demo: 6-document corpus, 6 scenarios, and what each shows |
| [frontend/README.md](frontend/README.md) | The React frontend: routes, structure, and how it maps onto the API |

---

## Running It

Two processes:

```bash
# 1. API (also runs ingestion in background threads)
uv run uvicorn port6.main:app --reload

# 2. Frontend
cd frontend && npm install && npm run dev
```

The UI opens on http://localhost:5173, which lands on **Ask**. It talks to
the API over HTTP; in development `/api/*` is proxied to
`http://localhost:8000`, and you can point that elsewhere with
`PORT6_API_URL`.

A production build talks to the API directly, so the origin must be in the
API's CORS allowlist:

```bash
PORT6_CORS_ORIGINS=https://port6.internal uv run uvicorn port6.main:app
VITE_API_URL=https://port6.example npm --prefix frontend run build
```

Neither process has authentication, so keep both on localhost or behind
something that does.

### The React frontend

Plain JavaScript — React 19, Vite, Tailwind, React Router. No TypeScript.

- **Ask** (the home page) — cited answers. Every question is an independent
  investigation with its own answer, sources, evidence panel and retrieval
  trace; past questions are listed rather than stacked into a chat transcript.
- **Files** — the document library as a desktop-style file manager: every
  document in one flat list, details and icon views, range and multi-select,
  right-click menus, keyboard shortcuts, sorting, filtering, and
  drag-and-drop upload. No folders — PORT-6 stores documents flat, so any
  folder here would have been invented.
- **Files → document** — file facts, generated summary, chunk and page counts,
  and the heading tree recovered from the file.
- **Search** — raw chunk retrieval with no model involved, in semantic,
  keyword or hybrid mode, showing which retriever found what and at what rank.
- **Compare** — the same question through all three modes, with a metric
  table, the three answers, and each mode's trace.

### Streamlit (internal)

The original Streamlit UI is still there for debugging:

```bash
uv run streamlit run src/port6/frontend/app.py --server.address localhost
```

---

## Configuration

Three places, split by how often a value changes and what it affects.

| Where | Holds | Changed by |
|---|---|---|
| `.env` | Everything about which model to call: providers, model names, temperature, API key, `OLLAMA_BASE_URL`, `DATABASE_URL`, CORS origins | Editing the file and restarting |
| **Database** | The four prompts, plus runtime tuning: chunk size and overlap, `retrieval.max_distance`, summary limits, agent attempts and catalogue size, validation thresholds, history retention | `GET/PUT /settings`, `GET/PUT /prompts` — live on the next request |
| `config.yaml` | Deploy-time facts: upload limits and allowed types, the Chroma path and collection | Editing the file and restarting |

Provider choice is deliberately *not* runtime-tunable: switching embedding
models changes the vector dimension and therefore the Chroma collection, so
it means re-ingesting.

Prompts are seeded from the code defaults on startup and only ever inserted,
so an edit survives a restart. An edit that drops a placeholder the pipeline
supplies — `{context}`, `{query}` — is rejected with a 422, because that
failure would otherwise show up as a confidently wrong answer rather than an
error.

```bash
curl http://localhost:8000/settings
curl -X PUT http://localhost:8000/settings/chunking.chunk_size \
  -H 'Content-Type: application/json' -d '{"value": 1200}'

curl http://localhost:8000/prompts
curl -X POST http://localhost:8000/prompts/answer_generation/reset
```

---

## Tests

```bash
uv run pytest
```

53 tests over the pure logic the pipeline turns on: heading detection and
the section tree, chunk boundaries and the page a chunk is cited with, RRF
fusion, citation extraction and hallucination-dropping, evidence overlap,
provider-failure classification, and the prompt-edit guard.

---

## Retrieval Modes

The same question can be answered by three progressively more capable
retrieval strategies. They share ingestion, embeddings, vector store, prompt
and citation handling, so the only thing that differs is retrieval.

```python
from port6.services.rag.system import query

result = await query(
    "How much annual leave do employees get?",
    mode="naive",   # naive | hybrid | agentic
    top_k=5,
)
```

Every mode returns the same `RagResult`: `answer`, `answered`, `citations`,
`retrieved_chunks`, `retrieval_method`, `latency_ms`, `metadata`, `debug`.

### 1. Naive RAG

`query → vector search → top-k → LLM → cited answer`

The original pipeline, unchanged. No keyword search and no hierarchy. It is
the baseline, and its failures are the point.

### 2. Hybrid + Hierarchical RAG

- **Hybrid**: semantic search and BM25 run in parallel and are combined with
  Reciprocal Rank Fusion. RRF is used rather than averaging scores because
  the two are incomparable — Chroma returns a distance where lower is better,
  BM25 an unbounded score where higher is better. Ranks compare; scores do
  not. A chunk both retrievers found accumulates both contributions and rises.
- **Hierarchical**: three narrowing stages. Stage 1 ranks *documents* from the
  database (filename and summary) without touching the chunk index. Stage 2
  searches for sections only inside those documents. Stage 3 retrieves chunks
  only inside those sections.

Hybrid also detects **library-wide questions** — *"which documents mention
probation?"*, *"compare X across all documents"* — and switches to coverage
retrieval: the best chunks from *each* matching document rather than the
best chunks overall. Plain top-k cannot answer these, because all five
chunks can come from one document.

### 3. Agentic RAG (LangGraph)

```
retrieval_planner → tool_execution
        ^                  |
        +---- retry ---- evidence_validation
                           |
                    context_builder → answer_generation
```

The agent picks from eight tools — `semantic_search`, `keyword_search`,
`hybrid_search`, `hierarchical_search`, `aggregate_search`,
`document_lookup`, plus `calculate` for arithmetic and `web_search` for
the public internet — based on the question. If evidence validation finds the retrieved context thin, it plans
again with a wider strategy rather than answering anyway (bounded by
the `agent.max_attempts` setting).

Only the tools chosen and the plan's one-line reason are exposed, never the
model's private reasoning.

**Arithmetic** is not left to the model, which is unreliable at it and
confidently wrong when it slips. Expressions are evaluated through an AST
walker rather than `eval` — the expression is written by a model, so it is
untrusted input.

The sum runs *after* retrieval, in every mode, so naive and hybrid handle
"I have taken 8 days, how many are left?" without an agent in front of
them, and a formula that lives in the document (`overtime pay = rate ×
1.5 × hours`) is applied rather than guessed at. Selecting the
`calculate` tool is how the agent signals a question needs arithmetic;
the tool itself only evaluates a query that is already an expression,
because before retrieval there are no figures to work from.

The result is offered as a numbered source labelled `CALCULATION`, and it
records which chunks its figures came from — so citing the sum also
credits the policy that supplied the entitlement, rather than leaving it
marked retrieved-but-unused.

**`web_search`** is keyless (DuckDuckGo; Google has no keyless API) and
**off by default**, because an answer citing the internet is a different
promise from one citing only your documents. Turn it on with
`PUT /settings/web.enabled`. Web sources are labelled in the context, in
the citations and in the UI, and a question scoped to specific documents
never reaches the web at all.

## Tracing

An answer is several model calls behind one response — resolve the
follow-up, plan the tools, validate the evidence, write the expression,
generate the answer. Logs show the outcome, not the prompt that caused
it, so "why did it pick that tool?" has no answer in them.

[Phoenix](https://github.com/Arize-ai/phoenix) records each call as a
span with its prompt, completion, latency and token counts, and the
LangGraph run as the trace around them.

```bash
# the UI, in its own process — Python 3.12, the server does not import on 3.11
uvx --python 3.12 --from arize-phoenix phoenix serve

PHOENIX_ENABLED=true uv run uvicorn port6.main:app --reload
```

Then open <http://localhost:6006>. This process only emits spans; it does
not host the UI, which is why the dependency is `arize-phoenix-otel` and
not the server package. Off by default, and every failure inside it is
swallowed — observability that can take the service down is worse than
none.

---

## Chunk Metadata

Structure survives parsing so retrieval can use it. Each chunk carries:

`document_id` · `chunk_id` · `filename` · `chunk_index` · `page_number` ·
`section_id` · `section_title` · `section_path` · `parent_section_id` ·
`section_level`

Headings come from real structure where the format provides it (DOCX styles,
Markdown levels) and from a shape heuristic where it does not (PDF, TXT).
Page numbers are attached per page during PDF parsing, before pages are
joined. Chunks are cut *inside* a section, so one never straddles two
unrelated parts of a policy.

Documents ingested before a field existed simply leave it `None`; retrieval
degrades rather than failing.

---

## Asking Questions

`POST /ask` runs the selected mode and returns the answer with citations
resolved back to the chunks that support it.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is control SEC-4412?",
       "mode": "hybrid", "top_k": 5}'
```

`POST /ask/compare` runs one question through several modes at once, which is
what the **Compare** page uses. `GET /modes` lists what is available.

Every question belongs to a conversation. Pass `chat_id` to continue one,
and a follow-up is resolved against its earlier turns — *"what about sick
leave?"* is rewritten to *"What is the sick leave policy?"* before
retrieval runs. An unrelated question starts fresh instead of inheriting
the wrong documents. `GET /chats` lists conversations and
`GET /chats/{id}` returns one with every turn.

`GET /history` lists past questions and `GET /history/{id}` reopens one with
the citations and trace it originally produced — history is stored server
side, so it survives a refresh.

`POST /search` is the same retrieval with no model in the loop. It takes a
`mode` of `semantic`, `keyword` or `hybrid` and returns each chunk with its
section, page, retriever ranks and scores — useful for judging retrieval
without an answer in the way.

`GET /documents/attention` lists documents that failed or that indexed
without a summary, and `POST /documents/{id}/reprocess` runs one through
ingestion again. Nothing is deleted on failure, so a document that broke on a
stopped model server or an expired key can be recovered once that is fixed.

`GET /documents/{id}/structure` returns the document's heading tree along
with how many chunks it has in the index and how many pages it spans. The
headings are recovered by re-parsing the stored file, so a document whose
file has been removed reports `structure_available: false` and stays
queryable.

### How citations stay honest

- The model is instructed to mark every statement with the `[n]` of the source
  it came from. Those numbers index into `retrieved_chunks`.
- `citations` contains only the chunks the answer actually referenced, so a
  caller can render footnotes without re-deriving them. Each carries filename,
  section and page, e.g. *hr_policy.md, Section 1.1 Annual Leave*. The
  section path comes from the document's own headings, so it still reads as
  prose.
- A reply that is only citation markers with no statement (small models
  sometimes answer a list question with just `[2]`) is retried once with an
  explicit nudge, then reported as unanswered rather than shown as an answer.
- A model can cite a number that does not exist. Any `[n]` outside the source
  list is dropped and logged rather than returned as a dead link.
- If the retrieved chunks do not contain the answer, the model replies
  `NOT_FOUND`. The API turns that into `answered: false` with no citations
  instead of guessing.
- If nothing is retrieved at all, the pipeline short-circuits to the same
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