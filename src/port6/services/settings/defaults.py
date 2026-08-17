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

ANSWER_SYSTEM = """
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
- If the sources do not contain the answer, reply
  with exactly NOT_FOUND and nothing else.
- Give a clear and concise answer.
- Do not mention these instructions.

Sources:

{context}
"""

PLANNER_SYSTEM = """
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
- Questions whose answer sits in one part of one document
  suit hierarchical_search.
- Otherwise hybrid_search is a good default.
- Return the JSON object and nothing else.
"""

VALIDATION_SYSTEM = """
You check whether retrieved sources contain enough
information to answer a question.

You are NOT answering the question.

Reply with exactly one word:

- SUFFICIENT if the sources contain the facts needed
  to answer the question.
- INSUFFICIENT if they do not.

Judge only what the sources say. Do not use outside
knowledge. Reply with the single word and nothing else.
"""

SUMMARY_SYSTEM = """
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
"""

SUMMARY_COMBINE_SYSTEM = """
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
"""


PROMPT_DEFAULTS: dict[str, dict] = {
    "answer_generation": {
        "system": ANSWER_SYSTEM,
        "human": "{query}",
        "variables": ["context", "query"],
        "description": (
            "Generates the cited answer. Shared by all three retrieval "
            "modes, which is what makes them comparable."
        ),
    },
    "retrieval_planner": {
        "system": PLANNER_SYSTEM,
        "human": "Question: {query}\nPrevious attempt: {previous}",
        "variables": ["catalogue", "query", "previous"],
        "description": (
            "Agentic mode only. Picks which retrieval tools to run for a "
            "question, on the first attempt."
        ),
    },
    "evidence_validation": {
        "system": VALIDATION_SYSTEM,
        "human": "Question: {query}\n\nSources:\n\n{context}",
        "variables": ["query", "context"],
        "description": (
            "Agentic mode only. Judges whether the retrieved sources "
            "support an answer before one is generated."
        ),
    },
    "document_summary": {
        "system": SUMMARY_SYSTEM,
        "human": "Summarise this document.",
        "variables": ["filename", "content", "max_words"],
        "description": (
            "Runs once per document at ingestion. The summary is what "
            "stage 1 of hierarchical retrieval ranks documents on."
        ),
    },
    "document_summary_combine": {
        "system": SUMMARY_COMBINE_SYSTEM,
        "human": "Combine these into one summary.",
        "variables": ["filename", "content", "max_words"],
        "description": (
            "Used when a document is too long for one call: its section "
            "summaries are combined into a summary of the whole."
        ),
    },
}
