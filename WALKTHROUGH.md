# PORT-6 Walkthrough

One document uploaded, one question asked, traced end to end through real code with real observed values.

Every number below was captured from an actual run against Postgres, Chroma and Ollama (`qwen2.5-coder:7b` + `nomic-embed-text`).

---

## Setup

```bash
uv run uvicorn port6.main:app --reload   # terminal 1
npm --prefix frontend run dev            # terminal 2 → http://localhost:5173
```

Or run everything at once:

```bash
uv run python demo/run_demo.py
```

The corpus is in [`demo/documents/`](demo/documents/) — six documents in four formats.

---

# Part 1 — Uploading `hr_policy.md`

## 1.1 The request

`POST /upload` → [`main.py`](src/port6/main.py) `upload_files()`.

## 1.2 Validation — `files/filevalidator.py`

Five gates in order. Any failure returns a 4xx and nothing is stored.

```
file count ≤ 5              ✓
size ≤ 5 MB                 ✓
MIME text/markdown allowed  ✓
magic bytes                 ✓  (text formats have no signature to check)
sha256 of bytes             ✓  not seen before
```

The file is saved as `uploads/<uuid>_hr_policy.md`, parsed, and a **second** SHA-256 is taken over the extracted text — that catches the same document re-uploaded as a PDF.

A row is inserted with `status = UPLOADED`, and the HTTP response returns immediately.

## 1.3 Background ingestion begins

`background_tasks.add_task(process_document, document_id)`. `process_document` is **synchronous**, so FastAPI runs it in a worker thread and the API keeps serving requests.

Status → `PROCESSING`.

## 1.4 Parsing — `parsers/parser.py`

Markdown is rendered to HTML and walked, so heading levels are read rather than guessed. **13 blocks** come out:

```
H1  'Acme Corp HR Policy'
    'Document Type: HR Policy\nDepartment: Human Resources'
H2  '1. Leave Entitlements'
H3  '1.1 Annual Leave'
    'Employees accrue 22 days of paid annual leave per calendar year…'
H3  '1.2 Maternity Leave'
    …
H2  '2. Probation'
    'New employees serve a probation period of 3 months…'
```

> The document's `Document Type:` and `Department:` header lines are just
> text. Nothing reads them: a file is identified by its filename, and the
> section path below is what makes a citation specific.

## 1.5 Section tree — `structure/service.py`

Blocks are walked with a heading stack:

```
- [s1] Acme Corp HR Policy
  - [s2] 1. Leave Entitlements
    - [s3] 1.1 Annual Leave
    - [s4] 1.2 Maternity Leave
    - [s5] 1.3 Sick Leave
  - [s6] 2. Probation
  - [s7] 3. Notice Period
```

`s2` holds no text of its own but is **kept**, because `s3`–`s5` point at it as their parent. Dropping it would leave dangling references. `content_sections()` filters it out at chunking time.

## 1.6 Chunking — `chunking/service.py`

Each section is split separately. One resulting chunk:

```python
page_content = "Employees accrue 22 days of paid annual leave per calendar year. …"
metadata = {
  "document_id": "…",  "chunk_id": "…:1",  "chunk_index": 1,
  "filename": "hr_policy.md",
  "section_id": "s3",  "section_level": 3,  "parent_section_id": "s2",
  "section_title": "1.1 Annual Leave",
  "section_path": "Acme Corp HR Policy > 1. Leave Entitlements > 1.1 Annual Leave",
}
```

Because the split happens inside `s3`, this chunk cannot contain any probation text.

## 1.7 Embedding — `vector/chroma.py`

Existing chunks for this document are deleted first, then `add_documents(chunks, ids=ids)` writes through the configured embedder — `nomic-embed-text`, 768 dimensions.

> The vector store is a **single shared client built once under a lock**. Ingestion runs in background threads, and uploading six files at once used to have six threads construct a Chroma client against the same directory simultaneously — which races inside Chroma's registry and fails ingestion.

## 1.8 Summary, then READY

`summarize_document()` sends the first 12 000 characters and stores the result — the one LLM call ingestion makes. If it fails, a warning is logged and the document still reaches `READY`, but see stage 1 below: the summary is what makes a document findable *as a document*.

Status → `READY`.

---

# Part 2 — Asking *"How much annual leave do employees get?"*

The answer is **22 days**, in `hr_policy.md` section 1.1.

## 2.1 Mode 1 — Naive

`rag/naive.py`: embed the question, take the top-k chunks, generate.

```
SEM: hr_policy.md 0.2761 · hr_policy.md 0.5410 · policy.docx 0.5808 · meeting_notes.txt 0.6170

answer: "Employees accrue 22 days of paid annual leave per calendar year.
         Unused annual leave may be carried over up to a maximum of 10 days. [1]"
cite:   hr_policy.md, Section 1.1 Annual Leave
```

Correct — but notice what else got in. `meeting_notes.txt` has an "ANNUAL LEAVE" heading that says nothing concrete, and `policy.docx` is unrelated. Naive ranks purely on embedding distance, so near-miss text competes for context slots.

## 2.2 Mode 2 — Hybrid + Hierarchical

### Stage 1 — documents, from Postgres only

BM25 over filenames and summaries. The chunk index is never touched.

```
hr_policy.md       2.8003
meeting_notes.txt  2.3742
travel_policy.md   0.3586
```

Three documents survive; the handbook, expense and security policies are eliminated **before any vector search runs**.

### Stage 2 — sections, inside those documents only

```
Acme Corp HR Policy > 1. Leave Entitlements > 1.1 Annual Leave   dist=0.2761  ← closest
Acme Corp HR Policy > 1. Leave Entitlements > 1.3 Sick Leave     dist=0.5410
ANNUAL LEAVE                                                     dist=0.6170
Acme Corp HR Policy > 1. Leave Entitlements > 1.2 Maternity Leave dist=0.6835
```

### Stage 3 — chunks, inside those sections only

```
[1] 1.1 Annual Leave     dist=0.2761
[2] 1.3 Sick Leave       dist=0.5410
[3] ANNUAL LEAVE         dist=0.6170
[4] 1.2 Maternity Leave  dist=0.6835
```

### The flat hybrid pass, as a safety net

Hierarchy is precise but can narrow onto the wrong document, so a flat pass runs alongside it:

```
SEM: hr_policy.md 0.2761 · hr_policy.md 0.5410 · policy.docx 0.5808 · meeting_notes.txt 0.6170
KW : hr_policy.md 8.347  · meeting_notes.txt 6.720 · policy.docx 4.658 · policy.docx 4.229
```

### RRF fusion

Each list contributes `1/(60 + rank)`. Scores are never averaged — a Chroma distance of `0.2761` and a BM25 score of `8.347` are not on comparable scales, but their ranks are.

```
hr_policy.md       0.032787   semantic+keyword   ← found by both, rises to the top
meeting_notes.txt  0.031754   semantic+keyword
hr_policy.md       0.016129   semantic
policy.docx        0.015873   semantic
```

Agreement between the two retrievers is what promotes the right chunk.

```
answer: "Employees accrue 22 days of paid annual leave per calendar year. [1]"
cite:   hr_policy.md, Section 1.1 Annual Leave
```

## 2.3 Mode 3 — Agentic

The graph runs `retrieval_planner → tool_execution → evidence_validation → context_builder → answer_generation`.

Observed trace for *"Which documents are in the library?"*:

```
retrieval_planner    (planned by model)
tool_execution       ran 1 tool(s)
evidence_validation  Model judged the sources sufficient.
context_builder      kept 1 chunk
answer_generation    1 citation

tools used: ['document_lookup']
attempts:   1
```

The model picked `document_lookup` — the right tool for a catalogue question — rather than running a similarity search that would have returned arbitrary policy text.

---

# Part 3 — Where each mode earns its keep

## 3.1 Exact codes: *"What is control SEC-4412?"*

```
answer: "Control SEC-4412 blocks the reuse of the previous 12 passwords [1]."
cite:   security_policy.docx, Section 1.1 Password Requirements
```

An identifier like `SEC-4412` is exactly what BM25 is for — embeddings tend to blur rare tokens into their surrounding text.

## 3.2 Page-level citations: *"What is the grievance procedure?"*

```
cite: employee_handbook.pdf, Section 5. Grievance Procedure, Page 3
```

The handbook is a PDF. Page numbers are captured per page during parsing, before pages are joined — after joining they are unrecoverable.

## 3.3 An unanswerable question

*"What is the company policy on pet insurance?"* in agentic mode:

```
attempts:   2
tools used: ['keyword_search', 'document_lookup', 'hybrid_search', 'keyword_search']
validation: sufficient=False
answer:     "I could not find an answer to that question in the uploaded
             documents."   (answered=False, 0 citations)
```

Validation caught the mismatch, the agent retried once with a wider strategy, then stopped at `MAX_ATTEMPTS` and declined. It did not invent an answer.

---

# Part 4 — Reading the UI

**Sidebar** — pick the mode; the ask runs in whichever is selected.

**Ask tab** — the answer renders `[n]` as superscript pills. A pill for a source that does not exist renders muted and dashed rather than disappearing, so you can see the model referenced something unresolvable.

**Retrieval trace** (collapsed under the answer) shows latency, chunks used, citation count, pipeline stages, documents chosen at stage 1, sections at stage 2, semantic vs keyword matches side by side, which chunks both retrievers found, and — for agentic — tools used, plan reason and validation verdict.

**Chunk list** — cited chunks pinned (📌) and open, uncited collapsed, so you can see what was retrieved *and not used*. Each label reads `[1] hr_policy.md · Section 1.1 Annual Leave · semantic+keyword · dist 0.2761`.

**Compare modes tab** — the same question through all three, with a summary table of answered / citations / chunks / documents / latency.

---

# Part 5 — Trying it yourself

```python
import asyncio
from port6.services.rag.system import query

async def main():
    for mode in ("naive", "hybrid", "agentic"):
        r = await query("How much annual leave do employees get?",
                        mode=mode, top_k=4)
        print(f"{mode:8} {r.latency_ms:7.0f}ms  {r.answer[:70]}")

asyncio.run(main())
```

Every retrieval component is independently callable, which makes each stage easy to inspect on its own:

```python
from port6.services.rag.retrievers import semantic_search, keyword_search, fuse
from port6.services.rag.hierarchical import select_documents, select_sections

print(select_documents("annual leave"))              # stage 1 only
print(keyword_search("SEC-4412", top_k=3))           # BM25 only
```

---

## Observed timings

Local, `qwen2.5-coder:7b` on Apple silicon, 6-document corpus:

| Mode | Latency |
|---|---|
| Naive | ~1.0 s |
| Hybrid + Hierarchical | ~0.9 s |
| Agentic | ~2–5 s |

Agentic costs more because planning and validation are extra model calls. That is the trade: it buys tool selection, evidence checking and a retry loop.
