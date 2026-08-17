"""Turn a provider failure into something worth showing a user.

"Processing failed" is useless when the real cause is an expired API key or
an Ollama server that is not running — those are operator problems with
obvious fixes, and they look nothing like a bad document.

Classification is by exception type name and message text rather than by
importing the provider SDKs, so this keeps working whichever provider is
installed and does not drag OpenAI's package into an Ollama-only setup.
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


# Coarse buckets. `kind` is stored on the document and drives whether a
# retry is worth offering.
PROVIDER = "provider"
PARSE = "parse"
STORAGE = "storage"
UNKNOWN = "unknown"


class ProviderError(Exception):
    """A model call failed for a reason the operator can act on."""

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        retryable: bool,
        original: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.original = original

    @property
    def message(self) -> str:
        return str(self)

    def as_dict(self) -> dict:
        return {
            "kind": PROVIDER,
            "reason": self.reason,
            "message": str(self),
            "retryable": self.retryable,
        }


# (reason, matches-any-of, message, retryable)
#
# Ordered: the first match wins, so the specific patterns come before the
# general ones.
_SIGNATURES: list[tuple[str, tuple[str, ...], str, bool]] = [
    (
        "auth",
        (
            "authenticationerror",
            "permissiondeniederror",
            "invalid_api_key",
            "incorrect api key",
            "invalid api key",
            "401",
            "unauthorized",
        ),
        "The model provider rejected the API key. It may be expired, "
        "revoked, or missing from .env.",
        # Retrying with the same key will fail identically.
        False,
    ),
    (
        "quota",
        (
            "insufficient_quota",
            "exceeded your current quota",
            "billing",
            "payment required",
            "402",
        ),
        "The model provider reports no remaining quota or a billing "
        "problem on the account.",
        False,
    ),
    (
        "rate_limit",
        (
            "ratelimiterror",
            "rate limit",
            "429",
            "too many requests",
        ),
        "The model provider is rate limiting requests. This usually "
        "clears on its own.",
        True,
    ),
    (
        "unreachable",
        (
            "apiconnectionerror",
            "connecterror",
            "connection refused",
            "failed to connect",
            "max retries exceeded",
            "name or service not known",
            "nodename nor servname",
        ),
        "The model provider could not be reached. If you are running "
        "Ollama, check that it is started and OLLAMA_BASE_URL is right.",
        True,
    ),
    (
        "model_missing",
        (
            "model not found",
            "not found, try pulling it",
            "no such model",
            "model_not_found",
        ),
        "The configured model is not available on the provider. Pull it "
        "or change the model in .env.",
        False,
    ),
    (
        "timeout",
        (
            "timeouterror",
            "timed out",
            "read timeout",
        ),
        "The model did not respond in time. A local model under load can "
        "take a while on the first call.",
        True,
    ),
    (
        "server",
        (
            "internalservererror",
            "500",
            "502",
            "503",
            "service unavailable",
        ),
        "The model provider returned a server error.",
        True,
    ),
]


def classify(error: Exception) -> ProviderError | None:
    """A ProviderError when this looks like a provider problem, else None."""

    haystack = " ".join(
        [
            type(error).__name__,
            str(error),
            # Wrapped exceptions often carry the real cause underneath.
            type(error.__cause__).__name__ if error.__cause__ else "",
            str(error.__cause__) if error.__cause__ else "",
        ]
    ).lower()

    for reason, needles, message, retryable in _SIGNATURES:

        if any(needle in haystack for needle in needles):
            return ProviderError(
                message,
                reason=reason,
                retryable=retryable,
                original=error,
            )

    return None


def describe(error: Exception) -> dict:
    """Classify any ingestion failure into a kind the UI can act on."""

    provider = classify(error)

    if provider is not None:
        return provider.as_dict()

    name = type(error).__name__.lower()
    text = str(error).lower()

    if any(
        needle in f"{name} {text}"
        for needle in ("parse", "corrupt", "unsupported", "decode", "pdfread")
    ):
        return {
            "kind": PARSE,
            "reason": "parse",
            "message": f"The file could not be read: {error}",
            "retryable": False,
        }

    if any(
        needle in f"{name} {text}"
        for needle in ("filenotfound", "permission denied", "no such file", "disk")
    ):
        return {
            "kind": STORAGE,
            "reason": "storage",
            "message": f"The stored file could not be accessed: {error}",
            "retryable": True,
        }

    return {
        "kind": UNKNOWN,
        "reason": "unknown",
        "message": str(error) or type(error).__name__,
        "retryable": True,
    }
