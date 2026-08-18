"""Provider-failure classification and the prompt-edit guard.

Both exist to keep an operator problem from looking like a content problem:
one turns "processing failed" into "your API key expired", the other stops
an edited prompt from silently dropping the sources it is meant to cite.
"""

import pytest

from port6.services.llm.errors import PARSE, PROVIDER, UNKNOWN, classify, describe
from port6.services.settings.defaults import PROMPT_DEFAULTS
from port6.services.settings.service import InvalidPrompt, _check_variables


# Named to match what the provider SDKs actually raise; classification is
# by type name and message, so these stand in without importing them.
class AuthenticationError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class RateLimitError(Exception):
    pass


@pytest.mark.parametrize(
    "error, reason, retryable",
    [
        (
            AuthenticationError("Error code: 401 - Incorrect API key provided"),
            "auth",
            False,
        ),
        (
            Exception("insufficient_quota: You exceeded your current quota"),
            "quota",
            False,
        ),
        (
            APIConnectionError("Connection refused to http://localhost:11434"),
            "unreachable",
            True,
        ),
        (RateLimitError("429 Too Many Requests"), "rate_limit", True),
        (
            Exception('model "qwen9" not found, try pulling it first'),
            "model_missing",
            False,
        ),
        (TimeoutError("Read timed out"), "timeout", True),
    ],
)
def test_provider_failures_are_named_and_scored_for_retry(
    error,
    reason,
    retryable,
):
    classified = classify(error)

    assert classified is not None
    assert classified.reason == reason
    assert classified.retryable is retryable
    assert classified.as_dict()["kind"] == PROVIDER
    # The message is for a human, so it must say something.
    assert len(classified.message) > 20


def test_an_expired_key_is_not_offered_as_retryable():
    """Retrying with the same dead key just fails again."""

    assert classify(AuthenticationError("401 unauthorized")).retryable is False


def test_a_wrapped_cause_is_still_recognised():
    outer = RuntimeError("Summarisation failed")
    outer.__cause__ = APIConnectionError("connection refused")

    assert classify(outer).reason == "unreachable"


def test_an_ordinary_error_is_not_blamed_on_the_provider():
    assert classify(ValueError("Document has no content to chunk")) is None


def test_describe_buckets_non_provider_failures():
    assert describe(ValueError("could not parse the PDF"))["kind"] == PARSE
    assert describe(ValueError("something odd"))["kind"] == UNKNOWN


# --- prompt guard -----------------------------------------------------

def test_shipped_prompts_declare_the_variables_they_use():
    for name, spec in PROMPT_DEFAULTS.items():
        _check_variables(name, spec["template"])


def test_an_edit_that_drops_the_sources_is_rejected():
    """Without {context} the model would be asked to cite nothing."""

    with pytest.raises(InvalidPrompt) as caught:
        _check_variables(
            "answer_generation",
            "Just answer the question.\n\n{query}",
        )

    assert "{context}" in str(caught.value)


def test_an_edit_that_drops_the_question_is_rejected():
    with pytest.raises(InvalidPrompt):
        _check_variables(
            "answer_generation",
            "Answer from these sources: {context}\n\nGo.",
        )


def test_an_unbalanced_brace_is_rejected_before_it_reaches_a_request():
    with pytest.raises(InvalidPrompt):
        _check_variables(
            "answer_generation",
            "{context} and a stray {\n\n{query}",
        )


def test_a_valid_rewording_is_accepted():
    _check_variables(
        "answer_generation",
        "Use only these sources:\n\n{context}\n\nBe brief.\n\n{query}",
    )
