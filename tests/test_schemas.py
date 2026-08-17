"""Response serialisation.

The timestamp case is a regression test: timestamps are stored naive but
are always UTC, and serialising them without a zone made `new Date(...)`
in a browser read them as *local* time. A file uploaded moments earlier
showed as "5h ago" for anyone east of UTC.
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from port6.services.schemas.admin import QueryRunSummary
from port6.services.schemas.common import to_utc_iso
from port6.services.schemas.document import DocumentResponse


def a_document(**overrides):
    fields = {
        "id": uuid4(),
        "filename": "hr_policy.md",
        "file_type": "text/markdown",
        "size_bytes": 688,
        "sha256": "a" * 64,
        "content_sha256": "b" * 64,
        "storage_path": "uploads/x.md",
        "status": "READY",
        "created_at": datetime(2026, 8, 17, 7, 55, 44),
    }
    fields.update(overrides)
    return DocumentResponse(**fields)


def test_a_naive_timestamp_is_serialised_as_utc():
    payload = json.loads(a_document().model_dump_json())

    assert payload["created_at"] == "2026-08-17T07:55:44+00:00"


def test_an_already_aware_timestamp_keeps_its_instant():
    aware = datetime(2026, 8, 17, 13, 25, 44, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    payload = json.loads(a_document(created_at=aware).model_dump_json())

    # Same moment, expressed in UTC.
    assert payload["created_at"] == "2026-08-17T07:55:44+00:00"


def test_a_browser_reading_the_value_gets_the_right_age():
    """The actual symptom: a fresh upload must not look hours old."""

    just_now = datetime.utcnow()

    payload = json.loads(a_document(created_at=just_now).model_dump_json())
    parsed = datetime.fromisoformat(payload["created_at"])

    age = datetime.now(timezone.utc) - parsed

    assert abs(age.total_seconds()) < 5


def test_a_missing_timestamp_stays_null():
    payload = json.loads(a_document(last_attempt_at=None).model_dump_json())

    assert payload["last_attempt_at"] is None


def test_query_runs_are_stamped_too():
    run = QueryRunSummary(
        id=uuid4(),
        question="How much annual leave?",
        mode="hybrid",
        top_k=5,
        answered=True,
        citation_count=1,
        chunk_count=5,
        latency_ms=812.0,
        retrieval_method="hybrid",
        created_at=datetime(2026, 8, 17, 7, 55, 44),
    )

    payload = json.loads(run.model_dump_json())

    assert payload["created_at"].endswith("+00:00")


def test_to_utc_iso_handles_none():
    assert to_utc_iso(None) is None
