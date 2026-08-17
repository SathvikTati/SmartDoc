"""Chunking, and the page number each chunk is cited with.

The page-number case is a regression test: every chunk in a section used to
be stamped with the section's *first* page, so a section spanning pages 4-7
cited all of its content as page 4.
"""

from port6.services.chunking.service import (
    chunk_document,
    chunk_sections,
    clean_metadata,
    page_for_offset,
    page_index,
)
from port6.services.ingestion.service import split_for_summary
from port6.services.parsers.parser import ParsedBlock
from port6.services.structure.service import build_sections


def blocks_across_pages(pages, size=700):
    """A heading plus one long body block per page."""

    result = [ParsedBlock(text="4. Leave", heading_level=1, page_number=pages[0])]

    for page in pages:
        result.append(
            ParsedBlock(text=f"Page {page} content. " + "x" * size, page_number=page)
        )

    return result


def test_chunk_is_cited_with_the_page_it_came_from():
    blocks = blocks_across_pages([4, 5, 6, 7])

    chunks = chunk_document(
        "doc-1",
        "multi.pdf",
        "\n\n".join(block.text for block in blocks),
        blocks=blocks,
    )

    pages = [chunk.metadata.get("page_number") for chunk in chunks]

    # The bug: this used to be [4, 4, 4, 4].
    assert pages == [4, 5, 6, 7]


def test_page_index_spans_line_up_with_the_joined_text():
    sections = build_sections(blocks_across_pages([1, 2]))
    section = [s for s in sections if s.blocks][0]

    spans = page_index(section)
    text = section.text

    for start, end, page in spans:
        assert text[start:end] == section.blocks[
            [s[2] for s in spans].index(page)
        ].text


def test_page_for_offset_falls_back_when_nothing_matches():
    assert page_for_offset([], 0, fallback=3) == 3
    assert page_for_offset([(0, 10, None)], 5, fallback=3) == 3


def test_page_for_offset_uses_the_preceding_block_past_the_end():
    spans = [(0, 10, 1), (12, 20, 2)]

    # An offset landing on the separator between blocks.
    assert page_for_offset(spans, 11, fallback=None) == 1


def test_chunks_never_straddle_two_sections():
    blocks = [
        ParsedBlock(text="1.1 Annual Leave", heading_level=2),
        ParsedBlock(text="Employees accrue 22 days of annual leave."),
        ParsedBlock(text="2. Probation", heading_level=2),
        ParsedBlock(text="Probation lasts three months."),
    ]

    chunks = chunk_document("doc-2", "hr.md", "irrelevant", blocks=blocks)

    for chunk in chunks:
        leave = "annual leave" in chunk.page_content.lower()
        probation = "probation lasts" in chunk.page_content.lower()
        assert not (leave and probation)


def test_chunk_ids_are_sequential_and_unique():
    blocks = blocks_across_pages([1, 2, 3])

    chunks = chunk_document("doc-3", "x.pdf", "text", blocks=blocks)

    indices = [chunk.metadata["chunk_index"] for chunk in chunks]

    assert indices == list(range(len(chunks)))
    assert len({chunk.metadata["chunk_id"] for chunk in chunks}) == len(chunks)
    assert all(
        chunk.metadata["chunk_id"] == f"doc-3:{chunk.metadata['chunk_index']}"
        for chunk in chunks
    )


def test_document_without_blocks_is_one_unstructured_section():
    chunks = chunk_document("doc-4", "plain.txt", "Some content here.")

    assert len(chunks) == 1
    assert chunks[0].metadata["section_id"]


def test_empty_content_is_rejected():
    try:
        chunk_document("doc-5", "empty.txt", "   ")
    except ValueError as exc:
        assert "no content" in str(exc)
    else:
        raise AssertionError("expected ValueError for empty content")


def test_clean_metadata_drops_none_which_chroma_rejects():
    cleaned = clean_metadata(
        {"a": 1, "b": None, "c": "", "d": "keep", "e": [1, 2]}
    )

    assert "b" not in cleaned
    assert "c" not in cleaned
    assert cleaned["a"] == 1
    assert cleaned["d"] == "keep"
    # Non-scalars are stringified rather than dropped.
    assert cleaned["e"] == "[1, 2]"


def test_sections_with_no_text_produce_no_chunks():
    sections = build_sections(
        [ParsedBlock(text="Heading only", heading_level=1)]
    )

    assert chunk_sections("doc-6", "x.md", sections) == []


# --- summary windowing ------------------------------------------------

def test_short_document_is_one_summary_call():
    assert split_for_summary("short", window=100, max_parts=6) == ["short"]


def test_medium_document_is_covered_completely():
    content = "x" * 250
    parts = split_for_summary(content, window=100, max_parts=6)

    assert len(parts) == 3
    assert "".join(parts) == content


def test_very_long_document_samples_across_its_whole_length():
    """The old behaviour truncated to the opening, which is what made the
    largest documents the hardest to find at stage 1."""

    # Every 1000-character block is uniquely marked, so a window's position
    # in the document is unambiguous.
    content = "".join(f"[block{index:03d}]".ljust(1000, ".") for index in range(100))
    parts = split_for_summary(content, window=1000, max_parts=5)

    assert len(parts) == 5

    # Windows must span the document, not cluster at the start.
    positions = [content.index(part) for part in parts]

    assert positions == sorted(positions)
    assert positions[0] == 0
    assert positions[-1] > len(content) * 0.9

    # And the tail must actually be represented.
    assert "block099" in parts[-1]
