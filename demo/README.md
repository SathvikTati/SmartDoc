# PORT-6 Demo

A corpus and a script that show what each retrieval mode does.

```bash
# 1. start the API
uv run uvicorn port6.main:app --reload

# 2. run the whole demo (uploads, waits for ingestion, runs every scenario)
uv run python demo/run_demo.py
```

Other options:

```bash
uv run python demo/run_demo.py --list             # list scenarios
uv run python demo/run_demo.py --only keyword     # run one
uv run python demo/run_demo.py --skip-upload      # already ingested
uv run python demo/run_demo.py --reset            # delete demo docs
```

First run takes a few minutes: six documents are chunked, embedded, summarised and have their metadata extracted by a local model.

> **For a clean demo, start with an empty library.** Any other document competes for the top-k slots and may end up cited. The script warns you if it finds any.

---

## The corpus

Six documents in four formats, built so every feature has something to bite on.

| File | Format | Contains |
|---|---|---|
| `hr_policy.md` | Markdown | Leave, probation, notice period — three-level heading tree |
| `expense_policy.md` | Markdown | Meal and hotel caps, reference code `FIN-2026-EXP` |
| `travel_policy.md` | Markdown | Booking rules; also mentions probation, so some questions cross documents |
| `security_policy.docx` | **DOCX** | Real `Heading 1/2/3` styles; codes `SEC-4412`, `SEC-8830`, `ISO 27001` |
| `employee_handbook.pdf` | **PDF, 3 pages** | Working hours, remote work, grievance procedure (page 3) |
| `meeting_notes.txt` | Plain text | ALL-CAPS headings, no metadata, deliberately vague |

### What each file is for

- **`hr_policy.md`** — the main target. Three heading levels exercise document → section → subsection narrowing.
- **DOCX** — structure comes from real Word heading styles rather than a shape heuristic. The codes are what BM25 shines on.
- **PDF** — three pages, so citations carry page numbers. The grievance procedure is on page 3.
- **`travel_policy.md`** — mentions probation, which also appears in the HR policy, so a probation question has to reach across documents.
- **`meeting_notes.txt`** — ALL-CAPS headings and an "ANNUAL LEAVE" section that says nothing concrete. It tests that near-miss text competes realistically for retrieval slots, and that a document whose headings come from a shape heuristic still chunks sensibly.

---

## Scenarios

| Key | Question | Shows |
|---|---|---|
| `keyword` | What is control SEC-4412? | BM25 on exact codes |
| `sections` | How much annual leave do employees get? | hierarchical narrowing, section-level citation |
| `pages` | What is the grievance procedure? | page-level citations from a PDF |
| `crossdoc` | What are the rules for working away from the office? | evidence spread across documents |
| `tools` | Which documents are in the library? | agent tool selection |
| `unanswerable` | What is the company policy on pet insurance? | refusing to guess |

---

## What actually happens

Observed on `qwen2.5-coder:7b` + `nomic-embed-text`. Your wording may differ slightly — the retrieval behaviour does not.

### `keyword` — exact identifiers

```
NAIVE   "Control SEC-4412 blocks the reuse of the previous 12 passwords [1]."
HYBRID  same answer
AGENTIC same answer   tools: ['keyword_search', 'hybrid_search', 'keyword_search']

cite: security_policy.docx, Section 1.1 Password Requirements
```

All three get it here, because the code appears verbatim and the corpus is small. Watch the retrieval trace rather than the answer: BM25 puts the security policy first on the keyword side, which is what keeps it robust as the corpus grows.

### `sections` — narrowing to the right section

```
NAIVE   "Employees accrue 22 days of paid annual leave per calendar year.
         Unused annual leave may be carried over up to a maximum of 10 days. [1]"
HYBRID  "Employees accrue 22 days of paid annual leave per calendar year. [1]"

cite: hr_policy.md, Section 1.1 Annual Leave
```

Stage 1 narrows to three documents from Postgres alone — BM25 over filenames and summaries, no chunk index touched. Stage 2 finds `1.1 Annual Leave` at distance `0.2761`. RRF then puts the chunk both retrievers found on top with a fused score of `0.032787`.

### `pages` — citing a page

```
cite: employee_handbook.pdf, Section 5. Grievance Procedure, Page 3
```

### `tools` — the agent choosing correctly

```
AGENTIC tools: ['document_lookup']
        validation: True
        "The document library contains the following documents:
         1. policy.docx  2. security_policy.docx  3. expense_policy.md
         4. meeting_notes.txt  5. travel_policy.md  6. employee_handbook.pdf
         7. hr_policy.md [1]"
```

It picked the catalogue tool rather than a similarity search. `document_lookup` returns the library listing — each filename with a clipped summary — **as a chunk**, because only chunks reach the answer generator; as pure metadata it could never have answered this.

### `unanswerable` — declining

```
AGENTIC attempts: 2
        tools: ['keyword_search', 'document_lookup', 'hybrid_search', 'keyword_search']
        validation: False
        "I could not find an answer to that question in the uploaded documents."
        0 citations
```

Two attempts, then it stopped and declined. No invented policy.

---

## Known weak spots

Shown honestly, because a demo that hides them is not much use.

**The 7B model is the accuracy ceiling, not retrieval.** In several runs the correct chunk ranked first and the validator still called the sources insufficient, triggering an unnecessary retry. A larger model closes most of this gap without any retrieval change.

**Naive often gets the right answer anyway.** With six documents the correct chunk usually ranks first regardless of mode. The difference shows in the *trace*, not always the answer: naive pulls in `meeting_notes.txt` and unrelated text that hybrid's narrowing eliminates before generation. That margin matters as a corpus grows, and the Compare tab is where you can see it.

**Enumeration is weak.** Questions like *"which documents mention probation?"* retrieve correctly but produce thin answers — there is no cross-document aggregation step. This is the clearest thing to build next.

---

## Regenerating the binary files

`security_policy.docx` and `employee_handbook.pdf` are committed. To rebuild them, edit and re-save in any editor — the demo only depends on the DOCX using real `Heading` styles and the PDF spanning several pages.
