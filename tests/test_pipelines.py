"""Compositions: which retrievers run, and whether an agent sits on them."""

import pytest

from port6.services.rag import pipelines
from port6.services.rag.base import RagMode, RetrievedChunk
from port6.services.rag.pipelines import (
    HIERARCHICAL,
    KEYWORD,
    MODE_DEFAULTS,
    PRESETS,
    RETRIEVERS,
    SEMANTIC,
    Composition,
    InvalidComposition,
    list_options,
    rerank,
    resolve,
)


# --- what a composition is --------------------------------------------

class TestComposition:

    def test_the_three_retrievers_combine_freely(self):
        for combination in [
            (SEMANTIC,),
            (KEYWORD,),
            (HIERARCHICAL,),
            (SEMANTIC, KEYWORD),
            (KEYWORD, HIERARCHICAL),
            (SEMANTIC, KEYWORD, HIERARCHICAL),
        ]:
            assert Composition(retrievers=combination).ordered == tuple(
                name
                for name in (SEMANTIC, KEYWORD, HIERARCHICAL)
                if name in combination
            )

    def test_order_does_not_change_identity(self):
        """Two ways of describing the same composition are the same one."""

        one = Composition(retrievers=(KEYWORD, SEMANTIC))
        other = Composition(retrievers=(SEMANTIC, KEYWORD))

        assert one.id == other.id
        assert one.label == other.label

    def test_no_retrievers_is_rejected(self):
        with pytest.raises(InvalidComposition):
            Composition(retrievers=())

    def test_an_unknown_retriever_is_rejected(self):
        with pytest.raises(InvalidComposition):
            Composition(retrievers=("telepathy",))

    def test_an_unknown_tool_is_rejected(self):
        with pytest.raises(InvalidComposition):
            Composition(retrievers=(SEMANTIC,), extra_tools=("nope",))

    def test_a_retrieval_tool_cannot_be_passed_as_an_extra(self):
        """Retrieval tools come from the retrievers, not from the list."""

        with pytest.raises(InvalidComposition):
            Composition(retrievers=(SEMANTIC,), extra_tools=("keyword_search",))

    def test_it_is_immutable(self):
        with pytest.raises(Exception):
            Composition(retrievers=(SEMANTIC,)).agent = True


class TestFamily:
    """The coarse mode a composition counts as, for history and /modes."""

    def test_one_retriever_is_naive(self):
        assert Composition(retrievers=(SEMANTIC,)).family is RagMode.NAIVE

    def test_several_is_hybrid(self):
        assert (
            Composition(retrievers=(SEMANTIC, KEYWORD)).family is RagMode.HYBRID
        )

    def test_the_agent_makes_it_agentic_whatever_it_retrieves_with(self):
        assert (
            Composition(retrievers=(SEMANTIC,), agent=True).family
            is RagMode.AGENTIC
        )


class TestIdentity:

    def test_the_slug_describes_the_composition(self):
        assert Composition(retrievers=(SEMANTIC, KEYWORD)).id == (
            "semantic+keyword"
        )

    def test_the_agent_is_visible_in_the_slug(self):
        assert Composition(retrievers=(KEYWORD,), agent=True).id == (
            "agent:keyword"
        )

    def test_so_are_the_tools_it_was_given(self):
        composition = Composition(
            retrievers=(KEYWORD,),
            agent=True,
            extra_tools=("calculate",),
        )

        assert composition.id == "agent[calculate]:keyword"

    def test_direct_is_distinguishable_from_planned(self):
        planned = Composition(retrievers=(KEYWORD,), agent=True)
        direct = Composition(retrievers=(KEYWORD,), agent=True, planner=False)

        assert planned.id != direct.id


# --- the agent may only reach what it was given -----------------------

class TestAllowedTools:
    """Turning the agent on must not widen what is searched.

    Otherwise a with-agent against without-agent comparison varies two
    things at once and says nothing about either.
    """

    def test_each_retriever_unlocks_its_own_tool(self):
        tools = Composition(retrievers=(KEYWORD,), agent=True).allowed_tools

        assert "keyword_search" in tools
        assert "semantic_search" not in tools
        assert "hierarchical_search" not in tools

    def test_the_fused_tool_needs_both_halves(self):
        one = Composition(retrievers=(SEMANTIC,), agent=True)
        both = Composition(retrievers=(SEMANTIC, KEYWORD), agent=True)

        assert "hybrid_search" not in one.allowed_tools
        assert "hybrid_search" in both.allowed_tools

    def test_coverage_is_always_available(self):
        """Any composition has to be able to answer a library-wide question."""

        for combination in [(SEMANTIC,), (KEYWORD,), (HIERARCHICAL,)]:
            composition = Composition(retrievers=combination, agent=True)

            assert "aggregate_search" in composition.allowed_tools

    def test_extras_have_to_be_asked_for(self):
        without = Composition(retrievers=(SEMANTIC,), agent=True)
        with_calc = Composition(
            retrievers=(SEMANTIC,),
            agent=True,
            extra_tools=("calculate",),
        )

        assert "calculate" not in without.allowed_tools
        assert "calculate" in with_calc.allowed_tools

    def test_selecting_web_search_does_not_switch_the_web_on(
        self,
        monkeypatch,
    ):
        """The composition asks; the setting decides.

        Stated rather than assumed: reading the live `web.enabled` would
        make this pass or fail on whatever the database happens to hold.
        """

        from port6.services.rag import tools as tool_registry

        monkeypatch.setattr(
            tool_registry,
            "get_setting",
            lambda key: False,
        )

        composition = Composition(
            retrievers=(SEMANTIC,),
            agent=True,
            extra_tools=("web_search",),
        )

        assert "web_search" in composition.allowed_tools

        assert "web_search" not in tool_registry.available_tools(
            composition.allowed_tools
        )


# --- shortcuts, not special cases -------------------------------------

class TestPresets:

    def test_every_preset_is_a_valid_composition(self):
        for name, preset in PRESETS.items():
            assert isinstance(preset, Composition), name
            assert preset.ordered

    def test_a_preset_is_reachable_by_hand(self):
        """Nothing a preset does is unavailable to a built composition."""

        hybrid = PRESETS["hybrid"]

        rebuilt = Composition(
            retrievers=hybrid.retrievers,
            agent=hybrid.agent,
            planner=hybrid.planner,
            extra_tools=hybrid.extra_tools,
        )

        assert rebuilt.id == hybrid.id

    def test_only_the_agentic_preset_carries_the_agent(self):
        assert PRESETS["agentic"].agent
        assert not PRESETS["semantic"].agent
        assert not PRESETS["keyword"].agent
        assert not PRESETS["hybrid"].agent


class TestModeCompatibility:
    """`mode` predates compositions and has to keep meaning what it did."""

    def test_every_mode_maps_to_a_composition(self):
        for mode in RagMode:
            assert isinstance(MODE_DEFAULTS[mode], Composition)

    def test_a_mode_maps_to_its_own_family(self):
        for mode, composition in MODE_DEFAULTS.items():
            assert composition.family is mode

    def test_naive_still_means_semantic_only(self):
        assert MODE_DEFAULTS[RagMode.NAIVE].ordered == (SEMANTIC,)

    def test_hybrid_still_means_all_three(self):
        assert set(MODE_DEFAULTS[RagMode.HYBRID].ordered) == {
            SEMANTIC,
            KEYWORD,
            HIERARCHICAL,
        }

    def test_agentic_still_carries_the_agent(self):
        assert MODE_DEFAULTS[RagMode.AGENTIC].agent


# --- choosing one -----------------------------------------------------

class TestResolve:

    def test_an_explicit_composition_wins(self):
        chosen = resolve(retrievers=[KEYWORD], agent=True, mode="naive")

        assert chosen.ordered == (KEYWORD,)
        assert chosen.agent

    def test_a_bare_mode_maps_to_its_composition(self):
        assert resolve(mode="naive").ordered == (SEMANTIC,)
        assert resolve(mode=RagMode.AGENTIC).agent

    def test_neither_falls_back_to_the_configured_default(self, monkeypatch):
        monkeypatch.setattr(pipelines, "get_setting", lambda key: "naive")

        assert resolve().ordered == (SEMANTIC,)

    def test_a_stale_setting_does_not_break_asking(self, monkeypatch):
        monkeypatch.setattr(pipelines, "get_setting", lambda key: "nonsense")

        assert pipelines.default_mode() == "hybrid"
        assert resolve().family is RagMode.HYBRID

    def test_an_empty_retriever_list_falls_through_rather_than_failing(self):
        """[] is "not specified", not "search with nothing"."""

        assert resolve(retrievers=[], mode="naive").ordered == (SEMANTIC,)


# --- what the builder is offered --------------------------------------

class TestOptions:

    def test_it_offers_every_retriever(self):
        options = list_options()

        assert {one["id"] for one in options["retrievers"]} == set(RETRIEVERS)

    def test_it_marks_a_tool_the_server_has_switched_off(self, monkeypatch):
        """The builder should grey a tool out rather than offer a control
        that silently does nothing."""

        from port6.services.rag import tools as tool_registry

        monkeypatch.setattr(tool_registry, "get_setting", lambda key: False)

        options = list_options()

        web = next(one for one in options["tools"] if one["id"] == "web_search")

        assert web["enabled"] is False

    def test_it_carries_the_presets_and_the_default_mode(self):
        options = list_options()

        assert {one["name"] for one in options["presets"]} == set(PRESETS)
        assert options["default_mode"] in {mode.value for mode in RagMode}


# --- ranking ----------------------------------------------------------

def chunk(chunk_id, *, fused=None, sources=(), score=None):
    return RetrievedChunk(
        number=0,
        chunk_id=chunk_id,
        document_id="d",
        filename="f.md",
        content="text",
        fused_score=fused,
        sources=list(sources),
        score=score,
    )


class TestRerank:

    def test_agreement_breaks_a_tie_on_fused_score(self):
        one = chunk("a", fused=0.03, sources=["semantic"])
        both = chunk("b", fused=0.03, sources=["semantic", "keyword"])

        assert [c.chunk_id for c in rerank([one, both], 2)] == ["b", "a"]

    def test_it_renumbers_from_one(self):
        ordered = rerank([chunk("a", fused=0.01), chunk("b", fused=0.02)], 2)

        assert [c.number for c in ordered] == [1, 2]

    def test_it_trims_to_top_k(self):
        assert len(rerank([chunk(str(i), fused=i / 10) for i in range(9)], 3)) == 3
