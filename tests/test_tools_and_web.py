"""Tool definitions, and the boundary around web search.

Web search changes what an answer means: every other retriever can only
return text from an uploaded file. These check that the separation is
enforced rather than described.
"""

import pytest

from port6.services.rag import tools as tool_registry
from port6.services.web import search as web


# --- tool definitions -------------------------------------------------

def test_every_tool_describes_itself_from_its_docstring():
    """The description lives beside the code, not in a distant registry."""

    for name, tool_fn in tool_registry.TOOLS.items():
        assert tool_fn.description, f"{name} has no description"
        assert len(tool_fn.description) > 30, f"{name}'s description is thin"


def test_every_tool_accepts_the_arguments_the_agent_passes():
    for name, tool_fn in tool_registry.TOOLS.items():
        assert set(tool_fn.args) >= {"query", "top_k", "document_ids"}, name


def test_the_catalogue_lists_only_offered_tools():
    catalogue = tool_registry.tool_catalogue()

    for name in tool_registry.available_tools():
        assert f"- {name}:" in catalogue

    withheld = set(tool_registry.TOOLS) - set(tool_registry.available_tools())

    for name in withheld:
        assert f"- {name}:" not in catalogue


def test_execution_can_still_resolve_a_withheld_tool():
    """A plan made a moment ago must not break if a tool is switched off."""

    assert set(tool_registry.TOOLS) >= set(tool_registry.available_tools())
    assert "web_search" in tool_registry.TOOLS


# --- the web boundary -------------------------------------------------

def test_web_search_is_not_offered_when_unavailable(monkeypatch):
    monkeypatch.setattr(web, "is_available", lambda: False)

    assert "web_search" not in tool_registry.available_tools()


def test_web_search_is_not_offered_when_switched_off(monkeypatch):
    """Off by default: reaching outside the library is an explicit choice."""

    monkeypatch.setattr(web, "is_available", lambda: True)
    monkeypatch.setattr(
        tool_registry,
        "get_setting",
        lambda key: False if key == "web.enabled" else True,
    )

    assert "web_search" not in tool_registry.available_tools()


async def test_a_scoped_question_never_reaches_the_web():
    """A document scope says which documents may be used. Going outside
    the library would contradict it."""

    outcome = await tool_registry.TOOLS["web_search"].ainvoke(
        {"query": "anything", "top_k": 3, "document_ids": ["some-id"]}
    )

    assert outcome["chunks"] == []
    assert "scoped" in outcome["info"]["skipped"]


async def test_web_search_returns_nothing_rather_than_raising(monkeypatch):
    """A failing web search must not sink a question the documents could
    still answer."""

    monkeypatch.setattr(web, "is_available", lambda: True)

    import sys

    # Make the import inside search() fail, standing in for no network.
    monkeypatch.setitem(sys.modules, "ddgs", None)

    assert web.search("anything") == []


# --- web results are marked as external -------------------------------

def test_a_web_result_is_identifiable_as_web():
    chunk = web.to_chunks(
        [{"title": "Leave", "href": "https://acme.com/hr", "body": "26 weeks."}]
    )[0]

    assert chunk.is_web
    assert chunk.url == "https://acme.com/hr"
    # Never a real document id, so it cannot be linked to as one.
    assert chunk.document_id == web.WEB_DOCUMENT_ID


def test_the_domain_is_used_as_the_source_name():
    assert web.domain_of("https://www.acme.com/hr/leave?x=1") == "acme.com"
    assert web.domain_of("https://docs.acme.co.uk/a") == "docs.acme.co.uk"
    assert web.domain_of("not a url") == "web"


def test_the_url_identifies_a_result_so_repeats_deduplicate():
    first = web.to_chunks([{"href": "https://a.com/x", "body": "s"}])[0]
    again = web.to_chunks([{"href": "https://a.com/x", "body": "s"}])[0]

    assert first.chunk_id == again.chunk_id


def test_the_title_is_kept_because_a_snippet_alone_is_ambiguous():
    chunk = web.to_chunks(
        [{"title": "Sick leave", "href": "https://a.com", "body": "12 days."}]
    )[0]

    assert "Sick leave" in chunk.content
    assert "12 days." in chunk.content


def test_an_empty_result_is_dropped():
    assert web.to_chunks([{"href": "https://a.com"}]) == []


def test_the_context_labels_a_web_source_as_web():
    """The model has to know a source is external to attribute it."""

    from port6.services.rag.generation import build_context

    chunks = web.to_chunks(
        [{"title": "T", "href": "https://acme.com/p", "body": "text"}]
    )

    context = build_context(chunks)

    assert "WEB: acme.com" in context
    assert "https://acme.com/p" in context


# --- the calculator as a tool ----------------------------------------

async def test_the_calculator_tool_evaluates_a_bare_expression():
    outcome = await tool_registry.TOOLS["calculate"].ainvoke(
        {"query": "22 - 8", "top_k": 5, "document_ids": None}
    )

    assert outcome["info"]["result"] == "14"
    assert "22 - 8 = 14" in outcome["chunks"][0].content


async def test_a_sentence_is_deferred_to_the_post_retrieval_pass():
    """The tool runs before retrieval, so it has no figures to work from.

    It used to ask the model for an expression here, and the model filled
    the empty sources from the worked examples in the prompt — answering
    "22 - 8" because 22 is in an example, not because it had read the
    policy.
    """

    outcome = await tool_registry.TOOLS["calculate"].ainvoke(
        {
            "query": "I have taken 8 days. How many are left?",
            "top_k": 5,
            "document_ids": None,
        }
    )

    assert outcome["chunks"] == []
    assert "deferred" in outcome["info"]


async def test_an_unsafe_expression_is_never_evaluated():
    outcome = await tool_registry.TOOLS["calculate"].ainvoke(
        {"query": "__import__(\'os\')", "top_k": 5, "document_ids": None}
    )

    assert outcome["chunks"] == []


# --- when the web is reached -----------------------------------------

def test_the_web_is_tried_only_after_the_documents_fail(monkeypatch):
    """Evidence validation cannot make this call. It is lexical, and a
    question sharing every key term with a policy that lacks the figure
    scores 100% and passes. `answered: false` is the honest trigger."""

    from langgraph.graph import END

    from port6.services.rag import agent
    from port6.services.rag.agent import route_after_answer

    # agent.py imports the function by name, so the module under test is
    # what has to be patched.
    monkeypatch.setattr(agent, "available_tools", lambda: {"web_search": None})

    # Answered from the documents: never reach outside.
    assert route_after_answer({"answered": True}) is END

    # The documents did not answer: try the web.
    assert route_after_answer({"answered": False}) == "retrieval_planner"

    # Already tried: stop, rather than loop.
    assert (
        route_after_answer({"answered": False, "web_attempted": True}) is END
    )


def test_no_web_fallback_when_the_tool_is_not_offered(monkeypatch):
    from langgraph.graph import END

    from port6.services.rag import agent
    from port6.services.rag.agent import route_after_answer

    monkeypatch.setattr(agent, "available_tools", lambda: {})

    assert route_after_answer({"answered": False}) is END


def test_the_retry_plan_leads_with_the_web_once_it_is_pending():
    from port6.services.rag.agent import rule_based_plan

    tools, reason = rule_based_plan(1, "anything", web_pending=True)

    assert tools[0] == "web_search"
    assert "web" in reason.lower()


def test_the_retry_plan_stays_local_when_the_web_is_not_pending():
    from port6.services.rag.agent import rule_based_plan

    tools, _ = rule_based_plan(1, "anything", web_pending=False)

    assert "web_search" not in tools
