"""Chunking.

Chunks are cut inside a section rather than across the whole document, so a
chunk never straddles two unrelated parts of a policy, and each one carries
the section and page it came from.
"""

from __future__ import annotations

from langchain_core.documents import Document as LangChainDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from port6.services.parsers.parser import ParsedBlock
from port6.services.settings.service import get_int
from port6.services.structure.service import (
    Section,
    build_sections,
    content_sections,
)


SEPARATORS = [
    "\n\n",
    "\n",
    ". ",
    " ",
    "",
]

# How sections join their blocks; the offset maths below depends on it.
BLOCK_SEPARATOR = "\n\n"


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=get_int("chunking.chunk_size"),
        chunk_overlap=get_int("chunking.chunk_overlap"),
        length_function=len,
        separators=SEPARATORS,
        # Offsets are what let a chunk be traced back to the block, and
        # therefore the page, it actually came from.
        add_start_index=True,
    )


def page_index(
    section: Section,
) -> list[tuple[int, int, int | None]]:
    """`(start, end, page)` for each block, in the section's own text.

    Section text is the blocks joined by a blank line, so a chunk's start
    offset locates the block it began in — and that block knows its page.
    """

    spans: list[tuple[int, int, int | None]] = []
    cursor = 0

    for block in section.blocks:
        length = len(block.text)
        spans.append((cursor, cursor + length, block.page_number))
        cursor += length + len(BLOCK_SEPARATOR)

    return spans


def page_for_offset(
    spans: list[tuple[int, int, int | None]],
    offset: int,
    fallback: int | None,
) -> int | None:
    """The page of the block a chunk starts in.

    Using the section's first page for every chunk was wrong: a section
    spanning pages 4-7 cited all of its chunks as page 4.
    """

    for start, end, page in spans:
        if start <= offset < end:
            return page if page is not None else fallback

    # An offset past the last block means the splitter landed on a
    # separator; the nearest preceding block is the honest answer.
    for start, end, page in reversed(spans):
        if offset >= start and page is not None:
            return page

    return fallback


def clean_metadata(
    metadata: dict,
) -> dict:
    """Drop empty values; Chroma only accepts scalar metadata."""

    cleaned = {}

    for key, value in metadata.items():

        if value is None or value == "":
            continue

        if isinstance(value, (str, int, float, bool)):
            cleaned[key] = value

        else:
            cleaned[key] = str(value)

    return cleaned


def chunk_sections(
    document_id: str,
    filename: str,
    sections: list[Section],
) -> list[LangChainDocument]:
    """Chunk each section separately and stamp the hierarchy onto every chunk."""

    splitter = _splitter()

    chunks: list[LangChainDocument] = []

    for section in content_sections(sections):

        section_text = section.text

        if not section_text.strip():
            continue

        spans = page_index(section)

        # create_documents rather than split_text: it carries the start
        # offset of each piece, which is how the page is recovered.
        for piece in splitter.create_documents([section_text]):

            if not piece.page_content.strip():
                continue

            chunk_index = len(chunks)

            metadata = {
                "document_id": document_id,
                "filename": filename,
                "chunk_index": chunk_index,
                "chunk_id": f"{document_id}:{chunk_index}",
                "section_id": section.section_id,
                "section_title": section.title,
                "section_path": section.path_label,
                "section_level": section.level,
                "parent_section_id": section.parent_section_id,
                "page_number": page_for_offset(
                    spans,
                    piece.metadata.get("start_index", 0),
                    section.page_start,
                ),
            }

            chunks.append(
                LangChainDocument(
                    page_content=piece.page_content,
                    metadata=clean_metadata(metadata),
                )
            )

    return chunks


def chunk_document(
    document_id: str,
    filename: str,
    content: str,
    blocks: list[ParsedBlock] | None = None,
) -> list[LangChainDocument]:
    """Chunk a document, using its structure when it is available.

    `blocks` comes from the parser. Without it the content is treated as one
    unstructured section, which is what happens for documents ingested before
    structure extraction existed.
    """

    if not content or not content.strip():
        raise ValueError(
            f"Document {document_id} has no content to chunk"
        )

    if blocks:
        sections = build_sections(blocks)

    else:
        sections = build_sections(
            [ParsedBlock(text=content)]
        )

    return chunk_sections(
        document_id=document_id,
        filename=filename,
        sections=sections,
    )
