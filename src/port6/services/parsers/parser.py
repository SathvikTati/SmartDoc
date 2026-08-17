"""Document parsing.

Parsers emit an ordered list of blocks rather than one flat string, so that
page numbers and heading structure survive into retrieval. `ParsedDocument.text`
is still the joined plain text, which keeps existing callers working.
"""

from pathlib import Path
import re

import markdown
from pydantic import BaseModel, Field
import pymupdf
from bs4 import BeautifulSoup
from docx import Document


# Matches "4.", "4.2", "4.2.1" and "Section 4" style numbering.
NUMBERED_HEADING = re.compile(
    r"^(?:section\s+)?(\d+(?:\.\d+)*)\.?\s+(\S.*)$",
    re.IGNORECASE,
)

# A heading is short; anything longer is almost certainly a sentence.
MAX_HEADING_CHARACTERS = 120

# "Version: 6.2" — a labelled metadata field rather than a section heading.
LABELLED_LINE = re.compile(r"^[A-Za-z][A-Za-z ]{1,30}:\s*\S")


class ParsedBlock(BaseModel):
    """One paragraph or heading, with where it came from."""

    text: str
    page_number: int | None = None

    # None for body text; 1..6 for a heading, where 1 is the top level.
    heading_level: int | None = None

    @property
    def is_heading(self) -> bool:
        return self.heading_level is not None


class ParsedDocument(BaseModel):
    source: str
    file_type: str
    text: str
    blocks: list[ParsedBlock] = Field(default_factory=list)


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = [line.strip() for line in text.splitlines()]

    cleaned_lines = []
    previous_empty = False

    for line in lines:
        if not line:
            if not previous_empty:
                cleaned_lines.append("")
            previous_empty = True
        else:
            cleaned_lines.append(line)
            previous_empty = False

    return "\n".join(cleaned_lines).strip()


def detect_heading_level(
    line: str,
) -> int | None:
    """Guess whether a line is a heading, for formats that do not say so.

    Used for PDF and plain text, where there is no style information. DOCX
    and Markdown carry explicit levels and do not need this.
    """

    stripped = line.strip()

    if not stripped or len(stripped) > MAX_HEADING_CHARACTERS:
        return None

    # Sentences and list items are not headings.
    if stripped.endswith((".", ",", ";", ":")) and not NUMBERED_HEADING.match(
        stripped
    ):
        return None

    match = NUMBERED_HEADING.match(stripped)

    if match:
        # A numbered heading sits under the document title, so "1." is
        # level 2 and "1.1" is level 3 — mirroring how the same document
        # would be written in Markdown (# title, ## 1., ### 1.1).
        depth = len(match.group(1).split("."))
        return min(depth + 1, 6)

    # "Version: 6.2" and "Effective From: 2026-01-01" are metadata fields,
    # not sections. Without this a document's header block would become a
    # handful of one-line sections.
    if LABELLED_LINE.match(stripped):
        return None

    words = stripped.split()

    # ALL CAPS lines of a few words read as section headers.
    if (
        stripped.isupper()
        and 1 <= len(words) <= 12
        and any(character.isalpha() for character in stripped)
    ):
        return 1

    # Title Case with no terminal punctuation, e.g. "Maternity Leave".
    if (
        1 < len(words) <= 8
        and not stripped.endswith((".", "?", "!"))
        and all(
            word[0].isupper()
            for word in words
            if word and word[0].isalpha()
        )
    ):
        return 1

    return None


def blocks_to_text(
    blocks: list[ParsedBlock],
) -> str:
    return clean_text(
        "\n\n".join(block.text for block in blocks)
    )


def _blocks_from_lines(
    text: str,
    page_number: int | None = None,
) -> list[ParsedBlock]:
    """Split plain text into blocks, inferring headings by shape."""

    blocks: list[ParsedBlock] = []
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return

        joined = "\n".join(paragraph).strip()

        if joined:
            blocks.append(
                ParsedBlock(
                    text=joined,
                    page_number=page_number,
                )
            )

        paragraph.clear()

    for line in text.splitlines():

        stripped = line.strip()

        if not stripped:
            flush()
            continue

        level = detect_heading_level(stripped)

        if level is not None:
            flush()
            blocks.append(
                ParsedBlock(
                    text=stripped,
                    page_number=page_number,
                    heading_level=level,
                )
            )
            continue

        paragraph.append(stripped)

    flush()

    return blocks


def parse(path: Path) -> ParsedDocument:
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    extension = path.suffix.lower()

    parsers = {
        ".pdf": pdf_parser,
        ".docx": doc_parser,
        ".txt": txt_parser,
        ".md": md_parser,
    }

    if extension not in parsers:
        raise ValueError(f"Unsupported file type: {extension}")

    return parsers[extension](path)


def pdf_parser(path: Path) -> ParsedDocument:
    blocks: list[ParsedBlock] = []

    with pymupdf.open(path) as doc:
        for page_index, page in enumerate(doc, start=1):

            text = clean_text(page.get_text())

            if not text:
                continue

            # Page numbers are only available here, so they are attached
            # before the pages get joined together.
            blocks.extend(
                _blocks_from_lines(
                    text,
                    page_number=page_index,
                )
            )

    if not blocks:
        raise ValueError(f"No text found in PDF: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="pdf",
        text=blocks_to_text(blocks),
        blocks=blocks,
    )


def doc_parser(path: Path) -> ParsedDocument:
    doc = Document(path)
    blocks: list[ParsedBlock] = []

    for paragraph in doc.paragraphs:

        text = clean_text(paragraph.text)

        if not text:
            continue

        # python-docx exposes the real outline, so no guessing is needed.
        style_name = (paragraph.style.name or "") if paragraph.style else ""

        heading_level = None

        if style_name.lower().startswith("heading"):
            digits = "".join(
                character
                for character in style_name
                if character.isdigit()
            )
            heading_level = int(digits) if digits else 1

        elif style_name.lower() == "title":
            heading_level = 1

        else:
            # Some documents mark headings by formatting alone.
            heading_level = detect_heading_level(text)

        blocks.append(
            ParsedBlock(
                text=text,
                heading_level=heading_level,
            )
        )

    for table_number, table in enumerate(doc.tables, start=1):

        table_lines = [f"Table {table_number}:"]

        for row in table.rows:
            cells = [clean_text(cell.text) for cell in row.cells]
            table_lines.append(" | ".join(cells))

        blocks.append(
            ParsedBlock(
                text="\n".join(table_lines),
            )
        )

    if not blocks:
        raise ValueError(f"No text found in DOCX: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="docx",
        text=blocks_to_text(blocks),
        blocks=blocks,
    )


def txt_parser(path: Path) -> ParsedDocument:
    text = clean_text(get_text_from_file(path))

    if not text:
        raise ValueError(f"TXT file is empty: {path}")

    blocks = _blocks_from_lines(text)

    return ParsedDocument(
        source=path.name,
        file_type="txt",
        text=text,
        blocks=blocks,
    )


def md_parser(path: Path) -> ParsedDocument:
    raw = get_text_from_file(path)

    if not raw.strip():
        raise ValueError(f"Markdown file is empty: {path}")

    html = markdown.markdown(
        raw,
        extensions=[
            "tables",
            "fenced_code",
        ],
    )

    soup = BeautifulSoup(html, "html.parser")

    blocks: list[ParsedBlock] = []

    # Markdown states its heading levels outright, so walk the rendered
    # elements rather than re-inferring structure from the text.
    for element in soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "li",
            "pre",
            "table",
            "blockquote",
        ]
    ):
        # Skip nodes whose text is already covered by an ancestor block.
        if element.find_parent(
            ["li", "pre", "table", "blockquote"]
        ):
            continue

        text = clean_text(element.get_text("\n"))

        if not text:
            continue

        heading_level = (
            int(element.name[1])
            if element.name.startswith("h") and element.name[1:].isdigit()
            else None
        )

        blocks.append(
            ParsedBlock(
                text=text,
                heading_level=heading_level,
            )
        )

    if not blocks:
        raise ValueError(f"No text found in Markdown: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="md",
        text=blocks_to_text(blocks),
        blocks=blocks,
    )


def get_text_from_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read()
