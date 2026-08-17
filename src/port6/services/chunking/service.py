"""Chunking.

Chunks are cut inside a section rather than across the whole document, so a
chunk never straddles two unrelated parts of a policy, and each one carries
the section and page it came from.
"""

from __future__ import annotations

from langchain_core.documents import Document as LangChainDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from port6.config import chunking_config
from port6.services.parsers.parser import ParsedBlock
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


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunking_config.get(
            "chunk_size",
            1000,
        ),
        chunk_overlap=chunking_config.get(
            "chunk_overlap",
            200,
        ),
        length_function=len,
        separators=SEPARATORS,
    )


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

        # Prefer the page the section starts on; a section rarely spans many.
        page_number = section.page_start

        for piece in splitter.split_text(section_text):

            if not piece.strip():
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
                "page_number": page_number,
            }

            chunks.append(
                LangChainDocument(
                    page_content=piece,
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
