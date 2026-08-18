# PORT-6 — Demo Inputs

Every input in demo order, with nothing but the setting and the expected
answer. Keep this open in a second window and paste from it.

The narrated version, with the reasoning for each step, is in
[WALKTHROUGH.md](WALKTHROUGH.md).

Assumes the seven files in `demo/documents/` and nothing else in the
library. `uv run python demo/run_demo.py --reset` clears it.

---

## Ask — hybrid mode

```
How much annual leave do employees get?
```
→ 22 days per calendar year · `hr_policy.md`

```
What is control SEC-4412?
```
→ blocks reuse of the previous 12 passwords · `security_policy.docx`
→ the keyword half of hybrid; check the trace for `keyword`

```
What is the grievance procedure?
```
→ informal, then written to People Operations; 5 days to acknowledge,
15 to hear · `employee_handbook.pdf` **with a page number**

```
What is the company policy on pet insurance?
```
→ declines. Nothing in the corpus covers it.

---

## Scoping — select in `/files`, then "Ask about this"

Select **`travel_policy.md`**:
```
What does this say about probation?
```
→ probation requires extra approval for international travel

Select **`hr_policy.md`**, same question:
```
What does this say about probation?
```
→ 3 months, may not be extended

Select **both** — button reads "Ask about these 2 documents":
```
What does probation affect?
```
→ international travel *and* annual leave accrual, cited to both

---

## Aggregation

```
What does each document say about probation?
```
→ header reads **aggregated over 3 documents**; grouped per document

```
Which documents mention leave?
```

---

## Follow-ups — same investigation, in order

```
What is the maternity leave policy?
```
→ 28 weeks; request 6 weeks ahead

```
What about sick leave?
```
→ 12 days/year · trace: `follow_up · combine`
→ resolved to **"What is the sick leave policy?"** before retrieval

```
Who is eligible?
```
→ resolved against the same history

```
What is the expense limit for hotels?
```
→ 250 USD major cities / 150 elsewhere · trace: `new_topic · fresh`
→ the topic switch is detected; history is *not* dragged in

---

## Calculator — agentic mode

```
Annual leave is 22 days and I have taken 8. How many are left?
```
→ 14 · tools `calculate, semantic_search` · source **calculator**: `22 - 8 = 14`

```
What is 15% of the 250 USD hotel cap?
```
→ 37.5 USD · the 250 is retrieved, the multiplication is not the model

> **Do not demo overtime.** The formula lives in `overtime.txt` and the
> model writes the expression wrong (`20 * 6`, dropping the ×1.5).
> Known limitation — see WALKTHROUGH Act 6.

---

## Web search — agentic mode

Enable first:
```bash
curl -X PUT localhost:8000/settings/web.enabled \
  -H 'Content-Type: application/json' -d '{"value": true}'
```

```
What is the UK statutory maternity leave entitlement in weeks?
```
→ 26 weeks, from the web · results badged, with URL and domain

Now select **`hr_policy.md`** in `/files` and ask the **same question**:
→ declines. `web_search` appears in the tools row but returns
`{'skipped': 'question is scoped to specific documents'}`

Disable again:
```bash
curl -X PUT localhost:8000/settings/web.enabled \
  -H 'Content-Type: application/json' -d '{"value": false}'
```

---

## Catalogue — agentic mode

```
What documents do I have?
```
→ lists all files via the `document_lookup` tool

---

## `/search` — retrieval with no model

```
expense reimbursement
```
→ 3 chunks from `expense_policy.md`, tagged `semantic + keyword`
→ toggle semantic / keyword / hybrid and watch the order change

```
SEC-4412
```
→ keyword finds it; semantic alone struggles

---

## `/compare`

```
What does each document say about probation?
```
→ naive ~1.5s (3 docs) · hybrid ~1.5s (2) · agentic ~2.2s (2)
→ on a corpus this small the modes largely agree — that *is* the point
of the page. Don't oversell agentic here.

```
What is control SEC-4412?
```

---

## Config — curl

```bash
curl -s localhost:8000/prompts  | python3 -m json.tool | head -40
curl -s localhost:8000/settings | python3 -m json.tool | head -40

# rejected with 422: dropping a placeholder the pipeline needs
curl -X PUT localhost:8000/prompts/answer_generation \
  -H 'Content-Type: application/json' \
  -d '{"system": "You are helpful.", "human": "Answer this: {query}"}'

# back to what the release shipped
curl -X POST localhost:8000/prompts/answer_generation/reset

# anything stuck in a bad state
curl -s localhost:8000/documents/attention
```

---

## Error states

- `/nonsense` → real 404 with a route back
- stop Ollama, then ask anything → classified provider error, human sentence
- a `FAILED` document → keeps its reason, offers Reprocess
