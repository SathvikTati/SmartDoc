"""OCR for the parts of a document a text layer does not cover.

A PDF carries text two ways. A digital PDF has a real text layer, which
`page.get_text()` returns for free. A scanned one is a picture of a page:
the words are pixels, `get_text()` returns nothing, and the parser used to
reject the file as empty. This recovers the second kind.

**Per page, not per file**, because the two mix. A single PDF can hold
digital pages and scanned pages, and a digital page can hold a scanned
table pasted in as an image — text that is invisible to retrieval and the
most likely thing anyone would want to ask about. So each page is
classified on its own:

    text, no images   ->  nothing to do, and no cost
    text and images   ->  OCR only the images; the text layer is kept
    no text, images   ->  rasterise and OCR the whole page
    neither           ->  a genuinely blank page

`full=False` is what makes the middle case safe: PyMuPDF OCRs the images
and leaves the existing text alone, so nothing is read twice.

**Tesseract, through PyMuPDF.** The PDF parser already depends on PyMuPDF,
which speaks to Tesseract directly, so OCR costs no new Python package —
only the `tesseract` binary. Everything here degrades to "no OCR" when
that binary is absent rather than failing the parse, which is what keeps a
machine without it behaving exactly as before.
"""

from __future__ import annotations

import logging

import pymupdf


logger = logging.getLogger(__name__)


LANGUAGE = "eng"

# Below this, a page's text layer is treated as absent rather than sparse.
# A scanned page is not always perfectly empty — a header stamped on by the
# scanner, or a stray ligature, can leave a few characters behind, and
# those must not be mistaken for a real text layer.
MIN_PAGE_CHARACTERS = 8

# What a page needs doing to it. `None` means nothing.
OCR_IMAGES = "images"
OCR_FULL = "full"


def is_available() -> bool:
    """Whether Tesseract can be reached.

    No credentials to check, only the binary and its language data. Guarded
    because PyMuPDF raises rather than returning false when the tessdata
    directory cannot be resolved.
    """

    try:
        return bool(pymupdf.get_tessdata())

    except Exception:
        return False


def page_mode(page) -> str | None:
    """How this page should be OCR'd, from what it already offers.

    Cheap on purpose: text length and an image count, both of which the
    parser would read anyway. Deciding this for every page before OCRing
    any of them is what lets a page budget be enforced up front instead of
    discovered halfway through a long file.
    """

    has_text = len(page.get_text().strip()) >= MIN_PAGE_CHARACTERS
    has_images = bool(page.get_images(full=True))

    if not has_images:
        # Either the text layer is all there is, or the page is blank.
        return None

    return OCR_IMAGES if has_text else OCR_FULL


def pages_to_ocr(document) -> dict[int, str]:
    """`{page index: mode}` for every page needing OCR, cheaply.

    Page indexes are 0-based, matching PyMuPDF.
    """

    modes = {}

    for index in range(len(document)):
        mode = page_mode(document[index])

        if mode is not None:
            modes[index] = mode

    return modes


def ocr_page(
    page,
    dpi: int,
    full: bool,
) -> str:
    """The page's text with OCR applied. Empty string on failure.

    Swallowed rather than raised: one unreadable page should cost that
    page, not the whole document. The caller keeps whatever the text layer
    gave it.
    """

    try:
        textpage = page.get_textpage_ocr(
            dpi=dpi,
            full=full,
            language=LANGUAGE,
        )

        return page.get_text(textpage=textpage)

    except Exception as exc:
        logger.warning(
            "OCR failed on page %d (full=%s): %s",
            page.number,
            full,
            exc,
        )
        return ""


def ocr_image_bytes(
    data: bytes,
    dpi: int,
) -> str:
    """Text found in a standalone image. Empty string on failure.

    Used for DOCX, where images are package parts rather than page
    content, so there is no page to hand to `ocr_page`.
    """

    try:
        pixmap = pymupdf.Pixmap(data)

    except Exception as exc:
        logger.warning("Could not read image for OCR: %s", exc)
        return ""

    try:
        # Tesseract writes its findings back as a one-page PDF with a text
        # layer, which is then read the ordinary way.
        rendered = pymupdf.open(
            "pdf",
            pixmap.pdfocr_tobytes(language=LANGUAGE),
        )

    except Exception as exc:
        logger.warning("OCR failed on an embedded image: %s", exc)
        return ""

    try:
        return rendered[0].get_text()

    finally:
        rendered.close()
