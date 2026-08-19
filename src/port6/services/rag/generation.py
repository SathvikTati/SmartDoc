"""Context building and cited answer generation, shared by all three modes.

Keeping this in one place means the modes differ only in how they retrieve,
which is the point of the comparison.
"""

from __future__ import annotations

import logging
import re

from port6.config import OLLAMA_NUM_CTX
from port6.services.llm.service import get_chat_model
from port6.services.rag.base import RetrievedChunk
from port6.services.rag.calculator import (
    CALCULATION_DOCUMENT_ID,
    augment_with_calculation,
)
from port6.services.rag.conflict import (
    context_note,
    find_conflicts,
    stamp_upload_times,
)
from port6.services.settings.service import get_prompt


logger = logging.getLogger(__name__)


NOT_FOUND_MARKER = "NOT_FOUND"

NOT_FOUND_ANSWER = (
    "I could not find an answer to that question in "
    "the uploaded documents."
)

NO_RESULTS_ANSWER = (
    "I could not find anything relevant to that question "
    "in the document library."
)

CITATION_PATTERN = re.compile(r"\[([\d\s,]+)\]")


def number_chunks(
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Renumber 1..n so [n] markers line up with the list order."""

    for position, chunk in enumerate(chunks, start=1):
        chunk.number = position

    return chunks


# Rough, and deliberately pessimistic: English prose with this much
# bracketed markup runs about 3.5 characters per token, and guessing low
# means the budget is under-spent rather than overrun.
CHARACTERS_PER_TOKEN = 3.5

# Left for the prompt template, the question and the answer itself.
CONTEXT_RESERVE_TOKENS = 1200


def fit_to_context(
    chunks: list[RetrievedChunk],
    budget_tokens: int | None = None,
) -> list[RetrievedChunk]:
    """Drop the weakest sources until the context fits the model's window.

    Something has to give when a large `top_k` meets a small window, and
    the question is only *what*. Left alone the model gives up the front of
    the prompt — llama.cpp shifts the oldest tokens out — which is the
    highest-ranked evidence, the chunk most likely to hold the answer. It
    then answers from the remainder with no sign anything is missing.

    Measured on the sample library at top_k=16 against a 2048-token
    window: four answers out of four, none of them right. The same
    question against 8192 was right four out of four.

    So the trim happens here instead, from the bottom, where dropping a
    chunk means losing the least likely source rather than the most.
    """

    if not chunks:
        return chunks

    budget = budget_tokens or OLLAMA_NUM_CTX
    allowance = int(
        max(budget - CONTEXT_RESERVE_TOKENS, 512) * CHARACTERS_PER_TOKEN
    )

    kept = list(chunks)

    while len(kept) > 1 and len(build_context(kept)) > allowance:
        kept.pop()

    if len(kept) < len(chunks):
        logger.warning(
            "Context budget of %d tokens fits %d of %d sources; dropped "
            "the %d lowest-ranked rather than letting the model truncate "
            "the highest",
            budget,
            len(kept),
            len(chunks),
            len(chunks) - len(kept),
        )

    return kept


def build_context(
    chunks: list[RetrievedChunk],
) -> str:
    """Render chunks as numbered sources, headed by their provenance."""

    parts = []

    for chunk in chunks:

        # A web result is marked in the context itself, so the model
        # attributes it as external rather than as one of the documents.
        if chunk.url:
            header = [f"[{chunk.number}] WEB: {chunk.filename}", chunk.url]

        # Likewise a worked sum: it is evidence, but it came from this
        # system rather than from anything someone uploaded.
        elif chunk.document_id == CALCULATION_DOCUMENT_ID:
            header = [f"[{chunk.number}] CALCULATION"]

        else:
            header = [f"[{chunk.number}] {chunk.filename}"]

        # The date is part of the evidence when two documents disagree:
        # the model is told to prefer the newer, and it can only do that
        # if it can see which one that is.
        if chunk.uploaded_at is not None:
            header.append(f"uploaded {chunk.uploaded_at:%Y-%m-%d}")

        if chunk.section_path:
            header.append(f"section: {chunk.section_path}")

        if chunk.page_number is not None:
            header.append(f"page {chunk.page_number}")

        parts.append(
            " | ".join(header) + "\n" + chunk.content
        )

    return "\n\n---\n\n".join(parts)


def is_degenerate(
    answer: str,
) -> bool:
    """True when a reply is citation markers with no actual statement.

    Small models sometimes answer a list-style question with just "[2]".
    That passes every other check — it has a valid citation and is not
    NOT_FOUND — but it tells the reader nothing, so it is caught here.
    """

    without_citations = CITATION_PATTERN.sub("", answer)

    letters = [
        character
        for character in without_citations
        if character.isalpha()
    ]

    return len(letters) < 15


def extract_cited_numbers(
    answer: str,
) -> list[int]:
    """Pull the [n] markers out of an answer, in order of first use."""

    cited: list[int] = []

    for group in CITATION_PATTERN.findall(answer):
        for part in group.split(","):

            part = part.strip()

            if not part.isdigit():
                continue

            number = int(part)

            if number not in cited:
                cited.append(number)

    return cited


# Words that already open a question or an instruction. Anything starting
# with one of these is left exactly as typed.
_ASKS = {
    "am", "are", "can", "ci", "compare", "could", "describe", "did", "do",
    "does", "explain", "find", "give", "how", "is", "list", "may", "might",
    "must", "name", "outline", "shall", "should", "show", "summarise",
    "summarize", "tell", "was", "were", "what", "when", "where", "which",
    "who", "whom", "whose", "why", "will", "would",
}

# Beyond this it is a sentence, whatever it starts with.
MAX_TOPIC_WORDS = 6

_WORDS = re.compile(r"[a-zA-Z']+")


def as_question(query: str) -> str:
    """Turn a bare topic into something that can be answered.

    People type "leave policy", not "what is the leave policy?". Retrieval
    handles that fine — the right chunks come back — but the answer prompt
    is told to reply NOT_FOUND when the sources do not contain *the
    answer*, and a topic phrase names no answer to look for. The model
    reads five relevant chunks and declines.

    Telling the prompt to allow topics helped some of the time and not
    others, which is the usual outcome of asking a 7B to notice something.
    Doing it here makes it certain, and it only affects what the generator
    is asked: retrieval still uses the words as typed, and the question
    shown back to the reader is unchanged.
    """

    stripped = (query or "").strip()

    # Already a question, or already an instruction.
    if "?" in stripped:
        return stripped

    words = _WORDS.findall(stripped.lower())

    if not words or len(words) > MAX_TOPIC_WORDS:
        return stripped

    if words[0] in _ASKS:
        return stripped

    return f"What do the documents say about {stripped}?"


async def _invoke(
    chain,
    query: str,
    context: str,
) -> str:

    response = await chain.ainvoke(
        {
            "query": query,
            "context": context,
        }
    )

    content = response.content

    if not isinstance(content, str):
        content = str(content)

    return content.strip()


def _credit_calculation_sources(
    citations: list[RetrievedChunk],
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Follow a cited calculation back to the chunks it was worked from.

    An answer that says "14 days remaining [6]" rests on the chunk holding
    "22 days accrued" just as much as on the arithmetic, but the model only
    writes the one marker. Left alone, the document that supplied the
    figure is reported as retrieved-but-unused — which is exactly backwards
    for the source doing the work.

    Appended rather than inserted, so the numbering the model wrote still
    lines up with the sources it named.
    """

    by_id = {chunk.chunk_id: chunk for chunk in chunks}

    already = {chunk.chunk_id for chunk in citations}

    credited = list(citations)

    for citation in citations:
        for chunk_id in citation.derived_from:

            source = by_id.get(chunk_id)

            if source is None or chunk_id in already:
                continue

            credited.append(source)
            already.add(chunk_id)

    return credited


async def generate_answer(
    query: str,
    chunks: list[RetrievedChunk],
    prompt_name: str = "answer_generation",
    context_builder=build_context,
) -> dict:
    """Generate an answer and resolve its citations back to chunks.

    The prompt and the way sources are rendered are both swappable, so an
    aggregation answer reuses every guard here — the NOT_FOUND sentinel,
    hallucinated-citation dropping and the degenerate-answer retry —
    rather than reimplementing them.
    """

    if not query.strip():
        raise ValueError("Query cannot be empty")

    if not chunks:
        return {
            "answer": NO_RESULTS_ANSWER,
            "answered": False,
            "citations": [],
            "chunks": [],
            "conflicts": [],
        }

    from port6.services.settings.service import get_setting

    # Recency first: the conflict check and the source headers both need
    # to know when each document was uploaded.
    conflicts = []

    if get_setting("conflicts.enabled"):
        stamp_upload_times(chunks)
        conflicts = find_conflicts(chunks)

    # Before numbering, so the worked sum takes its place in the list the
    # model cites from. Every mode goes through here, which is why naive
    # can answer "I have taken 8, how many are left?" without having a
    # tool-selecting agent in front of it.
    chunks = await augment_with_calculation(query, chunks)

    # Before numbering, so the markers the model is asked to cite match the
    # sources it was actually given. Trimming after numbering would leave
    # gaps that read as citable.
    chunks = fit_to_context(chunks)

    number_chunks(chunks)

    context = context_builder(chunks)

    # Prepended rather than folded into the builder, so the aggregate
    # layout gets the same warning without reimplementing it.
    note = context_note(conflicts)

    if note:
        context = f"{note}\n\n---\n\n{context}"

    chain = get_prompt(prompt_name) | get_chat_model()

    asked = as_question(query)

    if asked != query:
        logger.info("Asked as a topic; generating for %r", asked)

    answer = await _invoke(chain, asked, context)

    # One retry with an explicit nudge; a bare "[2]" is a formatting slip,
    # not a judgement that the sources are unusable.
    if is_degenerate(answer) and not answer.upper().startswith(
        NOT_FOUND_MARKER
    ):
        logger.warning(
            "Model returned a citation-only answer (%r); retrying",
            answer[:40],
        )

        answer = await _invoke(
            chain,
            (
                f"{asked}\n\n"
                "Write the answer as full sentences. Do not reply with "
                "only citation markers."
            ),
            context,
        )

        if is_degenerate(answer):
            return {
                "answer": (
                    "The sources appear relevant, but a readable answer "
                    "could not be generated from them."
                ),
                "answered": False,
                "citations": [],
                "chunks": chunks,
                "conflicts": conflicts,
            }

    # The mirror of the degenerate case, and the more damaging one: prose
    # with no markers anywhere. The aggregate layout is where it happens —
    # the model writes a heading per document with bullets underneath and
    # drops every marker on the way — and nothing downstream can recover
    # from it. Each source comes back "retrieved, unused", so a good answer
    # over four documents arrives with no evidence attached to any of it.
    #
    # The markers cannot be added here afterwards. A citation this system
    # wrote rather than read is exactly the laundered attribution the rest
    # of this module refuses, so the model is asked again instead.
    if (
        not answer.upper().startswith(NOT_FOUND_MARKER)
        and not extract_cited_numbers(answer)
    ):
        logger.warning(
            "Model answered without citing anything (%d sources given); "
            "retrying with an explicit instruction",
            len(chunks),
        )

        retried = await _invoke(
            chain,
            (
                f"{asked}\n\n"
                "Put the source number in square brackets after every "
                "statement, for example [1]. A heading naming the "
                "document is not a citation: the marker goes on the "
                "statement itself, including inside a list."
            ),
            context,
        )

        # Kept only if it actually fixed the problem. A retry that comes
        # back worse — shorter, or still bare — should not replace an
        # answer that at least reads correctly.
        if extract_cited_numbers(retried) and not is_degenerate(retried):
            answer = retried

        else:
            logger.warning(
                "Retry still cited nothing; answering with no citations"
            )

    if answer.upper().startswith(NOT_FOUND_MARKER):

        logger.info(
            "No answer found in sources for query: %s",
            query,
        )

        return {
            "answer": NOT_FOUND_ANSWER,
            "answered": False,
            "citations": [],
            "chunks": chunks,
            "conflicts": conflicts,
        }

    by_number = {chunk.number: chunk for chunk in chunks}

    citations = []

    for number in extract_cited_numbers(answer):

        chunk = by_number.get(number)

        # A model can cite a number that does not exist. Drop those rather
        # than returning a citation that points nowhere.
        if chunk is None:
            logger.warning(
                "Dropping hallucinated citation [%d]; only %d sources given",
                number,
                len(chunks),
            )
            continue

        citations.append(chunk)

    citations = _credit_calculation_sources(citations, chunks)

    logger.info(
        "Generated answer with %d citations",
        len(citations),
    )

    return {
        "answer": answer,
        "answered": True,
        "citations": citations,
        # The list the answer was actually generated from, which is not
        # what the caller passed in: a worked sum may have been added to
        # it. Callers report this as the retrieved evidence, so the
        # calculation shows up beside the documents it used.
        "chunks": chunks,
        # Reported even when the answer reads cleanly: the reader needs to
        # know a figure was chosen over another, not just what was chosen.
        "conflicts": conflicts,
    }
