"""Context building and cited answer generation, shared by all three modes.

Keeping this in one place means the modes differ only in how they retrieve,
which is the point of the comparison.
"""

from __future__ import annotations

import logging
import re

from port6.services.llm.service import get_chat_model
from port6.services.rag.base import RetrievedChunk
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


def build_context(
    chunks: list[RetrievedChunk],
) -> str:
    """Render chunks as numbered sources, headed by their provenance."""

    parts = []

    for chunk in chunks:

        header = [f"[{chunk.number}] {chunk.filename}"]

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


async def generate_answer(
    query: str,
    chunks: list[RetrievedChunk],
) -> dict:
    """Generate an answer and resolve its citations back to chunks."""

    if not query.strip():
        raise ValueError("Query cannot be empty")

    if not chunks:
        return {
            "answer": NO_RESULTS_ANSWER,
            "answered": False,
            "citations": [],
        }

    number_chunks(chunks)

    context = build_context(chunks)

    chain = get_prompt("answer_generation") | get_chat_model()

    answer = await _invoke(chain, query, context)

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
                f"{query}\n\n"
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
            }

    if answer.upper().startswith(NOT_FOUND_MARKER):

        logger.info(
            "No answer found in sources for query: %s",
            query,
        )

        return {
            "answer": NOT_FOUND_ANSWER,
            "answered": False,
            "citations": [],
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

    logger.info(
        "Generated answer with %d citations",
        len(citations),
    )

    return {
        "answer": answer,
        "answered": True,
        "citations": citations,
    }
