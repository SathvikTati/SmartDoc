# PORT-6 Workflows

How data moves through the system. Two pipelines: **ingestion** (upload → searchable) and **query** (question → cited answer, in one of three modes).

---

## Processes

| Process | Command | Responsibility |
|---|---|---|
| API | `uv run uvicorn port6.main:app --reload` | HTTP endpoints **and** background ingestion |
| Frontend | `npm --prefix frontend run dev` | React UI, talks to the API over HTTP only |
| Postgres | — | document rows and metadata |
| Chroma | — | chunk vectors, on disk in `chroma_data/` |
| Ollama / OpenAI | — | embeddings and generation |

There is no separate worker. Ingestion runs in a FastAPI `BackgroundTasks` thread inside the API process.

---

## Ingestion

Triggered by `POST /upload`. The response returns as soon as files are validated and stored; everything after that happens in the background.

```mermaid
flowchart TD
    U[POST /upload] --> V[validate_files]
    V --> V1[count / size / MIME]
    V1 --> V2[magic bytes]
    V2 --> V3[file sha256 - exact duplicate]
    V3 --> P[parse to text + blocks]
    P --> V4[content sha256 - content duplicate]
    V4 --> S[(save file to uploads/)]
    S --> D[(INSERT document, status=UPLOADED)]
    D --> R[return HTTP response]
    D -.background thread.-> B1

    B1[status = PROCESSING] --> B4[build_chunks]
    B4 --> B5[embed_chunks]
    B5 --> B6[summarize_document]
    B6 --> B7[status = READY]

    B4 -. on error .-> F[status = FAILED + error_message]
    B5 -. on error .-> F
```

### Stage by stage

**1. Validation** — `services/files/filevalidator.py`

Five gates, in order: file count, file size, declared MIME type, magic bytes (the declared type is not trusted), then SHA-256 of the bytes for exact duplicates. The file is parsed, and a second SHA-256 over the extracted text catches the same document uploaded in a different format.

**2. Parsing** — `services/parsers/parser.py`

Returns a `ParsedDocument` with `.text` (joined plain text, stored in Postgres) and `.blocks` — an ordered list of `ParsedBlock`, each carrying `text`, `page_number`, and `heading_level`.

Where headings come from:

| Format | Heading source |
|---|---|
| DOCX | paragraph style names (`Heading 1`…), real outline |
| Markdown | rendered `<h1>`…`<h6>` levels |
| PDF | shape heuristic (numbered `4.2`, ALL CAPS, Title Case) |
| TXT | same heuristic |

Page numbers are attached **per page during PDF parsing**, before pages are joined — after joining they are unrecoverable.

> **A file is identified by its filename.** Nothing infers a title, a type
> or an owning department from the content. That used to be a stage here —
> it cost a model call per upload to produce a label nothing could verify,
> and the section path already says where a citation came from. A citation
> now reads *hr_policy.md, Section 1.1 Annual Leave*.

**3. Chunking** — `services/structure/service.py` + `services/chunking/service.py`

Blocks are grouped into a section tree by their heading levels. Each section knows its `section_id`, `level`, `parent_section_id`, and `path` (root-down titles).

Chunks are then cut **inside each section separately**, never across section boundaries, so one chunk cannot contain the tail of the annual leave section and the head of the probation section.

Each chunk carries the page of the block it actually starts in, recovered
from the splitter's start offset. Stamping every chunk with the section's
*first* page meant a section spanning pages 4–7 cited all of its content as
page 4.

Every chunk is stamped with:

```
document_id  chunk_id  filename  chunk_index  page_number
section_id  section_title  section_path  parent_section_id  section_level
```

`None` values are dropped — Chroma rejects them.

**4. Embedding** — `services/vector/chroma.py`

The store is a single shared client built once under a lock: ingestion runs
in background threads, and several threads constructing a Chroma client
against the same directory at once races inside Chroma's registry.

Existing chunks for the document are deleted first (re-ingestion can produce fewer chunks; deleting avoids orphans at higher indices), then `vector_store.add_documents(chunks, ids=ids)` writes through the **configured** embedding function.

> Writing to `_collection.upsert()` directly would make Chroma silently embed with its own default model and store the wrong vector dimension.

**5. Summary** — one LLM call for a short document; a longer one is
summarised in windows that span its whole length and the parts combined,
because summarising only the opening made the largest documents the hardest
to find at stage 1.

Best-effort: a model failure logs a warning, leaves `summary` null, and the
document still reaches `READY` — but it is flagged on `/documents/attention`
and can be reprocessed, because a document with no summary is much weaker at
stage 1.

**Failure is recoverable.** The uploaded file is never deleted, so a
document that failed on a stopped Ollama or an expired key keeps its bytes.
`documents.attempts`, `last_attempt_at` and `failure_kind` record what
happened, and `POST /documents/{id}/reprocess` runs it again.

---

## Conversations

Every question belongs to a chat. One is created if none is given, and its
id comes back in `metadata.chat_id`, so a caller never has to decide up
front that it wanted a conversation.

A question that arrives in a chat is first *resolved* against the turns
before it, because some questions are not searchable as written:

```
Q1  "What is the maternity leave policy?"
Q2  "What about sick leave?"      -> retrieves almost nothing on its own
Q3  "Who is eligible?"            -> matches eligibility in every policy
```

**The expensive failure is the false positive.** Carrying maternity-leave
context into a question about expenses produces a confident wrong answer,
so the default is "new topic" and a follow-up has to be argued for.

Resolution runs in two halves:

1. **Rules, free.** A question carrying no dependent signal — no pronoun,
   no ellipsis, not a bare interrogative — is searchable as written and is
   treated as a new topic without a model call. Most questions stop here.
   This can only fail *safe*: the fallback is to ignore prior context, not
   to apply it.
2. **One small model call**, only for the rest. It returns the relation,
   the question rewritten to stand alone, and what to do with prior chunks.

Three outcomes:

| Strategy | When | What happens |
|---|---|---|
| `fresh` | new topic | Prior context is discarded entirely |
| `combine` | most follow-ups | Retrieve on the rewritten question, then merge a few chunks from the previous turn |
| `reuse` | "explain that more simply" | Answer from the previous turn's chunks; no retrieval runs |

A follow-up's rewritten question is what retrieval and generation actually
see; the user's original wording is what gets displayed and stored. Both
are recorded on the run, so an answer can be traced back to what was
really searched.

If the classifier fails, the question is searched as written and prior
context is ignored — a thinner answer, never one built on the wrong
document.

---

## Query

All three modes share the same entry point, prompt, and citation handling. Only retrieval differs.

```python
from port6.services.rag.system import query

result = await query(question, mode="naive" | "hybrid" | "agentic", top_k=5)
```

Every mode returns the same `RagResult`:

```
answer  answered  citations  retrieved_chunks
retrieval_method  latency_ms  metadata  debug
```

### Mode 1 — Naive

```mermaid
flowchart LR
    Q[question] --> E[embed query]
    E --> S[Chroma top-k]
    S --> G[LLM + numbered sources]
    G --> A[answer + citations]
```

No keyword matching and no hierarchy — a chunk is ranked purely on embedding distance to the question. This is the baseline the other modes improve on.

### Mode 2 — Hybrid + Hierarchical

```mermaid
flowchart TD
    Q[question] --> H1[Stage 1: rank documents<br/>from Postgres only]
    H1 --> H2[Stage 2: find sections<br/>inside those documents]
    H2 --> H3[Stage 3: retrieve chunks<br/>inside those sections]

    Q --> SEM[semantic search]
    Q --> KW[BM25 keyword search]

    H3 --> RRF[Reciprocal Rank Fusion]
    SEM --> RRF
    KW --> RRF
    RRF --> RR[rerank: agreement first]
    RR --> G[LLM] --> A[answer + citations]
```

**Hierarchical narrowing is genuinely progressive.** Stage 1 ranks
*documents* using BM25 over their filenames and summaries in Postgres — the
chunk index is never touched. The summary is effectively the whole signal
there: a filename is two or three tokens. A document with no summary falls
back to the opening of its content, so it stays rankable rather than
dropping out of document-level retrieval entirely. Stage 2 searches for sections
only within those documents. Stage 3 retrieves chunks only within those
sections.

**Fusion uses RRF, not score averaging.** Chroma returns a distance (lower is
better, unbounded scale), BM25 returns a relevance score (higher is better,
different scale). Those numbers are not comparable; their *ranks* are. Each
list contributes `1/(60 + rank)`, so a chunk both retrievers found
accumulates both contributions and rises to the top.

The hierarchical and flat-hybrid candidates are fused rather than one
replacing the other: hierarchy is precise but can narrow onto the wrong
document, and the flat pass is the safety net.

### Cross-document aggregation

Some questions are answered by breadth, not depth:

```
"Which documents mention probation?"
"What does each policy say about notice periods?"
"Compare the leave policies across all documents."
```

Plain top-k fails these *structurally*. With `top_k=5` every chunk can come
from one document, so the model is never shown the others and cannot
enumerate them however it is prompted.

Hybrid detects these with a conservative set of patterns — they all name
documents explicitly or ask for an exhaustive list, so *"how many days of
annual leave"* does not match — and switches to coverage retrieval:

1. **Topic terms** are separated from the asking-about-the-library
   scaffolding. *"What does each policy say about probation?"* has one real
   term, `probation`; matching on `policy` or `say` would qualify every
   document.
2. **One wide query**, then group by document keeping the best few from
   each, so a verbose document cannot take every slot.
3. **Documents with no keyword hit on the topic are dropped.** Semantic
   search returns the nearest chunk from every document whether or not it
   mentions the subject, and in an enumeration answer those near-misses are
   actively harmful.
4. **The context is grouped by document**, with `=== DOCUMENT: name ===`
   headings, so the boundaries the answer must enumerate are visible.

Agentic reaches the same thing through the `aggregate_search` tool, which
the planner selects for library-wide questions.

### Mode 3 — Agentic (LangGraph)

```mermaid
stateDiagram-v2
    [*] --> retrieval_planner
    retrieval_planner --> tool_execution
    tool_execution --> evidence_validation
    evidence_validation --> retrieval_planner: insufficient<br/>and attempts < 2
    evidence_validation --> context_builder: sufficient<br/>or out of retries
    context_builder --> answer_generation
    answer_generation --> [*]
```

**Graph state** (`AgentState`): `query`, `selected_tools`, `plan_reason`, `tool_runs`, `retrieved_chunks`, `retrieval_metadata`, `validation_result`, `attempts`, `final_context`, `answer`, `citations`, `stages`.

**The five tools:**

| Tool | Use |
|---|---|
| `semantic_search` | general natural-language questions |
| `keyword_search` | exact terms, codes, rare words |
| `hybrid_search` | both fused with RRF |
| `hierarchical_search` | answer sits in a specific part of a known document |
| `aggregate_search` | questions about the library as a whole: which documents mention X, comparing across documents |
| `calculate` | arithmetic the answer depends on — remaining leave, a percentage of a cap |
| `web_search` | the public web, when the library cannot answer. **Off by default** |
| `document_lookup` | what documents exist (returns filenames and clipped summaries as a chunk, so the model can actually answer from it) |

Tools are LangChain `@tool` objects, so each one's name, description and
arguments are defined once, beside the code. They are still selected by
*prompt* rather than by function calling: the local model picks the right
tool reliably but emits the choice as JSON in its content and leaves
`tool_calls` empty, so `bind_tools` and `ToolNode` would see nothing. On a
provider with working function calling the same definitions work unchanged.

Two of them are not retrieval:

- **`calculate`** evaluates arithmetic through an AST walker, never `eval`
  — the expression comes from a model, and `eval` on model output is
  arbitrary code execution. The agent hands every tool the raw question,
  so when it receives a sentence it recovers the expression first
  (*"Annual leave is 22 days. If I have taken 8…"* → `22 - 8` → `14`).
- **`web_search`** reaches the public internet, which changes what an
  answer means. It is off by default, withheld from the planner entirely
  when unavailable, refused outright for a question scoped to specific
  documents, and its results are labelled `WEB` in the context, badged in
  the UI and linked to their source rather than to a document.

**Planning** is done by the model on the first attempt (given the tool catalogue, it returns JSON `{"tools": [...], "reason": "..."}`), falling back to rules if the model returns anything unusable. The **retry always uses rules** — it is a deliberate widening to a full hybrid sweep, not a re-plan.

**Evidence validation** runs before the answer, in three bands. Below
`validation.min_overlap` the evidence is rejected outright; above
`validation.skip_model_above` it is accepted without asking the model, because
a small model reliably calls plainly good sources insufficient and each false
negative costs a full retry that changes nothing. Only in between does the
model judge `SUFFICIENT` / `INSUFFICIENT`. If the validator errors it falls
back to the lexical signal — a validator that cannot run must not block an
answer.

**Tool results are fused by rank, not by score.** A Chroma distance is better
when lower and a BM25 score when higher, so sorting the two together ranked a
keyword-only plan backwards and answered from the *worst* matches it found.
Each tool returns its own best-first ordering, and RRF over those positions is
what the context builder sorts on.

Bounded by the `agent.max_attempts` setting, so an unanswerable question still terminates. If evidence is still thin and nothing was retrieved, the agent **declines** rather than generating.

Only the tools chosen and a one-line plan reason are exposed. Never the model's private reasoning.

---

## Answer generation and citations

`services/rag/generation.py`, shared by all three modes.

Chunks are renumbered `1..n` and rendered with a provenance header:

```
[1] hr_policy.md | section: Acme Corp HR Policy > 1. Leave Entitlements > 1.1 Annual Leave | page 3
Employees accrue 22 days of paid annual leave per calendar year.
```

The filename and section path are in the header so the model can attribute each statement to a specific part of a specific document, which is what the `[n]` marker then resolves back to. The section path comes from the document's *own headings*, so it still reads as prose even though nothing extracts a title.

Three guards on the output:

1. **`NOT_FOUND` sentinel** — if the sources do not contain the answer, the model replies with that exact token, which becomes `answered: false` with no citations rather than a guess.
2. **Hallucinated citations dropped** — a `[7]` when only 4 sources exist is removed and logged, not returned as a dead link.
3. **Degenerate answers retried** — small models sometimes answer a list question with literally `[2]`. If stripping citation markers leaves under 15 letters, it retries once with an explicit nudge, then reports unanswered.

---

## Failure handling

| Situation | Behaviour |
|---|---|
| Empty library | `answered: false`, normal response shape, not an error |
| Nothing relevant retrieved | short-circuits before the LLM |
| Document with no summary | still retrievable by chunk; stage 1 cannot rank it |
| Structure file deleted from `uploads/` | chunks as one unstructured section |
| One agent tool throws | logged, other tools continue |
| A whole mode throws | `system.query` returns a `RagResult` carrying the error, so a comparison still renders the other modes |
| Summariser fails | document still reaches `READY`, `summary` stays null |
