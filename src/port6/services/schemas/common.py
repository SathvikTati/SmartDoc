"""Shared field types for API responses."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer


def to_utc_iso(value: datetime | None) -> str | None:
    """Serialise a timestamp with an explicit UTC offset.

    Timestamps are stored naive but are always UTC (`datetime.utcnow`).
    Serialised as-is they came out as "2026-08-17T07:55:44" with no zone,
    and `new Date(...)` in a browser reads a bare string like that as
    *local* time — so a file uploaded moments ago showed as "5h ago" for
    anyone east of UTC.

    Stamping the zone on the way out makes the value unambiguous without
    migrating the column or touching stored data.
    """

    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).isoformat()


UtcDatetime = Annotated[
    datetime,
    PlainSerializer(to_utc_iso, return_type=str, when_used="json"),
]
