from __future__ import annotations

import re
from dataclasses import dataclass


CAPABILITIES = (
    "I answer questions about the documents you have uploaded, and cite "
    "the passage each statement comes from. Ask about a policy, a "
    "procedure or a specific term — for example \"how much annual leave "
    "do employees get?\" or \"which documents mention probation?\""
)


@dataclass(frozen=True, slots=True)
class SmallTalk:
    kind: str
    answer: str


_GREETING = SmallTalk(
    kind="greeting",
    answer="Hello. " + CAPABILITIES,
)

_THANKS = SmallTalk(
    kind="thanks",
    answer="You are welcome. Ask another question whenever you need to.",
)

_FAREWELL = SmallTalk(
    kind="farewell",
    answer=(
        "Goodbye. Your conversations stay in the history if you need "
        "them again."
    ),
)

_CAPABILITY = SmallTalk(
    kind="capability",
    answer=CAPABILITIES,
)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
#
# Defined before the phrase tables below, not after: _add_phrases() calls
# normalise() at import time, so moving this down makes the module fail to
# import with a NameError.

MAX_CHARACTERS = 40

# Keep letters, numbers and whitespace.
# Punctuation is converted to a space rather than deleted so that:
#
# "hi!!!there" -> "hi there"
#
# instead of accidentally becoming:
#
# "hithere"
#
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE = re.compile(r"\s+")


def normalise(question: str) -> str:
    """
    Normalize input for strict phrase matching.

    Examples:
        "Hello!!  there :)" -> "hello there"
        "  THANK YOU  "     -> "thank you"
        "HELLO!!!"          -> "hello"
        "hi 123"            -> "hi 123"
    """
    lowered = (question or "").lower()

    # Punctuation becomes whitespace.
    # Numbers are preserved so "hi 123" cannot become "hi".
    cleaned = _NON_ALPHANUMERIC.sub(" ", lowered)

    # Collapse repeated whitespace.
    return _WHITESPACE.sub(" ", cleaned).strip()


# ---------------------------------------------------------------------------
# Supported phrases
# ---------------------------------------------------------------------------
#
# These are intentionally exact matches after normalization.
#
# "hi"                         -> greeting
# "hello!!!"                   -> greeting
# "  HELLO  "                  -> greeting
# "hi, how much annual leave?" -> normal RAG path
# "thanks, explain leave"     -> normal RAG path
#
# Never use startswith(), contains(), fuzzy matching, or semantic matching
# here. A real document question must never be intercepted accidentally.
# ---------------------------------------------------------------------------

_PHRASES: dict[str, SmallTalk] = {}


def _add_phrases(
    response: SmallTalk,
    phrases: tuple[str, ...],
) -> None:
    """Register normalized phrases while preventing duplicate categories."""
    for phrase in phrases:
        normalized = normalise(phrase)

        if not normalized:
            raise ValueError(
                f"Cannot register an empty phrase: {phrase!r}"
            )

        existing = _PHRASES.get(normalized)

        if existing is not None:
            if existing.kind != response.kind:
                raise ValueError(
                    f"Phrase {phrase!r} is registered for both "
                    f"{existing.kind!r} and {response.kind!r}."
                )

            continue

        _PHRASES[normalized] = response


_add_phrases(
    _GREETING,
    (
        # Basic greetings
        "hi",
        "hii",
        "hiii",
        "hiiii",
        "hello",
        "helloo",
        "hellooo",
        "helo",
        "hey",
        "heyy",
        "heyyy",
        "heya",
        "heyyo",
        "hiya",
        "yo",
        "yoo",
        "howdy",
        "greetings",

        # Morning
        "morning",
        "good morning",
        "morning there",
        "good morning there",

        # Afternoon
        "afternoon",
        "good afternoon",
        "good afternoon there",

        # Evening
        "evening",
        "good evening",
        "good evening there",

        # General
        "good day",
        "hi there",
        "hello there",
        "hey there",
        "hiya there",
        "hey everyone",
        "hello everyone",
        "hi everyone",
        "hey all",
        "hello all",
        "hi all",

        # Casual greetings
        "what's up",
        "whats up",
        "what up",
        "sup",
        "wassup",
        "how is it going",
        "how's it going",
        "hows it going",
        "how are you",
        "how are you doing",
        "how have you been",
        "how's everything",
        "hows everything",
        "how is everything",
    ),
)


_add_phrases(
    _THANKS,
    (
        # Basic thanks
        "thanks",
        "thank you",
        "thx",
        "ty",
        "tq",

        # Stronger thanks
        "thanks a lot",
        "thanks so much",
        "thanks very much",
        "thank you very much",
        "thank you so much",
        "many thanks",
        "a lot of thanks",

        # Appreciation
        "much appreciated",
        "really appreciate it",
        "appreciate it",
        "i appreciate it",
        "i appreciate that",
        "really appreciate that",
        "greatly appreciated",

        # Repeated thanks
        "thanks again",
        "thank you again",
        "thanks once again",
        "thank you once again",

        # Casual
        "cheers",
        "nice",
        "awesome",
        "perfect",
        "great",
        "amazing",
        "got it",
        "understood",
        "okay thanks",
        "ok thanks",
        "okay thank you",
        "ok thank you",

        # Acknowledgement
        "gotcha",
        "got it thanks",
        "understood thanks",
        "that helps",
        "this helps",
        "that was helpful",
        "very helpful",
        "really helpful",
    ),
)


_add_phrases(
    _FAREWELL,
    (
        # Basic
        "bye",
        "goodbye",
        "good bye",
        "see you",
        "see ya",
        "cya",

        # Casual
        "later",
        "see you later",
        "see ya later",
        "catch you later",
        "talk to you later",
        "speak to you later",
        "talk later",
        "chat later",

        # Goodbye variations
        "bye for now",
        "goodbye for now",
        "see you soon",
        "see ya soon",
        "until next time",
        "till next time",
        "until later",

        # Polite
        "take care",
        "you take care",
        "have a good day",
        "have a nice day",
        "have a great day",
        "have a good one",
        "have a nice one",
        "have a great one",

        # Time-specific
        "good night",
        "goodnight",
        "night",
        "have a good night",
        "have a nice night",
        "have a great night",
    ),
)

_add_phrases(
    _CAPABILITY,
    (
        "who are you",
        "what are you",
        "what can you do",
        "what do you do",
        "help",
        "what is this",
        "how does this work",
        "what can i ask",
    ),
)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(question: str) -> SmallTalk | None:
    """
    Return a canned response for a supported conversational opener.

    Returns None for anything that should continue through the normal
    document retrieval pipeline.
    """
    if not question:
        return None

    # Cheap guard before doing normalization.
    if len(question) > MAX_CHARACTERS:
        return None

    normalised = normalise(question)

    if not normalised:
        return None

    # Use the normalized length as the actual meaningful length.
    if len(normalised) > MAX_CHARACTERS:
        return None

    # Exact full-string lookup.
    #
    # This is deliberately NOT:
    #
    #     startswith()
    #     in
    #     fuzzy matching
    #
    # so real questions always reach RAG.
    return _PHRASES.get(normalised)


def is_small_talk(question: str) -> bool:
    """Return True when the message should bypass document retrieval."""
    return classify(question) is not None