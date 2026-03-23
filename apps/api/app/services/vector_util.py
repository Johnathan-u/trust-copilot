"""Shared vector formatting and validation for pgvector (indexing and retrieval)."""

import math

from app.services.embedding_service import EMBEDDING_DIM


def embedding_to_vector_literal(emb: list[float]) -> str:
    """
    Format embedding as PostgreSQL vector literal.
    Avoids scientific notation and nan/inf which can break the parser.
    Caller must ensure emb length is EMBEDDING_DIM; use validate_embedding_dimension first.
    """
    def _one(x: float) -> str:
        if not math.isfinite(x):
            return "0.0"
        return format(float(x), ".10f")
    return "[" + ",".join(_one(x) for x in emb) + "]"


def validate_embedding_dimension(embedding: list[float] | None, context: str = "embedding") -> None:
    """Raise ValueError if embedding is None, not a list, or length != EMBEDDING_DIM."""
    if embedding is None:
        raise ValueError(f"{context}: embedding is None")
    if not isinstance(embedding, list):
        raise ValueError(f"{context}: embedding is not a list")
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"{context}: embedding length {len(embedding)} != required {EMBEDDING_DIM}"
        )
