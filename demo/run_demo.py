#!/usr/bin/env python
"""Run the PORT-6 demo end to end against a running API.

    uv run python demo/run_demo.py            # upload, wait, run every scenario
    uv run python demo/run_demo.py --skip-upload
    uv run python demo/run_demo.py --only versioning
    uv run python demo/run_demo.py --reset    # delete demo docs and stop

Needs the API running:

    uv run uvicorn port6.main:app --reload
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests


API_URL = "http://localhost:8000"

DOCUMENTS = Path(__file__).parent / "documents"

# The API accepts at most 5 files per request, so uploads go in batches.
UPLOAD_BATCH = 5

MIME_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
}


BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
OFF = "\033[0m"


SCENARIOS = [
    {
        "key": "keyword",
        "title": "Exact term / code lookup",
        "question": "What is control SEC-4412?",
        "modes": ["naive", "hybrid", "agentic"],
        "expect": "Password reuse blocking, from the security policy",
        "watch": (
            "An exact code is what BM25 is for. Embeddings alone tend to "
            "blur rare identifiers into nearby text."
        ),
    },
    {
        "key": "sections",
        "title": "Hierarchical narrowing",
        "question": "How much annual leave do employees get?",
        "modes": ["naive", "hybrid"],
        "expect": "22 days, cited to Section 1.1 Annual Leave",
        "watch": (
            "Hybrid narrows document -> section -> chunk, so the citation "
            "points at the exact section rather than the document."
        ),
    },
    {
        "key": "pages",
        "title": "Page-level citation",
        "question": "What is the grievance procedure?",
        "modes": ["hybrid"],
        "expect": "Informal first, then written; acknowledged in 5 days",
        "watch": (
            "The handbook is a PDF, so the citation should carry a page "
            "number."
        ),
    },
    {
        "key": "crossdoc",
        "title": "Answer spread across documents",
        "question": "What are the rules for working away from the office?",
        "modes": ["naive", "hybrid", "agentic"],
        "expect": "Remote work from the handbook, travel from the policies",
        "watch": "Relevant text sits in three different documents.",
    },
    {
        "key": "tools",
        "title": "Agent tool selection",
        "question": "Which documents are in the library?",
        "modes": ["agentic"],
        "expect": "A list of the documents",
        "watch": (
            "The agent should pick document_lookup rather than running a "
            "similarity search."
        ),
    },
    {
        "key": "unanswerable",
        "title": "Refusing to guess",
        "question": "What is the company policy on pet insurance?",
        "modes": ["naive", "agentic"],
        "expect": "An honest 'not found', with no citations",
        "watch": (
            "Agentic should retry once, fail validation, then decline "
            "rather than invent an answer."
        ),
    },
]


def fail(message: str) -> None:
    print(f"{RED}{message}{OFF}")
    sys.exit(1)


def check_api() -> None:
    try:
        requests.get(f"{API_URL}/openapi.json", timeout=5).raise_for_status()

    except Exception:
        fail(
            f"No API at {API_URL}\n"
            "Start it with:  uv run uvicorn port6.main:app --reload"
        )


def list_documents() -> list[dict]:
    response = requests.get(f"{API_URL}/documents", timeout=30)
    response.raise_for_status()
    return response.json()


def upload() -> None:

    paths = sorted(
        path
        for path in DOCUMENTS.iterdir()
        if path.suffix.lower() in MIME_TYPES
    )

    if not paths:
        fail(f"No documents found in {DOCUMENTS}")

    existing = {document["filename"] for document in list_documents()}

    pending = [
        path
        for path in paths
        if path.name not in existing
    ]

    if not pending:
        print(f"{DIM}All {len(paths)} demo documents already uploaded.{OFF}")
        return

    print(f"{BOLD}Uploading {len(pending)} document(s){OFF}")

    for start in range(0, len(pending), UPLOAD_BATCH):

        batch = pending[start : start + UPLOAD_BATCH]

        files = [
            (
                "files",
                (
                    path.name,
                    path.read_bytes(),
                    MIME_TYPES[path.suffix.lower()],
                ),
            )
            for path in batch
        ]

        response = requests.post(
            f"{API_URL}/upload",
            files=files,
            timeout=120,
        )

        if not response.ok:
            fail(f"Upload failed: {response.status_code} {response.text[:300]}")

        for document in response.json():
            print(f"  accepted  {document['filename']}")


def wait_for_ready(timeout_seconds: int = 1800) -> None:
    """Ingestion runs in the background, and a local model is not fast."""

    print(
        f"\n{BOLD}Waiting for ingestion{OFF} "
        f"{DIM}(chunking, embedding, summaries){OFF}"
    )

    deadline = time.time() + timeout_seconds
    last = ""

    while time.time() < deadline:

        documents = list_documents()

        pending = [
            document
            for document in documents
            if document["status"] in ("UPLOADED", "PROCESSING")
        ]

        line = f"  {len(documents) - len(pending)}/{len(documents)} ready"

        if line != last:
            print(line)
            last = line

        if not pending:
            break

        time.sleep(4)

    else:
        print(f"{YELLOW}  Timed out waiting for ingestion.{OFF}")

    failed = [
        document
        for document in list_documents()
        if document["status"] == "FAILED"
    ]

    for document in failed:
        print(
            f"{RED}  FAILED {document['filename']}: "
            f"{document.get('error_message')}{OFF}"
        )


def warn_about_other_documents() -> None:
    """The scenarios assume the library holds only the demo corpus.

    Anything else competes for the top-k slots and can end up cited, which
    makes the comparison harder to read. Worth saying out loud rather than
    letting the output look inexplicable.
    """

    demo_names = {
        path.name
        for path in DOCUMENTS.iterdir()
        if path.suffix.lower() in MIME_TYPES
    }

    others = [
        document["filename"]
        for document in list_documents()
        if document["filename"] not in demo_names
    ]

    if not others:
        return

    print(
        f"\n{YELLOW}Note:{OFF} the library also holds "
        f"{len(others)} non-demo document(s): {', '.join(others[:5])}"
        + ("…" if len(others) > 5 else "")
    )
    print(
        f"{DIM}  They compete for retrieval slots and may appear in "
        f"citations below.\n"
        f"  For the cleanest demo, remove them first.{OFF}"
    )


def show_library() -> None:

    documents = sorted(
        list_documents(),
        key=lambda document: document["filename"],
    )

    print(f"\n{BOLD}Document library{OFF}")
    print(f"  {'file':32} {'type':22} {'status'}")
    print(f"  {'-' * 70}")

    for document in documents:

        status = document["status"]

        colour = GREEN if status == "READY" else (
            RED if status == "FAILED" else DIM
        )

        print(
            f"  {document['filename'][:39]:40} "
            f"{colour}{status}{OFF}"
        )


def ask(question: str, mode: str, top_k: int = 5) -> dict:

    response = requests.post(
        f"{API_URL}/ask",
        json={"question": question, "mode": mode, "top_k": top_k},
        timeout=900,
    )

    response.raise_for_status()
    return response.json()


def run_scenario(scenario: dict, top_k: int) -> None:

    print(f"\n{BOLD}{'=' * 80}{OFF}")
    print(f"{BOLD}{scenario['title']}{OFF}")
    print(f"{'=' * 80}")
    print(f"Q: {CYAN}{scenario['question']}{OFF}")
    print(f"{DIM}expect: {scenario['expect']}{OFF}")
    print(f"{DIM}watch : {scenario['watch']}{OFF}")

    for mode in scenario["modes"]:

        try:
            result = ask(scenario["question"], mode, top_k)

        except Exception as exc:
            print(f"\n  {RED}{mode}: {exc}{OFF}")
            continue

        documents = sorted(
            {
                chunk.get("filename") or "?"
                for chunk in result.get("retrieved_chunks") or []
            }
        )

        print(f"\n  {BOLD}{mode.upper()}{OFF} "
              f"{DIM}({(result.get('latency_ms') or 0) / 1000:.1f}s){OFF}")

        answer = " ".join((result.get("answer") or "").split())
        marker = GREEN if result.get("answered") else YELLOW
        print(f"    {marker}{answer[:300]}{OFF}")

        print(
            f"    {DIM}drew on {len(documents)} document(s): "
            f"{', '.join(documents) or '-'}{OFF}"
        )

        tools = (result.get("metadata") or {}).get("tools_used")

        if tools:
            print(f"    tools: {tools}")

        validation = (result.get("metadata") or {}).get("validation")

        if validation:
            print(
                f"    validation: {validation.get('sufficient')} "
                f"({validation.get('reason')})"
            )

        for citation in result.get("citations") or []:

            label = citation["filename"]

            bits = [label]

            if citation.get("section_title"):
                bits.append(f"Section {citation['section_title']}")

            if citation.get("page_number") is not None:
                bits.append(f"Page {citation['page_number']}")

            print(f"    {DIM}cite: {', '.join(bits)}{OFF}")


def reset() -> None:

    names = {
        path.name
        for path in DOCUMENTS.iterdir()
        if path.suffix.lower() in MIME_TYPES
    }

    removed = 0

    for document in list_documents():

        if document["filename"] not in names:
            continue

        requests.delete(
            f"{API_URL}/documents/{document['id']}",
            timeout=60,
        )

        print(f"  deleted {document['filename']}")
        removed += 1

    print(f"\nRemoved {removed} demo document(s). Other documents untouched.")


def main() -> None:

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--only", help="run one scenario by key")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the demo documents and exit",
    )
    parser.add_argument("--list", action="store_true", help="list scenarios")

    args = parser.parse_args()

    if args.list:
        for scenario in SCENARIOS:
            print(f"  {scenario['key']:14} {scenario['title']}")
        return

    check_api()

    if args.reset:
        reset()
        return

    if not args.skip_upload:
        upload()
        wait_for_ready()

    show_library()
    warn_about_other_documents()

    scenarios = SCENARIOS

    if args.only:
        scenarios = [s for s in SCENARIOS if s["key"] == args.only]

        if not scenarios:
            fail(
                f"Unknown scenario {args.only!r}. "
                f"Options: {', '.join(s['key'] for s in SCENARIOS)}"
            )

    for scenario in scenarios:
        run_scenario(scenario, args.top_k)

    print(f"\n{BOLD}{'=' * 80}{OFF}")
    print("Open the UI to explore interactively:")
    print("  uv run streamlit run src/port6/frontend/app.py")
    print(f"{DIM}Clean up with: python demo/run_demo.py --reset{OFF}")


if __name__ == "__main__":
    main()
