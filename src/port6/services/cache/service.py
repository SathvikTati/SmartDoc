"""Answered questions, kept so the same one is not answered twice.

An answer is expensive and deterministic-ish: retrieval plus one to four
model calls, measured at 0.9s for the naive pipeline and 2.7s for the
agentic one. Asking the same question again paid that again.

**Two tiers, in this order.**

1. Exact, after normalising case and whitespace. One Redis `GET`, and
   crucially *no embedding call* — so the cheap hit stays cheap.
2. Cosine similarity against other questions in the same scope, which
   catches a rewording. Only reached on an exact miss, because it needs the
   question embedded.

**Scope is part of the key, never part of the similarity search.** A key
covers the question, the pipeline that answered it, `top_k`, and the
document scope. Two questions only ever compete on similarity when all of
those already match, because an agentic answer is not a naive answer to
the same words, and an answer scoped to one document is not an answer from
the whole library.

**Invalidation is a flush, not arithmetic.** Anything that changes the
index clears the whole namespace. A new document can plausibly change any
answer, so versioning individual entries would be a lot of careful
bookkeeping to arrive at nearly the same set. Clearing everything cannot
be subtly wrong.

**Every failure is swallowed.** A cache that can fail a question is worse
than no cache, so an unreachable Redis logs once and gets out of the way —
the same rule tracing and history recording already follow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import struct
import threading
import time
from datetime import datetime, timezone

from port6.config import REDIS_URL
from port6.services.rag.base import RagResult
from port6.services.settings.service import get_float, get_int, get_setting


logger = logging.getLogger(__name__)


NAMESPACE = "port6:answers"

# One key per exact question, one set of members per scope. The set is what
# the similarity tier walks, and it is per scope so that walk can never
# cross a pipeline or a document restriction.
ENTRY_KEY = NAMESPACE + ":entry:{digest}"
SCOPE_KEY = NAMESPACE + ":scope:{digest}"

_WHITESPACE = re.compile(r"\s+")

_client = None
_client_lock = threading.Lock()
_unavailable_logged = False


# -------------------------------------------------------------------
# Connection
# -------------------------------------------------------------------

def _get_client():
    """The shared Redis client, or None if it cannot be had.

    Built once behind a lock, like the vector store and the settings cache.
    `redis-py` pools connections internally, so one client is what the
    whole process should share.
    """

    global _client, _unavailable_logged

    if _client is not None:
        return _client

    with _client_lock:

        if _client is not None:
            return _client

        try:
            import redis.asyncio as redis

            _client = redis.from_url(
                REDIS_URL,
                # Values hold packed floats and JSON, so they stay bytes.
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=2,
            )

        except Exception as exc:
            if not _unavailable_logged:
                logger.warning(
                    "Answer cache unavailable, answering without it: %s",
                    exc,
                )
                _unavailable_logged = True

            return None

    return _client


def _report_unavailable(exc: Exception) -> None:
    """Say it once. A cache miss per question is not worth a log line each."""

    global _unavailable_logged

    if not _unavailable_logged:
        logger.warning(
            "Answer cache unreachable, answering without it: %s",
            exc,
        )
        _unavailable_logged = True


def enabled() -> bool:
    return bool(get_setting("cache.enabled"))


# -------------------------------------------------------------------
# Keys
# -------------------------------------------------------------------

def normalise(question: str) -> str:
    """Fold away the differences that are not differences.

    Case and spacing only. Nothing is stemmed and no word is dropped: the
    similarity tier is what handles rewording, and doing it here as well
    would make one question silently stand for another with no threshold
    to tune and no similarity to show.
    """

    return _WHITESPACE.sub(" ", (question or "").strip()).lower()


def _digest(*parts) -> str:
    return hashlib.sha256(
        "\x1f".join(str(part) for part in parts).encode("utf-8")
    ).hexdigest()


def scope_digest(
    pipeline: str,
    top_k: int,
    document_ids: list[str] | None,
) -> str:
    """Everything that must match before two questions may be compared.

    Document ids are sorted, so the same scope asked for in a different
    order is the same scope.
    """

    return _digest(
        pipeline,
        top_k,
        ",".join(sorted(document_ids)) if document_ids else "*",
    )


def entry_digest(question: str, scope: str) -> str:
    return _digest(normalise(question), scope)


# -------------------------------------------------------------------
# Vectors
# -------------------------------------------------------------------

def pack(vector) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(raw: bytes):
    import numpy as np

    return np.frombuffer(raw, dtype="<f4")


def _best_match(query, vectors: dict[str, bytes]):
    """`(digest, similarity)` for the closest cached question.

    One matrix multiply rather than a loop: the candidate set is capped at
    a few hundred, so this is a fraction of a millisecond and not worth
    doing a row at a time.
    """

    import numpy as np

    digests = []
    rows = []

    for digest, raw in vectors.items():
        if not raw:
            continue

        row = unpack(raw)

        # A different embedding model produces a different width. Those
        # entries are simply not comparable, and skipping them lets the
        # cache survive a model change instead of returning nonsense.
        if row.shape[0] != len(query):
            continue

        digests.append(digest)
        rows.append(row)

    if not rows:
        return None, 0.0

    matrix = np.vstack(rows).astype("float32")
    target = np.asarray(query, dtype="float32")

    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(target)
    norms[norms == 0] = 1.0

    scores = (matrix @ target) / norms

    best = int(np.argmax(scores))

    return digests[best], float(scores[best])


# -------------------------------------------------------------------
# Reading
# -------------------------------------------------------------------

def _revive(raw: bytes, hit: str, similarity: float | None) -> RagResult | None:
    """Rebuild a stored result, and mark it as having come from the cache.

    The mark is not decoration. A similarity hit answered a question that
    was not quite the one asked, and the reader is owed that fact — so it
    reaches the UI and the trace rather than being invisible.
    """

    try:
        payload = json.loads(raw)
        result = RagResult(**payload["result"])

    except Exception as exc:
        logger.warning("Discarding an unreadable cache entry: %s", exc)
        return None

    result.metadata = dict(result.metadata or {})
    result.metadata["cache"] = {
        "hit": hit,
        "similarity": round(similarity, 4) if similarity is not None else None,
        "answered_at": payload.get("answered_at"),
        "age_seconds": max(int(time.time() - payload.get("stored_at", 0)), 0),
        # What the answer cost the first time. Kept because it is the
        # interesting number — it is what the cache saved — but kept
        # *here*, not left on `latency_ms` where it would claim this run
        # took 27 seconds when it took ten milliseconds.
        "original_latency_ms": result.latency_ms,
        "question": payload.get("question"),
    }

    return result


async def lookup_exact(
    question: str,
    scope: str,
) -> RagResult | None:
    """The stored answer to this exact question, if there is one."""

    client = _get_client()

    if client is None:
        return None

    digest = entry_digest(question, scope)

    try:
        raw = await client.get(ENTRY_KEY.format(digest=digest))

    except Exception as exc:
        _report_unavailable(exc)
        return None

    if not raw:
        return None

    return _revive(raw, hit="exact", similarity=1.0)


async def lookup_similar(
    embedding,
    scope: str,
) -> RagResult | None:
    """The stored answer to the closest question in this scope, if close enough."""

    client = _get_client()

    if client is None:
        return None

    threshold = get_float("cache.similarity_threshold")

    # A threshold of 1 means "exact wording only", which the tier above has
    # already settled. Skipping saves the whole comparison.
    if threshold >= 1.0:
        return None

    scope_key = SCOPE_KEY.format(digest=scope)

    try:
        members = await client.zrevrange(
            scope_key,
            0,
            get_int("cache.max_candidates") - 1,
        )

        if not members:
            return None

        vectors = await client.hmget(
            NAMESPACE + ":vectors",
            members,
        )

    except Exception as exc:
        _report_unavailable(exc)
        return None

    by_digest = {
        member.decode(): raw
        for member, raw in zip(members, vectors)
        if raw
    }

    if not by_digest:
        return None

    digest, similarity = _best_match(embedding, by_digest)

    if digest is None or similarity < threshold:
        return None

    try:
        raw = await client.get(ENTRY_KEY.format(digest=digest))

    except Exception as exc:
        _report_unavailable(exc)
        return None

    if not raw:
        return None

    return _revive(raw, hit="semantic", similarity=similarity)


# -------------------------------------------------------------------
# Writing
# -------------------------------------------------------------------

async def store(
    question: str,
    scope: str,
    result: RagResult,
    embedding=None,
    ttl_seconds: int | None = None,
) -> None:
    """Keep this answer. Best-effort, and never raises."""

    client = _get_client()

    if client is None:
        return

    digest = entry_digest(question, scope)
    ttl = ttl_seconds or get_int("cache.ttl_seconds")

    payload = json.dumps(
        {
            "question": question,
            # Both: the epoch for arithmetic, the ISO string because the UI
            # renders it with the same relative-time helper the history
            # list uses. A raw age in seconds read as machine output.
            "stored_at": int(time.time()),
            "answered_at": datetime.now(timezone.utc).isoformat(),
            "result": result.model_dump(mode="json"),
        }
    ).encode("utf-8")

    try:
        pipe = client.pipeline()
        pipe.set(ENTRY_KEY.format(digest=digest), payload, ex=ttl)

        if embedding is not None:
            # Scored by insertion time so the candidate cap keeps the most
            # recent questions rather than an arbitrary few.
            pipe.hset(NAMESPACE + ":vectors", digest, pack(embedding))
            pipe.zadd(SCOPE_KEY.format(digest=scope), {digest: time.time()})

        await pipe.execute()

    except Exception as exc:
        _report_unavailable(exc)


# -------------------------------------------------------------------
# Invalidation
# -------------------------------------------------------------------

async def clear() -> int:
    """Drop every cached answer. Returns how many keys went.

    Called whenever the index changes. Scoped to this namespace with SCAN
    rather than FLUSHDB, so nothing else sharing the Redis is touched.
    """

    client = _get_client()

    if client is None:
        return 0

    removed = 0

    try:
        async for key in client.scan_iter(match=NAMESPACE + ":*", count=500):
            await client.delete(key)
            removed += 1

    except Exception as exc:
        _report_unavailable(exc)
        return removed

    if removed:
        logger.info("Cleared %d answer cache keys", removed)

    return removed


def clear_soon() -> None:
    """Clear the cache from synchronous code.

    Ingestion and deletion are sync — they run in a worker thread — so they
    cannot await. This schedules the clear on the running loop when there
    is one, and otherwise runs it to completion itself.
    """

    import asyncio

    try:
        loop = asyncio.get_running_loop()

    except RuntimeError:
        try:
            asyncio.run(clear())

        except Exception as exc:
            logger.warning("Could not clear the answer cache: %s", exc)

        return

    loop.create_task(clear())


def reset() -> None:
    """Forget the client, so the next call rebuilds it. For tests."""

    global _client, _unavailable_logged

    _client = None
    _unavailable_logged = False
