"""
core/document_parser.py — Document parsing, page extraction, and semantic chunking.

Supported file types:
  - .pdf (page-by-page via PyMuPDF / fitz)
  - .txt
  - .md

Key features:
  - Page-by-page extraction preserving 1-indexed page numbers
  - Detection of empty / scanned / image-only PDFs
  - SHA-256 file hashing
  - Semantic-friendly chunking with paragraph/sentence boundaries and overlap
"""

import hashlib
import os
import re

SUPPORTED_DOC_EXTENSIONS = {".pdf", ".txt", ".md"}


def compute_file_hash(path: str) -> str:
    """Compute SHA-256 hexadecimal digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_document_pages(path: str) -> tuple[list[dict], str | None]:
    """
    Extract text from a document into a list of page dicts.

    Returns:
        (pages: list[{"page_number": int, "text": str}], error_message: str | None)

    Each page dict contains:
        page_number: 1-indexed integer
        text: extracted text content
    """
    if not os.path.exists(path):
        return [], f"File does not exist: {path}"

    if not os.path.isfile(path):
        return [], f"Not a regular file: {path}"

    _, ext = os.path.splitext(path)
    ext_lower = ext.lower()

    if ext_lower not in SUPPORTED_DOC_EXTENSIONS:
        return (
            [],
            f"Unsupported document extension '{ext}'.\n"
            f"[dim]Supported: {', '.join(sorted(SUPPORTED_DOC_EXTENSIONS))}[/dim]"
        )

    if ext_lower == ".pdf":
        return _extract_pdf_pages(path)
    else:
        return _extract_text_file(path)


def _extract_pdf_pages(path: str) -> tuple[list[dict], str | None]:
    """Extract text page-by-page from a PDF using PyMuPDF."""
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            return [], "PyMuPDF (fitz) is not installed. Please install pymupdf."

    pages = []
    total_text_len = 0

    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            return [], "PDF is password-protected or encrypted."

        page_count = len(doc)
        if page_count == 0:
            return [], "PDF contains no pages."

        for page_idx in range(page_count):
            page = doc[page_idx]
            text = page.get_text() or ""
            cleaned = text.strip()
            pages.append({
                "page_number": page_idx + 1,
                "text": cleaned
            })
            total_text_len += len(cleaned)

        doc.close()

        if total_text_len == 0:
            return (
                [],
                "No extractable text found in PDF. Scanned or image-only PDFs "
                "without an embedded text layer are not supported yet."
            )

        return pages, None

    except Exception as e:
        return [], f"Error reading PDF: {e}"


def _extract_text_file(path: str) -> tuple[list[dict], str | None]:
    """Extract text from .txt or .md as a single page (page 1)."""
    try:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

        cleaned = content.strip()
        if not cleaned:
            return [], "Document is empty."

        return [{"page_number": 1, "text": cleaned}], None
    except Exception as e:
        return [], f"Error reading document: {e}"


def chunk_document_pages(
    pages: list[dict],
    target_tokens: int = 800,
    overlap_tokens: int = 150,
) -> list[dict]:
    """
    Chunk document pages into semantic blocks preserving page association.

    Target tokens: 600–1000 tokens (~2400–4000 chars)
    Overlap tokens: 100–200 tokens (~400–800 chars)

    Returns:
        list of chunk dicts:
        [
            {
                "page_number": int,
                "chunk_index": int,
                "text": str,
                "token_estimate": int
            }, ...
        ]
    """
    target_chars = target_tokens * 4
    overlap_chars = overlap_tokens * 4

    chunks = []
    chunk_index = 0

    for page in pages:
        page_num = page["page_number"]
        page_text = page["text"].strip()
        if not page_text:
            continue

        # If page fits within target chunk size, keep it as a single chunk
        if len(page_text) <= target_chars:
            chunks.append({
                "page_number": page_num,
                "chunk_index": chunk_index,
                "text": page_text,
                "token_estimate": max(1, len(page_text) // 4)
            })
            chunk_index += 1
            continue

        # Split page into paragraphs
        paragraphs = re.split(r"\n\s*\n", page_text)
        current_chunk = []
        current_len = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_len = len(para)

            # If a single paragraph is larger than target_chars, split by sentences
            if para_len > target_chars:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if current_len + len(sentence) > target_chars and current_chunk:
                        chunk_text = " ".join(current_chunk)
                        chunks.append({
                            "page_number": page_num,
                            "chunk_index": chunk_index,
                            "text": chunk_text,
                            "token_estimate": max(1, len(chunk_text) // 4)
                        })
                        chunk_index += 1

                        # Retain overlap from end of chunk
                        overlap_budget = overlap_chars
                        overlap_parts = []
                        for part in reversed(current_chunk):
                            if overlap_budget <= 0:
                                break
                            overlap_parts.insert(0, part)
                            overlap_budget -= len(part)

                        current_chunk = overlap_parts + [sentence]
                        current_len = sum(len(p) for p in current_chunk) + len(current_chunk)
                    else:
                        current_chunk.append(sentence)
                        current_len += len(sentence) + 1
            else:
                if current_len + para_len > target_chars and current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append({
                        "page_number": page_num,
                        "chunk_index": chunk_index,
                        "text": chunk_text,
                        "token_estimate": max(1, len(chunk_text) // 4)
                    })
                    chunk_index += 1

                    # Retain overlap
                    overlap_budget = overlap_chars
                    overlap_parts = []
                    for part in reversed(current_chunk):
                        if overlap_budget <= 0:
                            break
                        overlap_parts.insert(0, part)
                        overlap_budget -= len(part)

                    current_chunk = overlap_parts + [para]
                    current_len = sum(len(p) for p in current_chunk) + len(current_chunk)
                else:
                    current_chunk.append(para)
                    current_len += para_len + 2

        if current_chunk:
            chunk_text = "\n\n".join(current_chunk).strip()
            if chunk_text:
                chunks.append({
                    "page_number": page_num,
                    "chunk_index": chunk_index,
                    "text": chunk_text,
                    "token_estimate": max(1, len(chunk_text) // 4)
                })
                chunk_index += 1

    return chunks
