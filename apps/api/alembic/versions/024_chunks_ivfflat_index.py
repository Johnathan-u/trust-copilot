"""Add hnsw index on chunks.embedding for scalable semantic search.

Converts embedding column from float[] to vector(1536) for pgvector native operators.
Creates hnsw index (supports empty tables; ivfflat requires data for k-means).
Uses vector_cosine_ops for cosine distance (<=>).

Revision ID: 024
Revises: 023
Create Date: 2026-03-17

"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure vector extension exists
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Convert embedding from float[] to vector(1536) for pgvector native operators
    op.execute("""
        ALTER TABLE chunks
        ALTER COLUMN embedding TYPE vector(1536)
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE ('[' || array_to_string(embedding, ',') || ']')::vector
            END
        )
    """)

    # Create hnsw index (works on empty tables; better for incremental inserts)
    op.execute("""
        CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("ANALYZE chunks")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS chunks_embedding_hnsw_idx")

    # Revert embedding to float[]: vector::text is '[a,b,c]', we need '{a,b,c}' for double precision[]
    op.execute("""
        ALTER TABLE chunks
        ALTER COLUMN embedding TYPE double precision[]
        USING (
            CASE
                WHEN embedding IS NULL THEN NULL
                ELSE ('{' || trim(both '[]' from embedding::text) || '}')::double precision[]
            END
        )
    """)
