from pathlib import Path
import markdown
from pydantic import BaseModel
import pymupdf
from bs4 import BeautifulSoup
from docx import Document


class ParsedDocument(BaseModel):
    source: str
    file_type: str
    text: str


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
        ".md": md_parser
    }

    if extension not in parsers:
        raise ValueError(f"Unsupported file type: {extension}")

    return parsers[extension](path)


def pdf_parser(path: Path) -> ParsedDocument:
    pages = []

    with pymupdf.open(path) as doc:
        for page in doc:
            text = clean_text(page.get_text())

            if text:
                pages.append(text)

    text = "\n\n".join(pages)

    if not text:
        raise ValueError(f"No text found in PDF: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="pdf",
        text=text
    )


def doc_parser(path: Path) -> ParsedDocument:
    doc = Document(path)
    sections = []

    for paragraph in doc.paragraphs:
        text = clean_text(paragraph.text)

        if text:
            sections.append(text)

    for table_number, table in enumerate(doc.tables, start=1):
        table_lines = [f"Table {table_number}:"]

        for row in table.rows:
            cells = []

            for cell in row.cells:
                cells.append(clean_text(cell.text))

            table_lines.append(" | ".join(cells))

        sections.append("\n".join(table_lines))

    text = "\n\n".join(sections)
    text = clean_text(text)

    if not text:
        raise ValueError(f"No text found in DOCX: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="docx",
        text=text
    )


def txt_parser(path: Path) -> ParsedDocument:
    text = get_text_from_file(path)
    text = clean_text(text)

    if not text:
        raise ValueError(f"TXT file is empty: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="txt",
        text=text
    )


def md_parser(path: Path) -> ParsedDocument:
    text = get_text_from_file(path)

    if not text.strip():
        raise ValueError(f"Markdown file is empty: {path}")

    html = markdown.markdown(
        text,
        extensions=[
            "tables",
            "fenced_code"
        ]
    )

    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text("\n")
    text = clean_text(text)

    if not text:
        raise ValueError(f"No text found in Markdown: {path}")

    return ParsedDocument(
        source=path.name,
        file_type="md",
        text=text
    )


def get_text_from_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as file:
        return file.read()