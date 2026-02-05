"""PDF text extraction utilities."""

from PyPDF2 import PdfReader
from config import MAX_PAGES


def extract_text_from_pdf(path, max_pages=None):
    """
    Extract text from PDF file.
    
    Args:
        path: Path to PDF file
        max_pages: Maximum pages to extract (defaults to config.MAX_PAGES)
    
    Returns:
        Concatenated text from all pages
    """
    if max_pages is None:
        max_pages = MAX_PAGES
    
    reader = PdfReader(path)
    texts = []
    for i in range(min(len(reader.pages), max_pages)):
        try:
            texts.append(reader.pages[i].extract_text() or "")
        except Exception:
            texts.append("")
    return "\n\n".join(texts)
