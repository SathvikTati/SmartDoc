"""Turn a flat list of parsed blocks into a document -> section tree.

Hierarchical retrieval narrows document -> section -> chunk, so every chunk
needs to know which section it belongs to and which section that sits under.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from port6.services.parsers.parser import ParsedBlock


# Content that appears before the first heading still needs a home.
PREAMBLE_TITLE = "Preamble"


class Section(BaseModel):
    section_id: str
    title: str
    level: int
    parent_section_id: str | None = None

    # Titles from the root down to and including this section.
    path: list[str] = Field(default_factory=list)

    blocks: list[ParsedBlock] = Field(default_factory=list)

    @property
    def path_label(self) -> str:
        return " > ".join(self.path)

    @property
    def text(self) -> str:
        return "\n\n".join(
            block.text
            for block in self.blocks
        ).strip()

    @property
    def page_start(self) -> int | None:
        pages = [
            block.page_number
            for block in self.blocks
            if block.page_number is not None
        ]
        return min(pages) if pages else None

    @property
    def page_end(self) -> int | None:
        pages = [
            block.page_number
            for block in self.blocks
            if block.page_number is not None
        ]
        return max(pages) if pages else None


def build_sections(
    blocks: list[ParsedBlock],
) -> list[Section]:
    """Group blocks under the headings that precede them.

    Returns sections in document order. A section's `blocks` holds only its
    own content, not its children's, so chunking a section does not duplicate
    text that a subsection will also chunk.
    """

    sections: list[Section] = []

    # Open sections from the root down to the current depth.
    stack: list[Section] = []

    def new_section(
        title: str,
        level: int,
    ) -> Section:

        parent = stack[-1] if stack else None

        section = Section(
            section_id=f"s{len(sections) + 1}",
            title=title,
            level=level,
            parent_section_id=(
                parent.section_id if parent else None
            ),
            path=(
                [*parent.path, title]
                if parent
                else [title]
            ),
        )

        sections.append(section)
        stack.append(section)

        return section

    for block in blocks:

        if not block.is_heading:

            if not stack:
                # Content before any heading.
                new_section(PREAMBLE_TITLE, 1)

            stack[-1].blocks.append(block)
            continue

        level = block.heading_level or 1

        # Close every open section at this level or deeper before opening
        # the new one, so siblings do not nest inside each other.
        while stack and stack[-1].level >= level:
            stack.pop()

        new_section(block.text, level)

    # Sections with no body text of their own are kept: they carry no chunks
    # but they are still parents, and dropping them would leave their
    # children's parent_section_id pointing at nothing.
    return sections


def content_sections(
    sections: list[Section],
) -> list[Section]:
    """Only the sections that hold text, i.e. the ones worth chunking."""

    return [
        section
        for section in sections
        if section.blocks
    ]


def section_outline(
    sections: list[Section],
    limit: int | None = None,
) -> str:
    """A compact outline, used to let a model pick relevant sections."""

    lines = []

    for section in sections[: limit or len(sections)]:
        indent = "  " * max(section.level - 1, 0)
        lines.append(
            f"{indent}- [{section.section_id}] {section.title}"
        )

    return "\n".join(lines)
