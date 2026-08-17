"""Thin HTTP client for the PORT-6 API.

The frontend talks to the running FastAPI service rather than importing the
services directly, so it needs no database connection of its own.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests


API_URL = os.getenv(
    "PORT6_API_URL",
    "http://localhost:8000",
).rstrip("/")


# Answering runs a local model, which can take a while on the first call.
ASK_TIMEOUT_SECONDS = float(
    os.getenv(
        "PORT6_ASK_TIMEOUT",
        "600",
    )
)

DEFAULT_TIMEOUT_SECONDS = 30.0

UPLOAD_TIMEOUT_SECONDS = 120.0


# The API validates the declared MIME type, and browsers do not always supply
# one for text formats, so fall back to the extension.
EXTENSION_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
    ".doc": "application/msword",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


class ApiError(Exception):
    """An API call that did not succeed, with a readable reason."""


def resolve_mime_type(
    filename: str,
    declared: str | None,
) -> str:

    extension = Path(filename).suffix.lower()

    # Browsers commonly report Markdown as text/plain or nothing at all.
    if extension in EXTENSION_MIME_TYPES:
        return EXTENSION_MIME_TYPES[extension]

    return declared or "application/octet-stream"


def _request(
    method: str,
    path: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    **kwargs,
):

    url = f"{API_URL}{path}"

    try:
        response = requests.request(
            method,
            url,
            timeout=timeout,
            **kwargs,
        )

    except requests.exceptions.ConnectionError as exc:
        raise ApiError(
            f"Could not reach the API at {API_URL}. "
            "Is the FastAPI service running?"
        ) from exc

    except requests.exceptions.Timeout as exc:
        raise ApiError(
            f"The API did not respond within {timeout:.0f}s."
        ) from exc

    if not response.ok:
        raise ApiError(
            _describe_error(response)
        )

    if not response.content:
        return None

    return response.json()


def _describe_error(
    response: requests.Response,
) -> str:
    """Turn a FastAPI error body into something worth showing a user."""

    try:
        payload = response.json()

    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"

    detail = payload.get("detail", payload)

    # Validation errors arrive as a list of per-field objects.
    if isinstance(detail, list):
        messages = [
            str(item.get("msg", item))
            for item in detail
        ]
        detail = "; ".join(messages)

    return f"HTTP {response.status_code}: {detail}"


def health() -> bool:
    """True when the API is reachable."""

    try:
        _request(
            "GET",
            "/openapi.json",
            timeout=5.0,
        )
        return True

    except ApiError:
        return False


def list_documents() -> list[dict]:
    return _request(
        "GET",
        "/documents",
    ) or []


def get_document_content(
    document_id: str,
) -> dict:
    return _request(
        "GET",
        f"/documents/{document_id}/content",
    )


def get_document_summary(
    document_id: str,
) -> dict:
    return _request(
        "GET",
        f"/documents/{document_id}/summary",
    )


def delete_document(
    document_id: str,
) -> dict:
    return _request(
        "DELETE",
        f"/documents/{document_id}",
    )


def upload_documents(
    files: list[tuple[str, bytes, str | None]],
) -> list[dict]:
    """Upload (filename, data, declared_mime) tuples."""

    payload = [
        (
            "files",
            (
                filename,
                data,
                resolve_mime_type(
                    filename,
                    declared,
                ),
            ),
        )
        for filename, data, declared in files
    ]

    return _request(
        "POST",
        "/upload",
        files=payload,
        timeout=UPLOAD_TIMEOUT_SECONDS,
    )


def list_modes() -> list[dict]:
    return _request(
        "GET",
        "/modes",
    ) or []


def ask(
    question: str,
    top_k: int = 5,
    mode: str = "naive",
) -> dict:
    return _request(
        "POST",
        "/ask",
        json={
            "question": question,
            "top_k": top_k,
            "mode": mode,
        },
        timeout=ASK_TIMEOUT_SECONDS,
    )


def compare(
    question: str,
    top_k: int = 5,
    modes: list[str] | None = None,
) -> dict:
    return _request(
        "POST",
        "/ask/compare",
        json={
            "question": question,
            "top_k": top_k,
            "modes": modes or ["naive", "hybrid", "agentic"],
        },
        # Three pipelines run back to back against a local model.
        timeout=ASK_TIMEOUT_SECONDS * 3,
    )


def search(
    query: str,
    top_k: int = 5,
    mode: str = "semantic",
) -> dict:
    # The API defaults to hybrid; this page reports raw distances, so it
    # asks for semantic only rather than relabelling fused ranks.
    return _request(
        "POST",
        "/search",
        json={
            "query": query,
            "top_k": top_k,
            "mode": mode,
        },
        timeout=ASK_TIMEOUT_SECONDS,
    )
