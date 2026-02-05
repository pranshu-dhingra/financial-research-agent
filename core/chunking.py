"""Text chunking utilities."""

from config import CHUNK_SIZE, CHUNK_OVERLAP


def chunk_text(text, chunk_size=None, chunk_overlap=None):
    """
    Split text into overlapping chunks.
    
    Args:
        text: Text to chunk
        chunk_size: Size of each chunk (defaults to config.CHUNK_SIZE)
        chunk_overlap: Overlap between chunks (defaults to config.CHUNK_OVERLAP)
    
    Returns:
        List of text chunks
    """
    if chunk_size is None:
        chunk_size = CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = CHUNK_OVERLAP
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - chunk_overlap
    return chunks
