# PORT-6 — Demo Inputs

Every input in demo order, with the setting and the answer this corpus
actually returns. Keep it open in a second window and paste from it.

The narrated version is [WALKTHROUGH.md](WALKTHROUGH.md). The corpus is
described in [README.md](README.md).

Assumes the ten files in `demo/documents/` are loaded and nothing else.
`demo/documents/updates/` is held back for the conflict step.

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
What does control SEC-8830 require?
```
→ auth events logged 12 months, network logs 90 days

```
What is the grievance procedure?
```
→ informal first, then written to People Operations; 5 days to
acknowledge, 15 to hear · `employee_handbook.pdf` **page 6**

```
How is part-time annual leave calculated?
```
→ 22 x 3 / 5 = 13.2 days for a three-day week · three heading levels deep

```
What is the company policy on pet insurance?
```
→ declines. Nothing in the corpus covers it.

---

## Topic phrases — not questions

Terse input is what people actually type. All of these answer.

```
leave policy
```
```
expense limits
```
```
data classification
```
```
shift allowances
```

---

## Scoping — select in `/files`, then "Ask about this"

Select **`travel_policy.md`**:
```
What does this say about probation?
```
→ probation needs extra approval for international travel

Select **`hr_policy.md`**, same question:
```
What does this say about probation?
```
→ 3 months, may not be extended, 1 week notice during probation

Select **both**:
```
What does probation affect?
```
→ bonus, training budget, unpaid leave *and* international travel

---

## Aggregation

```
What does each document say about probation?
```
→ **aggregated over 5 documents**, one short summary each: handbook,
hr_policy, hr_policy_2027, onboarding_checklist, travel_policy

```
Which documents mention data retention?
```
→ aggregated; `it_acceptable_use.md`, `data_retention_schedule.md`,
`security_policy.docx`

---

## Follow-ups — same conversation, in order

```
What is the maternity leave policy?
```
→ 28 weeks; 26 at full salary, 2 at statutory; request 6 weeks ahead

```
What about sick leave?
```
→ 12 days/year · trace: `follow_up · combine`
→ resolved to **"What is the sick leave policy?"** before retrieval

```
Who is eligible?
```
→ 26 weeks continuous service · resolved to **"Who is eligible for
maternity leave?"** — it tracked the subject back two turns

```
What is the expense limit for hotels?
```
→ 250 USD major cities / 150 elsewhere · trace: `new_topic · fresh`

---

## Arithmetic — any mode, try it on naive

```
I have taken 8 days of leave. How many leave days do I have remaining?
```
→ 14 · source **calculator**: `22 - 8 = 14`
→ the 22 is from `hr_policy.md`, the 8 from the question

```
My hourly rate is 20 and I worked 6 overtime hours. What is my overtime pay?
```
→ 180 · `20 * 1.5 * 6` — the x1.5 is in `overtime.txt`, not the question

```
I drove 120 business miles. What can I claim?
```
→ 54 GBP, from the 0.45/mile rate in `expense_policy.md`

---

## Conflicting documents

Upload the held-back revision:

```bash
curl -F "files=@demo/documents/updates/hr_policy_2027.md;type=text/markdown" \
  localhost:8000/upload
```

```
How much annual leave do employees get?
```
→ **25 days [1][3]. Previously, they received 22 days [5].**
→ banner: *Your documents disagree*

```
What is the notice period for resignation?
```
→ 90 days, previously 60

```
How many days of sick leave do employees get?
```
→ 15 days, previously 12

Delete `hr_policy_2027.md` afterwards to restore the other answers.

---

## Web search — agentic mode

```bash
curl -X PUT localhost:8000/settings/web.enabled \
  -H 'Content-Type: application/json' -d '{"value": true}'
```

```
What is the UK statutory maternity leave entitlement in weeks?
```
→ from the web, badged, with URL and domain

Then scope to `hr_policy.md` and ask it again:
→ declines. `web_search` is planned but returns
`{'skipped': 'question is scoped to specific documents'}`

```bash
curl -X PUT localhost:8000/settings/web.enabled \
  -H 'Content-Type: application/json' -d '{"value": false}'
```

---

## Greetings — no retrieval at all

```
hello
```
```
thanks
```
```
what can you do?
```
→ answered in 0 ms, no evidence panels

```
hi, how much annual leave do we get?
```
→ retrieves normally. Only a bare pleasantry short-circuits.

---

## Catalogue — agentic mode

```
What documents do I have?
```
→ all 10 files via the `document_lookup` tool

---

## `/search` — retrieval with no model

```
SEC-4412 password reuse
```
→ `security_policy.docx · 1.1 Password Requirements` top in all three
modes; the ranks below it differ

```
expense reimbursement
```

---

## `/compare`

```
What does each document say about probation?
```
→ naive ~2.8 s citing **3** documents · hybrid ~4.6 s citing **5** ·
agentic ~5.5 s citing **5**
→ the corpus is now big enough that the modes genuinely differ

---

## Config — curl

```bash
curl -s localhost:8000/prompts  | python3 -m json.tool | head -40
curl -s localhost:8000/settings | python3 -m json.tool | head -40

# rejected with 422: dropping a placeholder the pipeline needs
curl -X PUT localhost:8000/prompts/answer_generation \
  -H 'Content-Type: application/json' \
  -d '{"template": "You are helpful. Answer this: {query}"}'

curl -X POST localhost:8000/prompts/answer_generation/reset
curl -s localhost:8000/documents/attention
```

---

## Error states

- `/nonsense` → real 404 with a route back
- stop Ollama, then ask anything → classified provider error
- paste 1000+ characters → inline counter blocks it before sending
- a `FAILED` document → keeps its reason, offers Reprocess
