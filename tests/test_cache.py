"""The answer cache: the same question, not answered twice.

Two things are worth protecting here, and they pull against each other.

The cache has to *hit* — a repeated question must not pay for retrieval and
generation again. And it has to not hit *wrongly*: the similarity tier
answers a question that was not the one asked, so the guards around it —
the threshold, the scope isolation, the visible mark on the result — are
the difference between a fast answer and a confident wrong one.

Redis is faked rather than run, so these stay unit tests: no server, and no
ordering dependency on a real database's contents.
"""

from __future__ import annotations

import fnmatch
from datetime import datetime

import pytest

from port6.services.cache import service as cache
from port6.services.rag.base import RagResult


# --- a Redis, in memory -----------------------------------------------

class FakeRedis:
    """Just the commands the cache uses.

    Deliberately small. A dependency on fakeredis would test that library's
    fidelity; this tests the cache's use of five commands, which is all it
    has.
    """

    def __init__(self, failing: bool = False):
        self.strings: dict[str, bytes] = {}
        self.hashes: dict[str, dict[str, bytes]] = {}
        self.sets: dict[str, dict[str, float]] = {}
        self.failing = failing

    def _check(self):
        if self.failing:
            raise ConnectionError("redis is down")

    async def get(self, key):
        self._check()
        return self.strings.get(key)

    async def set(self, key, value, ex=None):
        self._check()
        self.strings[key] = value

    async def hset(self, key, field, value):
        self._check()
        self.hashes.setdefault(key, {})[field] = value

    async def hmget(self, key, fields):
        self._check()
        stored = self.hashes.get(key, {})
        return [
            stored.get(
                field.decode() if isinstance(field, bytes) else field
            )
            for field in fields
        ]

    async def zadd(self, key, mapping):
        self._check()
        self.sets.setdefault(key, {}).update(mapping)

    async def zrevrange(self, key, start, stop):
        self._check()
        ordered = sorted(
            self.sets.get(key, {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )
        return [
            member.encode()
            for member, _ in ordered[start : stop + 1]
        ]

    async def delete(self, key):
        self._check()
        self.strings.pop(key, None)
        self.hashes.pop(key, None)
        self.sets.pop(key, None)

    async def scan_iter(self, match=None, count=None):
        self._check()
        keys = (
            list(self.strings)
            + list(self.hashes)
            + list(self.sets)
        )
        for key in keys:
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    """Queues calls and replays them, which is all the cache needs."""

    def __init__(self, client):
        self.client = client
        self.queued = []

    def set(self, key, value, ex=None):
        self.queued.append(("set", (key, value), {"ex": ex}))

    def hset(self, key, field, value):
        self.queued.append(("hset", (key, field, value), {}))

    def zadd(self, key, mapping):
        self.queued.append(("zadd", (key, mapping), {}))

    async def execute(self):
        for name, args, kwargs in self.queued:
            await getattr(self.client, name)(*args, **kwargs)
        self.queued.clear()


@pytest.fixture
def redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(cache, "_get_client", lambda: client)
    return client


def a_result(answer: str = "22 days of annual leave [1].") -> RagResult:
    return RagResult(
        question="How many days of annual leave?",
        answer=answer,
        answered=True,
        retrieval_method="semantic vector search (top-k)",
    )


# --- normalisation ----------------------------------------------------

class TestNormalisation:

    def test_case_and_spacing_are_not_differences(self):
        assert (
            cache.normalise("  How   MANY days? ")
            == cache.normalise("how many days?")
        )

    def test_nothing_else_is_folded_away(self):
        """Stemming here would match questions with no threshold to tune.

        Rewording is the similarity tier's job, where the decision has a
        number attached and shows up on the answer.
        """

        assert cache.normalise("leave days") != cache.normalise("leave day")


# --- the exact tier ---------------------------------------------------

class TestExactTier:

    async def test_the_same_question_comes_back(self, redis):
        scope = cache.scope_digest("semantic", 5, None)

        await cache.store("How many leave days?", scope, a_result())

        hit = await cache.lookup_exact("How many leave days?", scope)

        assert hit is not None
        assert hit.metadata["cache"]["hit"] == "exact"

    async def test_wording_differing_only_in_case_still_hits(self, redis):
        scope = cache.scope_digest("semantic", 5, None)

        await cache.store("How many leave days?", scope, a_result())

        assert await cache.lookup_exact("how many LEAVE days?", scope)

    async def test_a_different_question_does_not(self, redis):
        scope = cache.scope_digest("semantic", 5, None)

        await cache.store("How many leave days?", scope, a_result())

        assert await cache.lookup_exact("What is the notice period?", scope) is None

    async def test_a_hit_says_it_came_from_the_cache(self, redis):
        """Invisible caching is how a stale answer goes unnoticed."""

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store("How many leave days?", scope, a_result())

        hit = await cache.lookup_exact("How many leave days?", scope)

        assert hit.metadata["cache"]["hit"] == "exact"
        assert hit.metadata["cache"]["age_seconds"] >= 0

    async def test_a_hit_says_when_it_was_first_answered(self, redis):
        """A timestamp, not just an age: the UI renders it like any other."""

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store("How many leave days?", scope, a_result())

        stamp = (await cache.lookup_exact("How many leave days?", scope)) \
            .metadata["cache"]["answered_at"]

        # Parseable, and carrying a timezone — the frontend does the rest.
        assert datetime.fromisoformat(stamp).tzinfo is not None

    async def test_the_original_latency_is_kept_off_the_run(self, redis):
        """A cache hit must not claim the time it just avoided.

        The stored latency belongs to the run that produced the answer.
        Left on `latency_ms` it made a 2ms lookup report 27 seconds, so it
        lives under the cache metadata where it reads as a saving.
        """

        scope = cache.scope_digest("semantic", 5, None)

        slow = a_result()
        slow.latency_ms = 27460.0

        await cache.store("How many leave days?", scope, slow)

        hit = await cache.lookup_exact("How many leave days?", scope)

        assert hit.metadata["cache"]["original_latency_ms"] == 27460.0


# --- scope ------------------------------------------------------------

class TestScope:
    """An answer belongs to the pipeline and library slice that produced it."""

    def test_each_pipeline_is_its_own_scope(self):
        assert (
            cache.scope_digest("semantic", 5, None)
            != cache.scope_digest("agent:semantic+keyword", 5, None)
        )

    def test_each_top_k_is_its_own_scope(self):
        assert (
            cache.scope_digest("semantic", 5, None)
            != cache.scope_digest("semantic", 8, None)
        )

    def test_a_document_restriction_is_its_own_scope(self):
        assert (
            cache.scope_digest("semantic", 5, None)
            != cache.scope_digest("semantic", 5, ["doc-a"])
        )

    def test_the_same_documents_in_any_order_are_one_scope(self):
        assert (
            cache.scope_digest("semantic", 5, ["a", "b"])
            == cache.scope_digest("semantic", 5, ["b", "a"])
        )

    async def test_a_naive_answer_is_not_served_to_an_agentic_question(
        self,
        redis,
    ):
        naive = cache.scope_digest("semantic", 5, None)
        agentic = cache.scope_digest("agent:semantic", 5, None)

        await cache.store("How many leave days?", naive, a_result())

        assert await cache.lookup_exact("How many leave days?", agentic) is None


# --- the similarity tier ----------------------------------------------

class TestSimilarityTier:

    async def test_a_near_identical_question_hits(self, redis, monkeypatch):
        monkeypatch.setattr(cache, "get_float", lambda key: 0.95)
        monkeypatch.setattr(cache, "get_int", lambda key: 500)

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store(
            "How many leave days?",
            scope,
            a_result(),
            embedding=[1.0, 0.0, 0.0],
        )

        hit = await cache.lookup_similar([0.99, 0.1, 0.0], scope)

        assert hit is not None
        assert hit.metadata["cache"]["hit"] == "semantic"

    async def test_a_merely_related_question_does_not(self, redis, monkeypatch):
        """The guard that keeps sick leave from answering annual leave."""

        monkeypatch.setattr(cache, "get_float", lambda key: 0.95)
        monkeypatch.setattr(cache, "get_int", lambda key: 500)

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store(
            "How many annual leave days?",
            scope,
            a_result(),
            embedding=[1.0, 0.0, 0.0],
        )

        # 0.86 — about where sick leave actually sits against annual leave.
        assert await cache.lookup_similar([0.86, 0.51, 0.0], scope) is None

    async def test_a_hit_reports_which_question_it_answered(
        self,
        redis,
        monkeypatch,
    ):
        monkeypatch.setattr(cache, "get_float", lambda key: 0.95)
        monkeypatch.setattr(cache, "get_int", lambda key: 500)

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store(
            "How many annual leave days?",
            scope,
            a_result(),
            embedding=[1.0, 0.0, 0.0],
        )

        hit = await cache.lookup_similar([1.0, 0.0, 0.0], scope)

        assert hit.metadata["cache"]["question"] == "How many annual leave days?"
        assert hit.metadata["cache"]["similarity"] == pytest.approx(1.0, abs=1e-3)

    async def test_a_threshold_of_one_switches_the_tier_off(
        self,
        redis,
        monkeypatch,
    ):
        monkeypatch.setattr(cache, "get_float", lambda key: 1.0)
        monkeypatch.setattr(cache, "get_int", lambda key: 500)

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store(
            "How many leave days?",
            scope,
            a_result(),
            embedding=[1.0, 0.0, 0.0],
        )

        assert await cache.lookup_similar([1.0, 0.0, 0.0], scope) is None

    async def test_a_different_embedding_width_is_skipped_not_compared(
        self,
        redis,
        monkeypatch,
    ):
        """Changing the embedding model must not make the cache lie."""

        monkeypatch.setattr(cache, "get_float", lambda key: 0.95)
        monkeypatch.setattr(cache, "get_int", lambda key: 500)

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store(
            "How many leave days?",
            scope,
            a_result(),
            embedding=[1.0, 0.0, 0.0],
        )

        assert await cache.lookup_similar([1.0, 0.0, 0.0, 0.0, 0.0], scope) is None


# --- invalidation -----------------------------------------------------

class TestInvalidation:

    async def test_clearing_removes_every_entry(self, redis, monkeypatch):
        monkeypatch.setattr(cache, "get_float", lambda key: 0.95)
        monkeypatch.setattr(cache, "get_int", lambda key: 500)

        scope = cache.scope_digest("semantic", 5, None)

        await cache.store("a?", scope, a_result(), embedding=[1.0, 0.0])
        await cache.store("b?", scope, a_result(), embedding=[0.0, 1.0])

        assert await cache.clear() > 0

        assert await cache.lookup_exact("a?", scope) is None
        assert await cache.lookup_similar([1.0, 0.0], scope) is None

    async def test_clearing_leaves_other_keys_alone(self, redis):
        """SCAN over this namespace, not FLUSHDB over the whole server."""

        redis.strings["someone-elses-key"] = b"keep me"

        await cache.store("a?", cache.scope_digest("semantic", 5, None), a_result())
        await cache.clear()

        assert redis.strings.get("someone-elses-key") == b"keep me"


# --- failure ----------------------------------------------------------

class TestDegradesQuietly:
    """A cache that can fail a question is worse than no cache."""

    async def test_a_broken_redis_reads_as_a_miss(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_client", lambda: FakeRedis(failing=True))
        monkeypatch.setattr(cache, "_unavailable_logged", False)

        scope = cache.scope_digest("semantic", 5, None)

        assert await cache.lookup_exact("anything?", scope) is None

    async def test_a_broken_redis_does_not_raise_on_write(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_client", lambda: FakeRedis(failing=True))
        monkeypatch.setattr(cache, "_unavailable_logged", False)

        # No exception is the assertion.
        await cache.store(
            "anything?",
            cache.scope_digest("semantic", 5, None),
            a_result(),
        )

    async def test_no_client_at_all_reads_as_a_miss(self, monkeypatch):
        monkeypatch.setattr(cache, "_get_client", lambda: None)

        scope = cache.scope_digest("semantic", 5, None)

        assert await cache.lookup_exact("anything?", scope) is None
        await cache.store("anything?", scope, a_result())


# --- round trip -------------------------------------------------------

class TestRoundTrip:

    async def test_the_answer_survives_storage_intact(self, redis):
        scope = cache.scope_digest("semantic", 5, None)
        original = a_result("Employees receive 22 days of annual leave [1].")

        await cache.store("How many leave days?", scope, original)

        hit = await cache.lookup_exact("How many leave days?", scope)

        assert hit.answer == original.answer
        assert hit.answered == original.answered
        assert hit.retrieval_method == original.retrieval_method

    async def test_an_unreadable_entry_is_a_miss_not_a_crash(self, redis):
        scope = cache.scope_digest("semantic", 5, None)
        digest = cache.entry_digest("How many leave days?", scope)

        redis.strings[cache.ENTRY_KEY.format(digest=digest)] = b"not json"

        assert await cache.lookup_exact("How many leave days?", scope) is None
