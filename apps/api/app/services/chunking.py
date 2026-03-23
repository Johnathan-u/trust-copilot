"""Chunking service (DOC-06)."""


def chunk_text(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """Split text into retrieval-friendly segments."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def chunk_evidence(parsed: list[dict], chunk_size: int = 512, overlap: int = 64) -> list[dict]:
    """Chunk parsed evidence with metadata (DOC-07)."""
    full_text = " ".join(p.get("text", "") for p in parsed)
    chunks = chunk_text(full_text, chunk_size, overlap)
    return [{"text": c, "metadata": {"chunk_index": i}} for i, c in enumerate(chunks)]
