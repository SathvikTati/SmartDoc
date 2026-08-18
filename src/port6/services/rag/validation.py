"""Evidence validation.

Checks the retrieved context actually supports an answer before that answer
is trusted, so the agentic mode can retry with a different strategy instead
of generating from thin evidence.

A cheap deterministic check runs first. It rejects the obvious cases
(nothing retrieved, no overlap with the question) and — just as importantly —
accepts the obvious ones: above `validation.skip_model_above` the model is
never asked. Small models produce false negatives on plainly good sources,
and in agentic mode each one costs a full retry that changes nothing.

The model check runs only in the band between those two thresholds, which is
where the judgement is actually needed.
"""

from __future__ import annotations

import logging

from port6.services.llm.service import get_chat_model
from port6.services.rag.aggregation import SCAFFOLDING
from port6.services.rag.base import RetrievedChunk
from port6.services.rag.generation import build_context
from port6.services.rag.retrievers import tokenize
from port6.services.settings.service import get_float, get_prompt


logger = logging.getLogger(__name__)


# Words too common to count as evidence of topical overlap.
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "do", "does", "did", "of", "for", "to", "in", "on", "at", "by", "with",
    "and", "or", "but", "if", "then", "than", "that", "this", "these",
    "those", "it", "its", "as", "from", "about", "into", "our", "us", "we",
    "you", "your", "i", "me", "my", "can", "could", "should", "would",
    "will", "shall", "may", "might", "must", "have", "has", "had", "get",
    "gets", "got", "there", "here", "any", "all", "some", "every", "each",
    "policy", "document", "documents",
}


# "Which documents mention probation?" scores on {mention, probation}, and
# "mention" never appears in a policy — so a perfect retrieval measured
# 50% and fell into the band where the model is asked, which then rejected
# it and cost a retry. The words that frame a question are not evidence
# that it was answered.
SCORED_AGAINST = STOPWORDS | SCAFFOLDING


class ValidationResult:

    def __init__(
        self,
        sufficient: bool,
        reason: str,
        method: str,
    ) -> None:
        self.sufficient = sufficient
        self.reason = reason
        self.method = method

    def as_dict(self) -> dict:
        return {
            "sufficient": self.sufficient,
            "reason": self.reason,
            "method": self.method,
        }


def keyword_overlap(
    query: str,
    chunks: list[RetrievedChunk],
) -> float:
    """Share of meaningful query words that appear in the retrieved text."""

    query_terms = {
        token
        for token in tokenize(query)
        if token not in SCORED_AGAINST and len(token) > 2
    }

    if not query_terms:
        return 1.0

    corpus_terms = set()

    for chunk in chunks:
        corpus_terms.update(tokenize(chunk.content))
        corpus_terms.update(tokenize(chunk.section_path or ""))
        corpus_terms.update(tokenize(chunk.filename or ""))

    hit = query_terms & corpus_terms

    return len(hit) / len(query_terms)


async def validate_evidence(
    query: str,
    chunks: list[RetrievedChunk],
    use_model: bool = True,
    min_overlap: float | None = None,
    skip_model_above: float | None = None,
) -> ValidationResult:

    if not chunks:
        return ValidationResult(
            sufficient=False,
            reason="Nothing was retrieved.",
            method="empty",
        )

    if min_overlap is None:
        min_overlap = get_float("validation.min_overlap")

    if skip_model_above is None:
        skip_model_above = get_float("validation.skip_model_above")

    overlap = keyword_overlap(query, chunks)

    if overlap < min_overlap:
        return ValidationResult(
            sufficient=False,
            reason=(
                f"Retrieved text shares only {overlap:.0%} of the "
                "question's key terms."
            ),
            method="lexical",
        )

    # A retrieval this strong does not need a second opinion, and asking
    # for one is where the false negatives came from: a small model would
    # call obviously-good sources insufficient, costing a full retry that
    # produced the same answer. Above the threshold, trust the retrieval.
    if overlap >= skip_model_above:
        return ValidationResult(
            sufficient=True,
            reason=(
                f"Retrieved text covers {overlap:.0%} of the question's "
                "key terms; accepted without a model check."
            ),
            method="lexical-strong",
        )

    if not use_model:
        return ValidationResult(
            sufficient=True,
            reason=f"Lexical overlap {overlap:.0%}.",
            method="lexical",
        )

    try:
        chain = get_prompt("evidence_validation") | get_chat_model()

        response = await chain.ainvoke(
            {
                "query": query,
                "context": build_context(chunks),
            }
        )

        verdict = response.content

        if not isinstance(verdict, str):
            verdict = str(verdict)

        verdict = verdict.strip().upper()

        sufficient = verdict.startswith("SUFFICIENT")

        return ValidationResult(
            sufficient=sufficient,
            reason=(
                "Model judged the sources sufficient."
                if sufficient
                else "Model judged the sources insufficient."
            ),
            method="model",
        )

    except Exception as exc:
        # A validator that cannot run must not block an answer; fall back
        # to the lexical signal rather than reporting a false negative.
        logger.warning(
            "Evidence validation failed, falling back to lexical: %s",
            exc,
        )

        return ValidationResult(
            sufficient=True,
            reason=f"Validator unavailable; lexical overlap {overlap:.0%}.",
            method="lexical-fallback",
        )
