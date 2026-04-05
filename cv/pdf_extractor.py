"""
PDF CV text extractor.

Strategy:
  1. Try pdfplumber first (best for structured/table layouts)
  2. Fall back to PyMuPDF (fitz) — faster, handles complex PDFs
  3. Fall back to OCR via pytesseract if text layer is missing (scanned PDFs)
"""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Optional

from loguru import logger


def extract_text_from_pdf(path: str | Path) -> str:
    """
    Extract all text from a PDF file.
    Returns clean text ready for LLM parsing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    text = _try_pdfplumber(path)
    if text and len(text.strip()) > 100:
        logger.info(f"[PDF] Extracted {len(text)} chars via pdfplumber: {path.name}")
        return _clean_text(text)

    text = _try_pymupdf(path)
    if text and len(text.strip()) > 100:
        logger.info(f"[PDF] Extracted {len(text)} chars via PyMuPDF: {path.name}")
        return _clean_text(text)

    # Last resort: OCR
    logger.warning(f"[PDF] Low text yield, attempting OCR: {path.name}")
    text = _try_ocr(path)
    logger.info(f"[PDF] OCR extracted {len(text)} chars")
    return _clean_text(text)


def _try_pdfplumber(path: Path) -> Optional[str]:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            parts = []
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if text:
                    parts.append(text)
                # Also extract tables
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            parts.append(" | ".join(str(cell or "") for cell in row))
            return "\n".join(parts)
    except Exception as e:
        logger.debug(f"[PDF] pdfplumber failed: {e}")
        return None


def _try_pymupdf(path: Path) -> Optional[str]:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        parts = []
        for page in doc:
            text = page.get_text("text")
            if text:
                parts.append(text)
        doc.close()
        return "\n".join(parts)
    except Exception as e:
        logger.debug(f"[PDF] PyMuPDF failed: {e}")
        return None


def _try_ocr(path: Path) -> str:
    """Convert PDF pages to images and OCR them."""
    try:
        import fitz
        import pytesseract
        from PIL import Image

        doc = fitz.open(str(path))
        parts = []
        for page in doc:
            # Render at 300 DPI for good OCR quality
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang="deu+eng")
            parts.append(text)
        doc.close()
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"[PDF] OCR failed: {e}")
        return ""


def _clean_text(text: str) -> str:
    """Clean extracted text for LLM consumption."""
    import re
    # Remove excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {3,}", " ", text)
    # Remove non-printable characters except common ones
    text = "".join(c for c in text if c.isprintable() or c in "\n\t")
    return text.strip()


def pdf_to_base64(path: str | Path) -> str:
    """Read a PDF and return its base64-encoded content (for DB storage)."""
    path = Path(path)
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def get_pdf_metadata(path: str | Path) -> dict:
    """Extract metadata from a PDF file."""
    path = Path(path)
    try:
        import fitz
        doc = fitz.open(str(path))
        meta = doc.metadata
        meta["page_count"] = doc.page_count
        doc.close()
        return meta
    except Exception:
        return {"page_count": 0}
