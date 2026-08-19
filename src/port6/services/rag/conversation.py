"""Resolving a question against the conversation it arrived in.

    Q1  "What is the maternity leave policy?"
    Q2  "What about sick leave?"
    Q3  "Who is eligible?"

Q2 and Q3 are not searchable as written. "What about sick leave?" retrieves
almost nothing, and "Who is eligible?" retrieves eligibility criteria from
every policy in the library. Both only mean something relative to what came
before.

Three decisions get made here:

1. **Is it a follow-up at all?** The dangerous failure is the false
   positive — dragging maternity-leave context into an unrelated question
   about expenses produces a confidently wrong answer. So the default is
   "new topic", and a follow-up has to be argued for.

2. **What is the standalone question?** A follow-up is rewritten so
   retrieval has something to work with: "Who is eligible?" becomes "Who is
   eligible for sick leave?".

3. **What happens to the previous chunks?**
   - `fresh`   — new topic. Prior context is discarded entirely.
   - `combine` — retrieve on the rewritten question and merge with the
     previous turn's chunks. The default for a follow-up, because the
     answer usually needs both.
   - `reuse`   — the question is *about* what was already retrieved
     ("explain that more simply"), so no retrieval runs at all.

The classification is one small model call, and only when there is history
to classify against. A first question never pays for it.
"""

from __future__ import annotations

import json
import logging
import re

from port6.services.llm.service import get_chat_model
from port6.services.rag.aggregation import is_aggregation_question
from port6.services.rag.base import RetrievedChunk
from port6.services.settings.service import get_int, get_prompt


logger = logging.getLogger(__name__)


NEW_TOPIC = "new_topic"
FOLLOW_UP = "follow_up"

FRESH = "fresh"
COMBINE = "combine"
REUSE = "reuse"


class Resolution:
    """What to do with a question given the conversation so far."""

    def __init__(
        self,
        relation: str,
        strategy: str,
        search_question: str,
        reason: str,
        method: str,
        standalone_question: str | None = None,
    ) -> None:
        self.relation = relation
        self.strategy = strategy
        # What retrieval actually runs on.
        self.search_question = search_question
        self.standalone_question = standalone_question
        self.reason = reason
        self.method = method

    @property
    def is_follow_up(self) -> bool:
        return self.relation == FOLLOW_UP

    def as_dict(self) -> dict:
        return {
            "relation": self.relation,
            "strategy": self.strategy,
            "search_question": self.search_question,
            "standalone_question": self.standalone_question,
            "reason": self.reason,
            "method": self.method,
        }


def first_turn(question: str) -> Resolution:
    """No history, so nothing to resolve against."""

    return Resolution(
        relation=NEW_TOPIC,
        strategy=FRESH,
        search_question=question,
        reason="First question in the conversation.",
        method="no-history",
    )


# A question carrying none of these needs no conversation to be searchable,
# so the classifier is skipped and it is treated as a new topic. This is the
# cheap half of the decision: it removes a model call from most questions.
#
# It is not, as this comment once claimed, a gate that can only fail safe.
# Ignoring context that a question needed produces a confident "not in the
# library" for something the previous turn had just answered — which reads
# as the document being missing rather than the question being misread. So
# the signals below err towards consulting the classifier.
_DEPENDENT_SIGNALS = [
    r"^\s*(and|but|so|also|then)\b",
    r"\bwhat about\b",
    r"\bhow about\b",
    r"\bwhat if\b",
    # Bare pronouns and demonstratives with no noun of their own.
    r"\b(it|its|they|them|their|those|these|that|this|there)\b",
    r"\b(he|she|his|her|him)\b",
    # A bare interrogative with little body of its own: "Who is
    # eligible?" (12 characters after the word) depends on context;
    # "How much annual leave do employees get?" (39) does not.
    #
    # 34 rather than 20, because 20 let "Which benefits are restricted?"
    # (24) through as self-contained. Searched as written it retrieves
    # nothing about the probation restrictions the conversation was
    # actually discussing, and the turn came back "not in the library"
    # immediately after a turn that had answered exactly that. The
    # self-contained questions this now sends to the classifier —
    # "Which policy covers international travel expenses?",
    # "When must carried-over annual leave be taken by?" — all stay
    # above it, and library-wide questions are short-circuited above.
    r"^\s*(who|when|where|why|how|which)\b[^?]{0,34}\??\s*$",
    r"\b(the same|similar|instead|as well|too|either)\b",
    r"\b(more|less|further|another|other|next|previous)\b",
    r"\b(explain|elaborate|clarify|simpler|summari[sz]e)\b",
    # A correction of the turn before it: "no the annual leaves", "i meant
    # annual leave", "actually annual". These are the most unmistakable
    # follow-ups there are, and every one of them used to be searched as
    # written — so the correction was answered as though it were a fresh
    # question about the words "no the annual leaves", and failed.
    r"^\s*(no|nope|not)\b",
    r"^\s*actually\b",
    r"\b(i meant|i mean)\b",
    r"^\s*\w+\s*\??\s*$",
]

_DEPENDENT = [re.compile(pattern, re.IGNORECASE) for pattern in _DEPENDENT_SIGNALS]

_WORDS = re.compile(r"[A-Za-z0-9']+")

# At or below this, a question inside a conversation is taken as dependent
# whatever words it uses.
#
# The signal list above is a list of *shapes*, and questions kept arriving
# in shapes nobody had thought of — "total how many?", "same for annual?",
# "for annual leave?" carry no pronoun, open with no interrogative, and are
# plainly about the turn before them. Each one was searched as written and
# reported the library empty.
#
# Length is the property they share. Four words cannot describe a subject,
# a scope and a question at once, so in a conversation they are leaning on
# what came before. Four rather than more because it covers every case seen
# without sending much else to the classifier: of a dozen genuinely
# self-contained questions only three cross it, and being sent to the
# classifier costs a model call, not a wrong answer — it replies
# "new_topic" and the question is searched as written anyway.
MAX_SELF_CONTAINED_WORDS = 4


def looks_self_contained(question: str) -> bool:
    """True when a question can be searched exactly as written."""

    # A library-wide question names its own scope — "which documents
    # mention probation" is complete on its own, even though it opens
    # with a bare interrogative.
    if is_aggregation_question(question):
        return True

    if len(_WORDS.findall(question or "")) <= MAX_SELF_CONTAINED_WORDS:
        return False

    return not any(pattern.search(question or "") for pattern in _DEPENDENT)


def render_history(turns: list[dict], max_turns: int) -> str:
    """The recent turns, as the classifier sees them.

    Answers are clipped: the classifier needs to know what the conversation
    was *about*, not to re-read it. Documents are listed because a
    follow-up usually stays within them.
    """

    lines = []

    for turn in turns[-max_turns:]:

        lines.append(f"Q: {turn['question']}")

        answer = " ".join((turn.get("answer") or "").split())

        if len(answer) > 240:
            answer = answer[:240].rstrip() + "…"

        lines.append(f"A: {answer or '(no answer)'}")

        documents = turn.get("documents") or []

        if documents:
            lines.append(f"Documents used: {', '.join(documents)}")

        lines.append("")

    return "\n".join(lines).strip()


def _parse(content: str) -> dict | None:
    """Pull the JSON object out of a reply that may be wrapped in prose."""

    if not isinstance(content, str):
        content = str(content)

    content = content.strip()

    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)

    start = content.find("{")
    end = content.rfind("}")

    if start == -1 or end <= start:
        return None

    try:
        parsed = json.loads(content[start : end + 1])

    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


async def resolve(
    question: str,
    turns: list[dict],
) -> Resolution:
    """Decide how a question relates to the conversation before it.

    `turns` is oldest-first, each `{question, answer, documents}`.
    """

    if not turns:
        return first_turn(question)

    if looks_self_contained(question):
        # Nothing in the wording depends on context. Treating it as a new
        # topic costs nothing if it happened to be related — retrieval on
        # a complete question finds the same material anyway.
        return Resolution(
            relation=NEW_TOPIC,
            strategy=FRESH,
            search_question=question,
            reason="Question stands on its own.",
            method="rules",
        )

    max_turns = get_int("conversation.history_turns")

    try:
        chain = get_prompt("follow_up_resolution") | get_chat_model()

        response = await chain.ainvoke(
            {
                "history": render_history(turns, max_turns),
                "question": question,
            }
        )

        parsed = _parse(response.content)

        if parsed is None:
            raise ValueError("classifier returned no JSON object")

        relation = str(parsed.get("relation", "")).strip().lower()

        if relation not in (NEW_TOPIC, FOLLOW_UP):
            raise ValueError(f"unknown relation {relation!r}")

        if relation == NEW_TOPIC:
            return Resolution(
                relation=NEW_TOPIC,
                strategy=FRESH,
                search_question=question,
                reason=str(parsed.get("reason", "")).strip()
                or "Unrelated to the previous turns.",
                method="model",
            )

        rewritten = str(parsed.get("standalone_question", "")).strip()

        # A rewrite that dropped everything is worse than no rewrite.
        if len(rewritten) < 3:
            rewritten = question

        strategy = str(parsed.get("strategy", "")).strip().lower()

        if strategy not in (COMBINE, REUSE):
            strategy = COMBINE

        return Resolution(
            relation=FOLLOW_UP,
            strategy=strategy,
            search_question=rewritten,
            standalone_question=rewritten,
            reason=str(parsed.get("reason", "")).strip()
            or "Continues the previous question.",
            method="model",
        )

    except Exception as exc:
        # A classifier that cannot run must not block an answer, and must
        # not guess that context applies. Falling back to a fresh search on
        # the question as written is the safe direction: at worst the user
        # gets a thinner answer, never one built on the wrong document.
        logger.warning("Follow-up resolution failed: %s", exc)

        return Resolution(
            relation=NEW_TOPIC,
            strategy=FRESH,
            search_question=question,
            reason=f"Classifier unavailable ({exc}); searched as written.",
            method="fallback",
        )


def merge_context(
    fresh_chunks: list[RetrievedChunk],
    previous_chunks: list[RetrievedChunk],
    carry_over: int | None = None,
) -> list[RetrievedChunk]:
    """Newly retrieved chunks, plus a few carried from the previous turn.

    Fresh chunks lead: the follow-up was rewritten to be searchable, so
    what it retrieves is the better evidence. Prior chunks fill in what the
    rewrite could not recover — the specifics the user is still talking
    about, and web results no amount of re-retrieval will bring back.

    `carry_over` caps how many are kept, so they cannot outweigh the new
    material. `None` means the caller has already capped them.
    """

    seen = {chunk.chunk_id for chunk in fresh_chunks}

    carried = [
        chunk
        for chunk in previous_chunks
        if chunk.chunk_id not in seen
    ]

    if carry_over is not None:
        carried = carried[:carry_over]

    merged = [*fresh_chunks, *carried]

    for position, chunk in enumerate(merged, start=1):
        chunk.number = position

    return merged
