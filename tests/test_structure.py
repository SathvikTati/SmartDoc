"""Blocks -> section tree.

The tree is what keeps a chunk from straddling two unrelated policies and
what gives a citation its section path, so its parenting rules matter.
"""

from port6.services.parsers.parser import ParsedBlock
from port6.services.structure.service import (
    PREAMBLE_TITLE,
    build_sections,
    content_sections,
    section_outline,
)


def heading(text, level, page=None):
    return ParsedBlock(text=text, heading_level=level, page_number=page)


def body(text, page=None):
    return ParsedBlock(text=text, page_number=page)


def test_nests_by_heading_level():
    sections = build_sections(
        [
            heading("HR Policy", 1),
            heading("1. Leave", 2),
            heading("1.1 Annual", 3),
            body("22 days."),
        ]
    )

    by_title = {section.title: section for section in sections}

    assert by_title["1. Leave"].parent_section_id == by_title["HR Policy"].section_id
    assert by_title["1.1 Annual"].parent_section_id == by_title["1. Leave"].section_id
    assert by_title["1.1 Annual"].path == ["HR Policy", "1. Leave", "1.1 Annual"]


def test_siblings_do_not_nest_inside_each_other():
    sections = build_sections(
        [
            heading("Doc", 1),
            heading("A", 2),
            body("a"),
            heading("B", 2),
            body("b"),
        ]
    )

    by_title = {section.title: section for section in sections}

    assert by_title["A"].parent_section_id == by_title["B"].parent_section_id


def test_heading_only_sections_are_kept_so_parents_never_dangle():
    """A parent with no text of its own is still a parent.

    Dropping it would leave its children's parent_section_id pointing at a
    section that does not exist.
    """

    sections = build_sections(
        [
            heading("Doc", 1),
            heading("1. Leave", 2),  # no body of its own
            heading("1.1 Annual", 3),
            body("22 days."),
        ]
    )

    ids = {section.section_id for section in sections}
    parents = {
        section.parent_section_id
        for section in sections
        if section.parent_section_id
    }

    assert parents <= ids

    # ...but it is not chunked, because it holds no text.
    assert "1. Leave" not in {s.title for s in content_sections(sections)}


def test_content_before_any_heading_gets_a_home():
    sections = build_sections([body("Loose text with no heading above it.")])

    assert sections[0].title == PREAMBLE_TITLE
    assert sections[0].text.startswith("Loose text")


def test_a_section_holds_only_its_own_text():
    """Otherwise a parent and its child would both chunk the same words."""

    sections = build_sections(
        [
            heading("Parent", 1),
            body("parent text"),
            heading("Child", 2),
            body("child text"),
        ]
    )

    by_title = {section.title: section for section in sections}

    assert by_title["Parent"].text == "parent text"
    assert by_title["Child"].text == "child text"


def test_page_span_comes_from_the_blocks():
    sections = build_sections(
        [
            heading("Doc", 1, page=2),
            body("first", page=2),
            body("later", page=5),
        ]
    )

    assert sections[0].page_start == 2
    assert sections[0].page_end == 5


def test_outline_indents_by_level():
    sections = build_sections(
        [
            heading("Doc", 1),
            heading("Sub", 2),
        ]
    )

    outline = section_outline(sections)

    assert "- [s1] Doc" in outline
    assert "  - [s2] Sub" in outline
