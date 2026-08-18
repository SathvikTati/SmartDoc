# PORT-6 — Live Demo Walkthrough

A single pass through the UI that touches every feature. Follow it top to
bottom and nothing is left unshown.

Each step gives you the **exact text to paste** and the **answer this
corpus actually returns**, so you know immediately whether a step went
wrong. Every output below was captured from a real run against
`demo/documents/` — not written from memory.

Reading time ~7 min. Demo time ~25 min at a talking pace.

Just want the inputs without the narration? See [INPUTS.md](INPUTS.md).

---

## Before you start

```bash
# 1. API
uv run uvicorn port6.main:app --reload

# 2. frontend
cd frontend && npm run dev        # http://localhost:5173

# 3. Ollama must be up with both models
ollama list                       # qwen2.5-coder:7b, nomic-embed-text
```

**Start from a clean library.** The answers below assume the ten files in
`demo/documents/` and nothing else. `demo/documents/updates/` is held
back on purpose — it is uploaded during Act 7.

```bash
uv run python demo/run_demo.py --reset    # removes the demo documents
```

About 108 KB across ten documents, indexing to roughly 200 chunks, and
deliberately overlapping: five documents mention probation, three mention
data retention, and the held-back revision disagrees with the HR policy
on three figures. The overlap is what makes aggregation, scoping and
conflict detection worth showing.

| File | Format | Why it is in the corpus |
|---|---|---|
| `hr_policy.md` | Markdown, 11 KB | The anchor — three heading levels, most of the figures |
| `expense_policy.md` | Markdown, 8.6 KB | Caps, rates, an approval table, `FIN-2026-EXP` |
| `it_acceptable_use.md` | Markdown, 7.2 KB | Devices, BYOD, AI tool rules |
| `travel_policy.md` | Markdown, 6.7 KB | Overlaps HR on probation |
| `data_retention_schedule.md` | Markdown, 6.2 KB | Retention tables; overlaps security |
| `security_policy.docx` | DOCX, 40 KB | Real Word heading styles; `SEC-4412`, `SEC-8830` |
| `employee_handbook.pdf` | PDF, 8 pages | Page-numbered citations |
| `overtime.txt` | Plain text, 5.1 KB | Pay formulas the calculator reads out of the document |
| `onboarding_checklist.txt` | Plain text, 5.2 KB | No heading syntax — the structure fallback |
| `meeting_notes.txt` | Plain text, 4.7 KB | Deliberately vague; competes and loses |

---

## Act 1 — Ingestion and the file manager

**Go to** `/files`.

1. **Drag all ten files** from `demo/documents/` onto the window. The
   upload dialog accepts the drop and each file gets its own row.

2. **Watch the status column.** Rows go `PENDING → PROCESSING → READY`.
   Ingestion runs in a background thread, so the UI stays responsive —
   click around while it works. On a warm Ollama the ten files take a
   few minutes — this corpus is large enough that ingestion is worth
   watching rather than skipping.

   Worth saying out loud: extraction, chunking, embedding and
   summarisation all happen here, once. Nothing is re-read at query time.

3. **Switch between the two views** with the toggle top-right. Details
   view gives you sortable columns; icons view gives you a grid. Click a
   column header to sort by name, size or date.

4. **Click one file.** The preview pane opens on the right with the
   summary, the size, the page or section count, and the ingest time.
   The summary is LLM-generated at upload — for a long document it is
   produced map-reduce over windows, so the tail of the file is
   represented, not just the first few pages.

5. **Right-click a file.** The context menu has Open, Ask about this, and
   Delete. All three work; the menu closes on an outside click.

6. **Check the status bar** at the bottom. It tracks selection live:
   select three files and it reads the count and the combined size.

7. **Open `employee_handbook.pdf`** (double-click, or Open from the menu).
   The detail page shows the full summary, the extracted section tree,
   and every chunk with its page number and character offsets. This is
   the receipt for ingestion — if a citation later says "page 4", this
   page is where you show that page 4 is real.

8. **Mention recovery.** A file that fails extraction lands in a `FAILED`
   state with the reason attached, and `Reprocess` re-runs ingestion
   without a re-upload. `GET /documents/attention` lists everything
   currently in a bad state, so a stuck document cannot hide in a long
   library.

---

## Act 2 — Asking, and where answers come from

**Go to** `/ask`. Mode selector set to **Hybrid**.

### 2a. A plain question

```
How much annual leave do employees get?
```

> Employees accrue 22 days of paid annual leave per calendar year [1].

Click the `[1]`. The evidence panel scrolls to the exact chunk, and it
says `hr_policy.md · 1.1 Annual Leave`. The citation is not decorative —
every sentence is traceable to a chunk that was actually retrieved.

### 2b. A rare code, which is why hybrid exists

```
What is control SEC-4412?
```

> Control SEC-4412 blocks the reuse of the previous 12 passwords [1].

This is the BM25 half of hybrid earning its place. Embeddings are poor at
identifiers — `SEC-4412` has no useful semantic neighbourhood — so a
pure-vector system tends to return "something about passwords" instead of
the control. Keyword search matches the token exactly, and Reciprocal
Rank Fusion puts it first.

Open the **retrieval trace** below the answer. Each chunk shows which
retriever found it (`semantic`, `keyword`, or both) and its rank in each
list. Chunks found by both retrievers are the ones that rise.

### 2c. A page-numbered citation from a PDF

```
What is the grievance procedure?
```

> An employee should first discuss a grievance informally with their line
> manager. If not resolved, they can submit a formal written grievance to
> People Operations, who must acknowledge it within 5 working days and
> hold a hearing within 15 working days [1].

The citation reads **page 6**, and page 6 of the handbook is the
grievance section — open the document and check. Chunk offsets are mapped
back to the PDF page they came from during ingestion.

### 2d. It declines rather than inventing

```
What is the company policy on pet insurance?
```

> I could not find an answer to that question in the uploaded documents.

Nothing in the corpus covers this. The answer prompt is constrained to
the retrieved sources, and a separate validation pass scores the answer's
content words against the retrieved text — so a confident fabrication
gets caught rather than shipped. This is the single most important slide
in a document-QA demo; don't skip it.

---

## Act 3 — What people actually type

Before the polished questions, show the messy ones. This is where most
document-QA demos quietly fall over.

**A topic, not a question:**

```
leave policy
```
```
expense limits
```

Both answer. A bare topic names no answer to look for, so the generator
used to read five perfectly good chunks and reply "I could not find an
answer" — the phrase is rewritten into a question before generation,
while retrieval still uses the words as typed.

**A greeting:**

```
hello
```

> Hello. I answer questions about the documents you have uploaded, and
> cite the passage each statement comes from…

Answered in 0 ms with no evidence panels, because nothing was retrieved.
`thanks`, `bye` and `what can you do?` behave the same way.

**And the thing that must not break:**

```
hi, how much annual leave do we get?
```

Retrieves normally. Only a message that is *nothing but* a pleasantry
short-circuits — a real question quietly answered with "how can I help?"
would be far worse than a greeting getting retrieved for.

**Too long:**

Paste more than 1000 characters. The counter turns red and submit is
blocked before the request is sent, rather than the server returning
"String should have at most 1000 characters".

---

## Act 4 — Scoping to the documents you chose

Same question, different scope, different answer. This is the clearest
30 seconds in the demo.

1. **Go to** `/files`, select **`travel_policy.md`** only, right-click →
   **Ask about this**. In `/ask`, paste:

```
What does this say about probation?
```

> Employees still on probation require additional approval before any
> international travel [1].

2. **Back to** `/files`. Select **`hr_policy.md`** only, ask the same
   question again:

> New employees serve a probation period of 3 months, and probation may
> not be extended [1].

3. **Now select both** (ctrl/cmd-click, or shift-click for a range). The
   button reads **Ask about these 2 documents**:

```
What does probation affect?
```

> Probation affects an employee's ability to travel internationally and
> their accrual of annual leave [2][4].

The scope is a hard filter applied at the retriever, not a hint in the
prompt. Chunks outside the selection are never retrieved, so they cannot
influence the answer even indirectly.

---

## Act 5 — Cross-document aggregation

Normal retrieval optimises for *depth* — the k best chunks anywhere. Some
questions need *coverage* — the best chunks from every document that is
relevant. Top-k gives you five chunks from your two strongest documents
and silently drops the third.

```
What does each document say about probation?
```

> **employee_handbook.pdf** — Probation terms are set out in the HR Policy
> and are not repeated here. [1]
>
> **hr_policy.md** — New employees serve a probation period of 3 months.
> Probation may not be extended. [3]

The header above the answer reads **aggregated over 5 documents**. The
question is classified as an aggregation up front, retrieval switches to
coverage mode, chunks are grouped by document, and a different answer
prompt renders it per document rather than as one paragraph.

Also try:

```
Which documents mention leave?
```

**Be honest about the boundary.** Detection is pattern-based, so it fires
on "each document", "which documents", "across all", "compare" and
similar phrasings. A question that means the same thing in different
words may not trip it. Phrase it as an aggregation and it aggregates.

---

## Act 6 — Follow-up questions

Ask these **in order, in the same investigation**. Do not start a new one
between them.

**1.**
```
What is the maternity leave policy?
```
> Eligible employees are entitled to 28 weeks of paid maternity leave.
> Maternity leave must be requested at least 6 weeks before the expected
> date [1].

**2.**
```
What about sick leave?
```
> Employees receive 12 days of paid sick leave per year [1].

Open the trace. It shows `follow_up · combine`, and the resolved query:
**"What is the sick leave policy?"** On its own, "What about sick leave?"
retrieves nothing useful — there is no verb and no subject. The chat
history is used to rewrite it into a standalone question *before*
retrieval runs, and the resolution is shown rather than hidden.

**3.**
```
Who is eligible?
```

Another pronoun-only question, resolved against the same history.

**4. Now switch topic in the same chat:**
```
What is the expense limit for hotels?
```
> Hotel accommodation is capped at 250 USD per night in major cities and
> 150 USD per night elsewhere [1].

The trace reads `new_topic · fresh`. This is the failure mode that
matters: a naive "always prepend the history" implementation drags
maternity leave into a hotel question and pollutes the retrieval. The
classifier recognises the question as self-contained and starts clean.

Point at the **Chat ID** in the header — it is what threads the turns
together, and it's what the History page groups on.

---

## Act 7 — Arithmetic

Leave the mode selector on **Naive** for the first one. That is the
point: this is not an agent feature.

```
I have taken 8 days of leave. How many leave days do I have remaining?
```

> You have 14 days of leave remaining [6].

Click the `[6]`. The source is **calculator** and its content is the
worked expression `22 - 8 = 14`. The 22 came from `hr_policy.md`; the
8 came from the question; the subtraction came from neither.

Run the same question in Hybrid and Agentic — same answer. The sum runs
after retrieval in every mode, so a question needing arithmetic does not
first need someone to pick the right mode.

Second one, mixing retrieval and arithmetic:

```
What is 15% of the 250 USD hotel cap?
```

> 15% of the 250 USD hotel cap is 37.5 USD [6].

The `250` came from `expense_policy.md`; the multiplication did not come
from the model.

**Why not just let the model do it.** A 7B is unreliable at arithmetic
and confidently wrong when it slips — the worst combination inside an
answer that cites a policy. The expression is evaluated by parsing it to
an AST and walking it against an allow-list of operators and functions.

**It never calls `eval`.** The expression is written by a model, which
makes it untrusted input, and `eval` on untrusted input is arbitrary code
execution. If someone asks how it is sandboxed, this is the answer:
`__import__("os")`, `().__class__.__bases__`, `open()` and `2**10000000`
are all rejected by the walker, and there is no path from an expression
to attribute access, imports or arbitrary calls.

**Third one — the formula lives in the document, not the question:**

```
My hourly rate is 20 and I worked 6 overtime hours. What is my overtime pay?
```

> Overtime pay = Hourly pay rate x 1.5 x overtime hours worked.
> 20 x 1.5 x 6 = 180 [6]

The ×1.5 multiplier appears nowhere in the question — it is in
`overtime.txt`. This works because the calculation runs **after**
retrieval, with the sources in view. Asked before retrieval, the model
had nothing to write the multiplier from and produced `20 * 6 = 120`.

Two guards worth mentioning if anyone asks how it avoids laundering a
guess. The expression step returns NONE when it cannot build the whole
expression from the question and the sources — a missing operation
counts, even when the numbers are all present. And an "expression" that
is just a number is thrown away: that means the model did the sum itself
and skipped the working, which is precisely what this exists to prevent.

**Where it still declines.** "I carried over 10 days on top of my annual
leave, what is my total?" returns no answer. Nothing states that carry-
over adds to the entitlement, so refusing is the correct outcome rather
than a bug — but do not put it in the demo expecting 32.

---

## Act 8 — When two documents disagree

A library accumulates versions. Someone uploads a revised policy and
does not delete the old one, and now two documents answer the same
question with different numbers.

**Upload the held-back revision**, from `/files` or from a terminal:

```bash
curl -F "files=@demo/documents/updates/hr_policy_2027.md;type=text/markdown" \
  localhost:8000/upload
```

Wait for it to reach READY, then ask the question you asked in Act 2a:

```
How much annual leave do employees get?
```

> 25 days of paid annual leave per calendar year [1][3]. Previously, they
> received 22 days [5].

A banner appears above the answer: **Your documents disagree** — with the
figures, the filenames and the upload dates. Two more:

```
What is the notice period for resignation?
```
> 90 days, previously 60.

```
How many days of sick leave do employees get?
```
> 15 days, previously 12.

**How it decides.** Detection is narrow on purpose: two chunks conflict
only when they come from different documents and the words *after* the
number match. "22 days paid annual leave" against "25 days paid annual
leave" is a conflict; "12 days paid sick leave" is not. A missed conflict
just leaves the old behaviour, while a false one rewrites a correct
answer — so it errs toward missing.

**Be clear that recency is a guess.** Nothing in a file says it
supersedes another. The most recently uploaded document wins because
that is the only signal available, which is exactly why the older figure
is reported rather than silently dropped: a reader who knows the old
document is the authoritative one can see it was set aside. It is also
why the upload dialog asks you to delete the version you are replacing.

**Delete `hr_policy_2027.md` before moving on**, or the rest of the demo
answers 25 days where this script says 22.

---

## Act 9 — Web search

Off by default. Turn it on for this act:

```bash
curl -X PUT http://localhost:8000/settings/web.enabled \
  -H 'Content-Type: application/json' -d '{"value": true}'
```

Mode: **Agentic**.

```
What is the UK statutory maternity leave entitlement in weeks?
```

> The UK statutory maternity leave entitlement is 26 weeks [1][3].

Nothing in the corpus answers this. The agent tries the documents, the
validation pass finds the answer unsupported, and the retry plan reaches
for `web_search`. Web sources are badged distinctly in the evidence panel
and carry their URL and domain.

**Then show the boundary holding.** Go to `/files`, select `hr_policy.md`,
Ask about this, and ask the same question:

> I could not find an answer to that question in the uploaded documents.

The agent *planned* a web search — you can see `web_search` in the tools
row — but the tool refused, returning
`{'skipped': 'question is scoped to specific documents'}`. A document
scope is a statement about which documents may answer; reaching outside
the library would contradict it. The guard is in the tool, not the
prompt, so the model cannot talk its way past it.

Three things keep web results from being confused with your documents:
a web chunk carries a `url` and nothing else in the system sets one; its
`document_id` is the literal string `"web"`, so it can never be mistaken
for a row in the documents table; and the context handed to the model
labels it `WEB` with its URL.

**Cost:** nothing. It uses DuckDuckGo via `ddgs`, which needs no API key
and no billing account. Google has no keyless search API — the official
route wants a Cloud project, an API key and a separately-created engine
ID before it returns a single result.

**Caveat:** the 7B occasionally attaches a document citation to a
web-sourced claim. The badge in the evidence panel is authoritative; the
inline numbering is not always.

Turn it back off afterwards if you are demoing the default posture:

```bash
curl -X PUT http://localhost:8000/settings/web.enabled \
  -H 'Content-Type: application/json' -d '{"value": false}'
```

---

## Act 10 — Search, Compare, History

### Search — retrieval without the model

**Go to** `/search`. Query:

```
expense reimbursement
```

Three chunks come back from `expense_policy.md` —
*Acme Corp Expense Policy*, *2. Reimbursement*, *1.1 Meals* — each tagged
`semantic + keyword`. Switch the mode toggle between semantic, keyword
and hybrid and watch the ordering change.

This page is the debugging surface. When an answer is wrong, the question
is always "was the right chunk retrieved?" — and this answers it without
the generation step in the way.

### Compare — the three modes on one question

**Go to** `/compare`:

```
What does each document say about probation?
```

All three modes run on the same question and render side by side with
latency. Representative numbers from this corpus:

| Mode | Latency | Documents cited |
|---|---|---|
| naive | ~2.8 s | 3 |
| hybrid | ~4.6 s | 5 |
| agentic | ~5.5 s | 5 |

Naive ranks chunks and stops, so it sees three documents and never learns
the other two exist. Hybrid detects the aggregation and covers five. That
gap is real now — on the small corpus this demo used to ship with, all
three modes agreed and naive often read best.

Still worth saying plainly: agentic costs latency and extra model calls
for the same five documents hybrid found. This page is how you decide
whether a corpus needs it, not a claim that it always wins.

Try one where they agree, so the comparison stays honest:

```
What is control SEC-4412?
```

### History

**Go to** `/history`. Every run is here: question, mode, latency, which
tools ran, and how many attempts the agent needed. Turns are grouped
under their chat, so a follow-up thread reads as a conversation rather
than as loose rows.

The sidebar shows the eight most recent and the Ask page the five most
recent; this page is the full list. Delete a chat and its runs go with
it — no orphaned rows in the sidebar.

---

## Act 11 — Configuration, live

Prompts and settings live in Postgres, not in source. Every prompt is
editable at runtime and the change takes effect on the next request — no
restart, no redeploy.

```bash
curl -s localhost:8000/prompts | python3 -m json.tool | head -40
curl -s localhost:8000/settings | python3 -m json.tool | head -40
```

Eight prompts are exposed: `answer_generation`, `aggregate_answer`,
`retrieval_planner`, `follow_up_resolution`, `evidence_validation`,
`calculation_expression`, `document_summary` and
`document_summary_combine`. Each is a single `template` field — one box
to edit, not a system/human pair to keep consistent.

**Show the guard rail.** Every prompt declares the placeholders its
pipeline supplies. Drop one and the write is rejected:

```bash
curl -X PUT localhost:8000/prompts/answer_generation \
  -H 'Content-Type: application/json' \
  -d '{"template": "You are helpful. Answer this: {query}"}'
```

```json
{"detail": "Prompt 'answer_generation' must still contain: {context}"}
```

`422`. Without this check, dropping `{context}` would silently discard
the retrieved sources and the failure would surface as a confidently
wrong answer rather than an error — the worst possible way to find out.

Every prompt can be reset to what the release shipped:

```bash
curl -X POST localhost:8000/prompts/answer_generation/reset
```

Upgrades follow the same principle: a new release advances a prompt that
you have *not* edited, and never touches one you have.

---

## Act 12 — What happens when things break

- **404** — go to `/nonsense`. A real page with a route back, not a blank
  screen.
- **Empty states** — every list has one, written for the situation rather
  than a generic "No data".
- **Provider errors** — stop Ollama and ask a question. The failure is
  classified (auth, quota, rate limit, unreachable, missing model,
  timeout, server) and surfaced as a human sentence with the fix, not a
  stack trace.
- **Failed ingestion** — a `FAILED` document keeps its reason and offers
  `Reprocess`.

---

## Things to have an answer ready for

**"Does anything leave my machine?"** By default, no. Ollama is local,
Postgres and Chroma are local, and web search is off. Turn web search on
and the *query* goes to DuckDuckGo — which is why it is off by default
and badged everywhere it appears.

**"Is it secure?"** Neither process has authentication. It is built to
run on localhost. That is a deliberate scope choice, not an oversight —
say so plainly rather than being caught by it.

**"Why a 7B model?"** It runs on a laptop with no per-token cost, which
is the right default for a demo. The provider is pluggable — switch to
OpenAI in settings and every pipeline uses it unchanged. The rough edges
you saw (the occasional stray citation, a declined question that a
person would have answered) are 7B-shaped and largely go away on a
bigger model.

**"How do I know it isn't hallucinating?"** Three layers, and you showed
all three: retrieval is filtered to your documents, every sentence cites
a chunk you can open, and a validation pass scores the answer against the
retrieved text before it is returned. Plus Act 2d — it declines.
