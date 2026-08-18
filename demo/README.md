# PORT-6 Demo

A corpus, a CLI script, and a UI walkthrough.

| | |
|---|---|
| [WALKTHROUGH.md](WALKTHROUGH.md) | **Demoing to a person.** Every feature in one pass through the UI, with the exact inputs and the answers this corpus really returns. |
| [INPUTS.md](INPUTS.md) | The same inputs with no narration — paste from it while you talk. |
| `run_demo.py` | **Demoing to a terminal.** Uploads the corpus and runs every scenario headless. |

---

## The CLI script

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

First run takes a few minutes: every document is chunked, embedded and summarised by a local model.

> **For a clean demo, start with an empty library.** Any other document competes for the top-k slots and may end up cited. The script warns you if it finds any.

---

## The corpus

Ten documents in four formats, about 108 KB of text, indexing to roughly
200 chunks. Deliberately overlapping: five documents mention probation,
three mention data retention, and two give different figures for annual
leave. That overlap is what makes aggregation, scoping and conflict
detection worth showing.

| File | Format | Size | Why it is here |
|---|---|---|---|
| `hr_policy.md` | Markdown | 11 KB | The anchor. Three heading levels, most of the figures |
| `expense_policy.md` | Markdown | 8.6 KB | Caps, rates, an approval table, `FIN-2026-EXP` |
| `it_acceptable_use.md` | Markdown | 7.2 KB | Devices, BYOD, AI tool rules, `IT-AUP-204` |
| `travel_policy.md` | Markdown | 6.7 KB | Booking and class rules; overlaps HR on probation |
| `data_retention_schedule.md` | Markdown | 6.2 KB | Retention tables, `DR-SCH-2026` |
| `security_policy.docx` | **DOCX** | 40 KB | Real Word heading styles; `SEC-4412`, `SEC-8830`, ISO 27001 |
| `employee_handbook.pdf` | **PDF, 8 pages** | 13 KB | Page-numbered citations; grievance on page 6 |
| `overtime.txt` | Plain text | 5.1 KB | Pay formulas the calculator has to read out of the document |
| `onboarding_checklist.txt` | Plain text | 5.2 KB | No heading syntax at all — the structure fallback |
| `meeting_notes.txt` | Plain text | 4.7 KB | Deliberately vague. Competes for retrieval slots and loses |

`demo/documents/updates/hr_policy_2027.md` is **not** loaded by default.
It restates annual leave as 25 days, notice as 90 days and sick leave as
15 days, and exists to be uploaded during the demo so the conflict
handling has something to resolve.

### Regenerating the binaries

`security_policy.docx` and `employee_handbook.pdf` are committed so the
demo needs no build step. To change their content, edit
`demo/build_binaries.py` and run it:

```bash
uv run python demo/build_binaries.py
```

They are binaries rather than more Markdown because two features depend
on the format: the DOCX carries real `Heading 1/2/3` styles, so structure
comes from the document instead of a shape heuristic, and the PDF runs to
eight pages, so a page citation can be checked against the file.

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

**Naive often gets the right answer anyway.** On a corpus this small the correct chunk usually ranks first regardless of mode. The difference shows in the *trace*, not always the answer: naive pulls in `meeting_notes.txt` and unrelated text that hybrid's narrowing eliminates before generation. That margin matters as a corpus grows, and the Compare tab is where you can see it.

**Enumeration now works, and shows the difference between modes.** *"Which documents mention probation?"* is answered by coverage rather than top-k:

```
NAIVE   saw 2 documents  ->  "policy.pdf | employee_handbook.pdf"
HYBRID  saw 4 documents  ->  "policy.pdf [1], employee_handbook.pdf [3],
                              travel_policy.md [5], hr_policy.md [7]"
```

Naive ranks chunks, so five of them can come from one document and the
others are never seen. Hybrid detects the question, retrieves the best
chunks from *each* matching document, and excludes documents with no
keyword hit on the topic. It is the sharpest demonstration in the demo of
why the modes differ.

---

## Regenerating the binary files

`security_policy.docx` and `employee_handbook.pdf` are committed. To rebuild them, edit and re-save in any editor — the demo only depends on the DOCX using real `Heading` styles and the PDF spanning several pages.
