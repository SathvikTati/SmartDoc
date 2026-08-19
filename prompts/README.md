# Prompts

Every prompt the system sends to a model, one file each, so they can be
read and diffed without opening the code.

**These files are copies.** The shipped templates live in
`PROMPT_DEFAULTS`, in
[`src/port6/services/settings/defaults.py`](../src/port6/services/settings/defaults.py),
and that is what a fresh database is seeded from. Editing a file here
changes nothing at runtime. `tests/test_prompt_files.py` fails if a copy
drifts from the template it mirrors, so what you read here is what the
model is sent.

To change a prompt on a running install, edit it through the API. To
change it for every install, edit `defaults.py` and regenerate:

```bash
python prompts/export.py
```

That rewrites these files and the settings reference block in
`config.yaml`. It is idempotent, and it is the fix for a drift failure.

## The eight

| file | placeholders | what it decides |
|---|---|---|
| `answer_generation.txt` | `{context}` `{query}` | the cited answer. Shared by all three retrieval modes, which is what makes them comparable |
| `aggregate_answer.txt` | `{context}` `{query}` | questions about the library as a whole, walking the documents one by one |
| `retrieval_planner.txt` | `{catalogue}` `{query}` `{previous}` | which tools the agent runs, from those currently available |
| `evidence_validation.txt` | `{query}` `{context}` | whether the retrieved sources can answer the question, which is what decides a retry |
| `follow_up_resolution.txt` | `{history}` `{question}` | whether a question continues the conversation, and the standalone rewrite retrieval runs on |
| `calculation_expression.txt` | `{question}` `{context}` | the arithmetic expression handed to the calculator |
| `document_summary.txt` | `{filename}` `{content}` `{max_words}` | the per-document summary that stage 1 of hierarchical retrieval ranks on |
| `document_summary_combine.txt` | `{filename}` `{content}` `{max_words}` | one summary of a long document, from its section summaries |

## The placeholders are a contract

Each prompt is formatted with a fixed set of variables, listed above. An
edit that drops one is rejected with a 422 rather than accepted, because
a template missing `{context}` would not raise — it would ask the model
to answer with no sources and cite them anyway, which surfaces as a
confidently wrong answer instead of an error. A stray `{` is rejected for
the same reason. See `_check_variables` in
[`settings/service.py`](../src/port6/services/settings/service.py).

## Editing a running install

```bash
# Read one, with its shipped default alongside the live value.
curl -s localhost:8000/prompts/answer_generation | python3 -m json.tool

# Change it. The edit is stored in the database and survives restarts,
# which is the whole reason prompts live there rather than in code.
curl -X PUT localhost:8000/prompts/answer_generation \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"template": open("prompts/answer_generation.txt").read()}))')"

# Back to the shipped template for this release.
curl -X POST localhost:8000/prompts/answer_generation/reset
```

One behaviour to know before editing anything. On startup, a prompt row
that still matches its shipped default **follows** the new default, so a
release can improve a prompt and have it reach installs that already ran.
A row you have edited is never touched again — which also means it will
not receive later fixes. `reset` is what opts a prompt back in.

## Why they read the way they do

Most of the odd-looking lines in these files are scar tissue, and the
comments in `defaults.py` say what from. A few worth knowing:

- **Worked examples beat rules.** Every rule that a 7B ignored was fixed
  by showing it rather than stating it. `calculation_expression.txt`
  teaches banded rates with a mileage example because the rule alone left
  six Saturday overtime hours priced as four.
- **The citation marker is not scaffolding.** `aggregate_answer.txt`
  spells this out because the model was mirroring the grouped context's
  shape and stripping `[n]` on the way, which produced good four-document
  answers with every source reported as retrieved-but-unused.
- **A verdict needs its comparison written out.** `answer_generation.txt`
  makes the reader see "the entitlement is 12 days, 30 is greater than
  12, so no" because a bare yes/no was frequently the wrong one — and the
  same rule, applied to a question that *asserts* a figure, is what stops
  "is the monthly allowance 300 GBP?" being answered yes off the one-off
  payment that happens to share the number.
- **`NOT_FOUND` is a sentinel, not prose.** Several prompts end by
  demanding it exactly, because the code tests for it to decide whether
  an answer was found at all.
