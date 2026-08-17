"""Fusion, citation handling and evidence scoring.

These are the pure functions the three modes share, so a mistake here is a
mistake in every mode at once.
"""

from port6.services.rag.base import RetrievedChunk, chunk_from_metadata
from port6.services.rag.generation import (
    build_context,
    extract_cited_numbers,
    is_degenerate,
    number_chunks,
)
from port6.services.rag.retrievers import (
    combine_where,
    fuse,
    tokenize,
    where_for_documents,
)
from port6.services.rag.validation import keyword_overlap


def chunk(chunk_id, content="text", score=None, **kwargs):
    return RetrievedChunk(
        number=1,
        chunk_id=chunk_id,
        document_id="doc",
        filename="hr_policy.md",
        content=content,
        score=score,
        **kwargs,
    )


# --- tokenizing -------------------------------------------------------

def test_tokenize_keeps_digits_and_short_tokens():
    """Enterprise queries turn on exact terms stemming would blur."""

    assert tokenize("SEC-4412 and 26 weeks, v4") == [
        "sec", "4412", "and", "26", "weeks", "v4",
    ]


# --- fusion -----------------------------------------------------------

def test_rrf_promotes_the_chunk_both_retrievers_found():
    semantic = [chunk("a", score=0.1), chunk("b", score=0.2)]
    keyword = [chunk("b", score=9.0), chunk("c", score=8.0)]

    fused = fuse(semantic, keyword, top_k=3)

    # "b" is rank 2 in both; "a" is rank 1 in one only. Agreement wins.
    assert fused[0].chunk_id == "b"
    assert set(fused[0].sources) == {"semantic", "keyword"}


def test_rrf_score_is_the_sum_of_reciprocal_ranks():
    fused = fuse([chunk("a")], [chunk("a")], top_k=1)

    assert fused[0].fused_score == round(1 / 61 + 1 / 61, 6)


def test_fusion_records_each_retriever_rank_separately():
    fused = fuse(
        [chunk("x"), chunk("a")],
        [chunk("a")],
        top_k=2,
    )

    found = {c.chunk_id: c for c in fused}

    assert found["a"].semantic_rank == 2
    assert found["a"].keyword_rank == 1


def test_fusion_does_not_mutate_the_input_lists():
    semantic = [chunk("a")]
    fuse(semantic, [chunk("a")], top_k=1)

    assert semantic[0].sources == []


def test_fusion_renumbers_from_one():
    fused = fuse([chunk("a"), chunk("b")], [], top_k=2)

    assert [c.number for c in fused] == [1, 2]


# --- citations --------------------------------------------------------

def test_extract_cited_numbers_in_order_of_first_use():
    assert extract_cited_numbers("A [3]. B [1][3]. C [2]") == [3, 1, 2]


def test_extract_handles_comma_groups():
    assert extract_cited_numbers("Both apply [1, 2].") == [1, 2]


def test_extract_ignores_non_citation_brackets():
    assert extract_cited_numbers("See [appendix] and [1].") == [1]


def test_degenerate_detects_a_citation_only_answer():
    assert is_degenerate("[2]")
    assert is_degenerate("[1][3]")


def test_degenerate_allows_a_real_sentence():
    assert not is_degenerate("Employees accrue 22 days of leave. [1]")


def test_build_context_numbers_sources_and_shows_provenance():
    chunks = number_chunks(
        [
            chunk("a", content="Body one", section_path="Doc > 1.1", page_number=3),
            chunk("b", content="Body two"),
        ]
    )

    context = build_context(chunks)

    assert "[1] hr_policy.md | section: Doc > 1.1 | page 3" in context
    assert "[2] hr_policy.md" in context
    assert "Body one" in context and "Body two" in context


def test_citation_label_uses_the_filename():
    labelled = chunk("a", section_title="1.1 Annual Leave", page_number=4)

    assert labelled.citation_label() == (
        "hr_policy.md, Section 1.1 Annual Leave, Page 4"
    )


def test_chunk_from_metadata_tolerates_missing_fields():
    """Documents ingested before a field existed must still retrieve."""

    built = chunk_from_metadata(
        number=1,
        content="body",
        metadata={"document_id": "d1", "filename": "x.md"},
    )

    assert built.chunk_id == "d1:0"
    assert built.section_title is None
    assert built.page_number is None


def test_chunk_from_metadata_ignores_an_unparsable_page():
    built = chunk_from_metadata(
        number=1,
        content="body",
        metadata={"document_id": "d", "page_number": "not a number"},
    )

    assert built.page_number is None


# --- evidence ---------------------------------------------------------

def test_overlap_is_the_share_of_meaningful_query_terms_present():
    chunks = [chunk("a", content="Employees accrue annual leave each year.")]

    # "annual" and "leave" hit; "sabbatical" does not.
    assert keyword_overlap("annual leave sabbatical", chunks) == 2 / 3


def test_overlap_ignores_stopwords():
    chunks = [chunk("a", content="annual leave")]

    # "what", "is", "the" are stopwords, so this is a clean hit.
    assert keyword_overlap("What is the annual leave?", chunks) == 1.0


def test_overlap_of_a_query_with_no_meaningful_terms_is_total():
    assert keyword_overlap("what is the", [chunk("a")]) == 1.0


# --- document scoping -------------------------------------------------

def test_scope_clause_for_one_document():
    assert where_for_documents(["a"]) == {"document_id": "a"}


def test_scope_clause_for_several_is_deduped_and_sorted():
    assert where_for_documents(["b", "a", "b"]) == {
        "document_id": {"$in": ["a", "b"]}
    }


def test_no_scope_means_the_whole_library():
    assert where_for_documents(None) is None
    assert where_for_documents([]) is None


def test_a_scope_composes_with_an_existing_filter():
    combined = combine_where({"section_id": "s3"}, where_for_documents(["a"]))

    assert combined == {
        "$and": [{"section_id": "s3"}, {"document_id": "a"}]
    }


def test_combining_nothing_is_nothing():
    assert combine_where(None, None) is None
    assert combine_where({"a": 1}, None) == {"a": 1}
