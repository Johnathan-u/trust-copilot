"""Persist SHA-256, version, and media type for documents and exports (TC-10-006).

Existing rows stay null. A null hash is not a download. The operator command
``python -m app.services.storage_checksum`` fills the columns from the current
object. Downgrade drops the columns. The objects stay. A later upgrade leaves
the hashes null again, and downloads stay refused until the command runs again.

The revision id is 26 characters and fits ``alembic_version.version_num``
(varchar(32)). ``down_revision`` is the single Alembic head on master when this
file is parented. This revision does not import the application package.

Revision ID: tc10006_storage_checksums
Revises: tc20050_crm_pipeline_sync
"""

import sqlalchemy as sa
from alembic import op

revision = "tc10006_storage_checksums"
down_revision = "tc20050_crm_pipeline_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("object_version", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("object_media_type", sa.String(length=128), nullable=True))
    op.add_column(
        "export_records", sa.Column("content_sha256", sa.String(length=64), nullable=True)
    )
    op.add_column("export_records", sa.Column("object_version", sa.Integer(), nullable=True))
    op.add_column("export_records", sa.Column("content_type", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("export_records", "content_type")
    op.drop_column("export_records", "object_version")
    op.drop_column("export_records", "content_sha256")
    op.drop_column("documents", "object_media_type")
    op.drop_column("documents", "object_version")
    op.drop_column("documents", "content_sha256")
