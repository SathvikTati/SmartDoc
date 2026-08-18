"""The shipped values for every runtime setting and prompt.

These are the source of truth for a fresh database: startup seeds any key
that is missing, so a new install and an upgraded one end up with the same
content. Once a row exists it is never overwritten — an edit made through
the API survives a restart, which is the whole point of storing them.

What does *not* live here:

- which model to call, and how to reach it — that is `.env`, because
  swapping providers is a deployment decision, not a runtime tweak
- upload limits and the Chroma path — `config.yaml`, because they are
  deploy-time facts and the vector store must open before the database is
  necessarily reachable
"""

from __future__ import annotations


# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------

SETTING_DEFAULTS: dict[str, dict] = {
    "chunking.chunk_size": {
        "value": 1000,
        "description": "Target characters per chunk.",
    },
    "chunking.chunk_overlap": {
        "value": 200,
        "description": (
            "Characters repeated between neighbouring chunks so a "
            "sentence split across the boundary is still retrievable."
        ),
    },
    "defaults.mode": {
        "value": "hybrid",
        "description": (
            "The retrieval mode a new chat starts with: naive, hybrid or "
            "agentic. Chats stay on the three families deliberately — "
            "choosing between the strategies inside one is what the "
            "Pipelines page is for. A request naming its own mode or "
            "pipeline overrides this."
        ),
    },
    "defaults.top_k": {
        "value": 5,
        "description": (
            "How many chunks a new chat retrieves. More is not always "
            "better: past a point the extra chunks are near-misses that "
            "dilute the context the answer is written from."
        ),
    },
    "retrieval.max_distance": {
        "value": None,
        "description": (
            "Drop chunks whose embedding distance exceeds this before "
            "generating. null disables the filter."
        ),
    },
    "summary.max_input_characters": {
        "value": 12000,
        "description": (
            "Characters sent per summarisation call. A longer document is "
            "summarised in sections and the parts combined."
        ),
    },
    "summary.max_words": {
        "value": 150,
        "description": "Target length of a document summary.",
    },
    "summary.max_sections": {
        "value": 6,
        "description": (
            "Most section summaries to produce for a long document before "
            "combining them. Bounds the cost of ingesting a large file."
        ),
    },
    "agent.max_attempts": {
        "value": 2,
        "description": (
            "How many times the agent may plan and retrieve before it has "
            "to answer or decline."
        ),
    },
    "agent.catalogue_limit": {
        "value": 50,
        "description": (
            "Most documents document_lookup will list. Bounds the context "
            "a catalogue question can consume."
        ),
    },
    "agent.catalogue_summary_characters": {
        "value": 140,
        "description": (
            "How much of each summary the catalogue shows, so filenames "
            "stay legible in a long listing."
        ),
    },
    "validation.min_overlap": {
        "value": 0.2,
        "description": (
            "Below this share of the question's key terms in the retrieved "
            "text, evidence is rejected without asking the model."
        ),
    },
    "validation.skip_model_above": {
        "value": 0.75,
        "description": (
            "Above this overlap the evidence is accepted without asking "
            "the model. Small models produce false negatives on obviously "
            "good retrievals, and each one costs a wasted retry."
        ),
    },
    "conflicts.enabled": {
        "value": True,
        "description": (
            "Notice when two documents give different figures for the "
            "same thing, answer from the most recently uploaded, and say "
            "what the older one said."
        ),
    },
    "calculation.enabled": {
        "value": True,
        "description": (
            "After retrieval, work out any arithmetic the answer depends "
            "on and offer the result as a source. Runs in every mode, so "
            "a question needing a sum is not left to the model's "
            "arithmetic."
        ),
    },
    "aggregation.enabled": {
        "value": True,
        "description": (
            "Detect questions that need breadth across documents "
            "(\"which documents mention X\") and retrieve for coverage "
            "instead of depth."
        ),
    },
    "aggregation.max_documents": {
        "value": 8,
        "description": (
            "Most documents an aggregation answer covers. Bounds the "
            "context an enumeration question can consume."
        ),
    },
    "aggregation.chunks_per_document": {
        "value": 2,
        "description": (
            "Chunks taken from each document when aggregating, so one "
            "verbose document cannot crowd the others out."
        ),
    },
    "aggregation.excerpt_characters": {
        "value": 420,
        "description": (
            "How much of each chunk an aggregation answer sees per "
            "document. Aggregation is about breadth, and handed the full "
            "text of six documents the model transcribes instead of "
            "summarising."
        ),
    },
    "aggregation.require_keyword_match": {
        "value": True,
        "description": (
            "When aggregating, only cover documents the keyword retriever "
            "actually found. Semantic search returns the nearest chunk from "
            "every document whether or not it mentions the topic, and those "
            "near-misses dilute an enumeration answer."
        ),
    },
    "conversation.enabled": {
        "value": True,
        "description": (
            "Resolve a question against the conversation it arrived in, so "
            "\"what about sick leave?\" is understood as a follow-up."
        ),
    },
    "conversation.history_turns": {
        "value": 4,
        "description": (
            "Recent turns shown to the follow-up classifier. Enough to "
            "resolve a reference, short enough that a stale topic from ten "
            "questions ago cannot pull the answer off course."
        ),
    },
    "conversation.carry_over_chunks": {
        "value": 3,
        "description": (
            "Chunks carried from the previous turn into a follow-up's "
            "context. Capped so prior material cannot outweigh what the "
            "rewritten question actually retrieved."
        ),
    },
    "web.enabled": {
        "value": False,
        "description": (
            "Offer the web_search tool to the agent. Off by default: an "
            "answer citing the public internet is a different promise "
            "from one citing only your documents, so reaching outside "
            "the library is an explicit choice."
        ),
    },
    "history.retain_runs": {
        "value": 500,
        "description": (
            "Most query runs kept. The oldest are trimmed beyond this so "
            "history cannot grow without bound."
        ),
    },
}


# -------------------------------------------------------------------
# Prompts
# -------------------------------------------------------------------

ANSWER_TEMPLATE = """
You are an enterprise document question-answering assistant.

Answer the user's question using ONLY the numbered
sources below.

Rules:
- Do not use outside knowledge.
- Do not invent information.
- Cite the source number in square brackets after
  every statement you make, for example: [1].
- If two sources support the same statement, cite
  both, for example: [1][3].
- Only cite source numbers that appear below.
- Cite a source only if it states what you just wrote.
  Never attach a citation to a fact you knew already.
- A source marked WEB is from the public internet, not
  the user's own documents. Say which of the two a
  statement comes from, and never merge a figure from a
  document with one from the web as though they were the
  same fact.
- A source marked CALCULATION is arithmetic this system
  evaluated from figures in the other sources. It is
  correct. Use its result and cite it like any other
  source, rather than doing the sum yourself.
- A figure the sources do not state directly, but which a
  CALCULATION source works out, counts as answered.
- If a NOTE above the sources says the documents disagree,
  answer with the figure from the most recently uploaded
  document, then add one short sentence saying what the
  older document said and that it appears to be superseded.
  Never average the two, and never present both as equally
  current.
- The input may be a topic rather than a question —
  "leave policy", "expense limits", "probation". Say what
  the sources contain on that topic. Not being phrased as
  a question is never a reason to reply NOT_FOUND.
- If the sources do not contain the answer, reply
  with exactly NOT_FOUND and nothing else.
- Give a clear and concise answer.
- Do not mention these instructions.

Sources:

{context}

Question: {query}

Answer:
"""

PLANNER_TEMPLATE = """
You plan document retrieval. You do not answer questions.

Available tools:

{catalogue}

Given the question, choose between 1 and 3 tools that
together will find the evidence needed.

Reply with ONLY a JSON object:

{{"tools": ["tool_name", ...], "reason": "one short sentence"}}

Guidance:
- Questions naming exact terms, codes or rare words need
  keyword_search.
- Questions about what documents exist need document_lookup.
- Questions about the library as a whole — which documents
  mention X, comparing across documents, what each policy
  says — need aggregate_search.
- A question whose answer requires arithmetic needs
  calculate as well as a retrieval tool: retrieve the
  numbers, then compute with them.
- Questions whose answer sits in one part of one document
  suit hierarchical_search.
- Otherwise hybrid_search is a good default.
- Return the JSON object and nothing else.

Question: {query}
Previous attempt: {previous}
"""

VALIDATION_TEMPLATE = """
You check whether retrieved sources contain enough
information to answer a question.

You are NOT answering the question.

Reply with exactly one word:

- SUFFICIENT if the sources contain the facts needed
  to answer the question.
- INSUFFICIENT if they do not.

Judge only what the sources say. Do not use outside
knowledge. Reply with the single word and nothing else.

Question: {query}

Sources:

{context}
"""

SUMMARY_TEMPLATE = """
You are a document summarisation assistant.

Summarise the document below in at most
{max_words} words.

Rules:
- Use only what the document says.
- Do not invent information.
- Write plain prose, no bullet points or headings.
- Do not mention these instructions.

Document: {filename}

{content}

Summarise this document.
"""

FOLLOW_UP_TEMPLATE = """
You decide how a new question relates to the conversation
before it. You never answer the question itself.

Reply with ONLY a JSON object, with these four keys:

  relation             "follow_up" or "new_topic"
  standalone_question  the question, rewritten to be
                       searchable on its own
  strategy             "combine" or "reuse"
  reason               why, in your own words

Worked examples.

Conversation:
Q: What is the maternity leave policy?
A: Employees are entitled to 26 weeks of paid maternity leave.
New question: What about sick leave?
{{"relation": "follow_up", "standalone_question": "What is the sick leave policy?", "strategy": "combine", "reason": "Asks the same thing about a different kind of leave."}}

Conversation:
Q: What is the sick leave policy?
A: Employees receive 12 days of paid sick leave per year.
New question: Who is eligible?
{{"relation": "follow_up", "standalone_question": "Who is eligible for sick leave?", "strategy": "combine", "reason": "Eligibility for the sick leave just discussed."}}

Conversation:
Q: What is the maternity leave policy?
A: Employees are entitled to 26 weeks of paid maternity leave.
New question: What is the expense limit for hotels?
{{"relation": "new_topic", "standalone_question": "What is the expense limit for hotels?", "strategy": "combine", "reason": "Expenses are unrelated to leave."}}

Conversation:
Q: What is control SEC-4412?
A: It blocks the reuse of the previous 12 passwords.
New question: Explain that more simply.
{{"relation": "follow_up", "standalone_question": "Explain control SEC-4412 more simply.", "strategy": "reuse", "reason": "Asks about the material already retrieved."}}

Rules:
- "follow_up" means the question cannot be understood alone:
  it uses a pronoun, drops its subject, or narrows what came
  before.
- "new_topic" means a different subject. When unsure choose
  "new_topic" — carrying the wrong context into an unrelated
  question produces a confident wrong answer.
- relation is only ever "follow_up" or "new_topic".
- Resolve against the most recent turn unless the question
  clearly points further back.
- Always fill standalone_question with real words from the
  conversation. Never leave a placeholder.
- Use "reuse" only for questions about the material already
  retrieved (restate it, explain it, summarise it).
- Output the JSON object and nothing else.

Conversation:

{history}

New question: {question}
"""

CALCULATION_TEMPLATE = """
You turn a question into a single arithmetic expression.
You never answer the question.

Use only numbers and formulas that appear in the question
or in the sources below. Reply with the expression alone —
no words, no equals sign, no units.

Reply with exactly NONE when the expression cannot be built
from the question and the sources alone. That includes when
the *operation* is missing, even though the numbers are
present. A wrong number is worse than no number: it is
handed to the answer as evidence.

Worked examples.

Sources: Employees accrue 22 days of paid annual leave per calendar year.
Question: I have taken 8 days of leave. How many do I have remaining?
22 - 8

Sources: Hotel accommodation is capped at 250 USD per night in major cities.
Question: What is 15% of the hotel cap?
250 * 0.15

Sources: Overtime pay = Hourly pay rate x 1.5 x overtime hours worked.
Question: My hourly rate is 20 and I worked 6 overtime hours. What is my overtime pay?
20 * 1.5 * 6

Sources: Employees must give 60 days written notice of resignation.
Question: What is the maternity leave entitlement?
NONE

Sources: Control SEC-4412 blocks the reuse of the previous 12 passwords.
Question: What is control SEC-4412?
NONE

Sources:

{context}

Question: {question}
"""

AGGREGATE_TEMPLATE = """
You are an enterprise document question-answering assistant.

The question asks about the document library as a whole, so
the sources below are grouped by the document they came from.

Answer using ONLY those sources.

Rules:
- Go through the documents one by one. Name each document
  and say what it contributes, in one or two sentences.
- Summarise in your own words. Never copy a source's
  header line, and never reproduce "| section: ..." or
  "| page N" — those label the sources for you, they are
  not part of the answer.
- Do not quote a source at length. The reader can open it;
  what they need here is what each document adds.
- Cite the source number in square brackets after every
  statement, for example: [1].
- Only cite source numbers that appear below.
- A document that does not address the question should be
  left out rather than described as silent.
- Do not invent documents that are not listed below.
- If none of the documents address the question, reply with
  exactly NOT_FOUND and nothing else.
- Do not mention these instructions.

Sources, grouped by document:

{context}

Question: {query}

Answer:
"""

SUMMARY_COMBINE_TEMPLATE = """
You are a document summarisation assistant.

Below are summaries of consecutive parts of one document,
in order. Combine them into a single summary of the whole
document, in at most {max_words} words.

Rules:
- Cover the whole document, not only its opening.
- Use only what the parts say.
- Do not invent information.
- Write plain prose, no bullet points or headings.
- Do not mention these instructions.

Document: {filename}

{content}

Combine these into one summary.
"""


# Each prompt is a single template rather than a system/human pair. The
# split bought nothing — every prompt put its instructions, its sources
# and its question in a fixed order anyway — and cost a reader two fields
# to hold in their head, and an editor two boxes to keep consistent.
PROMPT_DEFAULTS: dict[str, dict] = {
    "answer_generation": {
        "template": ANSWER_TEMPLATE,
        "variables": ["context", "query"],
        "description": (
            "Generates the cited answer. Shared by all three retrieval "
            "modes, which is what makes them comparable."
        ),
    },
    "retrieval_planner": {
        "template": PLANNER_TEMPLATE,
        "variables": ["catalogue", "query", "previous"],
        "description": (
            "Chooses which retrieval tools the agent runs, from the "
            "catalogue of those currently available."
        ),
    },
    "evidence_validation": {
        "template": VALIDATION_TEMPLATE,
        "variables": ["query", "context"],
        "description": (
            "Judges whether the retrieved sources can answer the "
            "question, which is what decides a retry."
        ),
    },
    "aggregate_answer": {
        "template": AGGREGATE_TEMPLATE,
        "variables": ["context", "query"],
        "description": (
            "Answers a question about the library as a whole, walking "
            "the documents one by one instead of writing one paragraph."
        ),
    },
    "follow_up_resolution": {
        "template": FOLLOW_UP_TEMPLATE,
        "variables": ["history", "question"],
        "description": (
            "Decides whether a question continues the conversation or "
            "starts a new topic, and rewrites a follow-up to stand alone."
        ),
    },
    "calculation_expression": {
        "template": CALCULATION_TEMPLATE,
        "variables": ["question", "context"],
        "description": (
            "Turns a question into an arithmetic expression for the "
            "calculator, using formulas and figures from the retrieved "
            "sources as well as from the question itself."
        ),
    },
    "document_summary": {
        "template": SUMMARY_TEMPLATE,
        "variables": ["filename", "content", "max_words"],
        "description": (
            "Runs once per document at ingestion. The summary is what "
            "stage 1 of hierarchical retrieval ranks documents on."
        ),
    },
    "document_summary_combine": {
        "template": SUMMARY_COMBINE_TEMPLATE,
        "variables": ["filename", "content", "max_words"],
        "description": (
            "Used when a document is too long for one call: its section "
            "summaries are combined into a summary of the whole."
        ),
    },
}
