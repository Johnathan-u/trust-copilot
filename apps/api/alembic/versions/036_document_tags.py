"""Add tags and document_tags tables for enterprise document tagging.

Revision ID: 036
Revises: 035
"""
from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tags_workspace_id", "tags", ["workspace_id"])
    op.create_index("ix_tags_category_key", "tags", ["category", "key"])
    op.execute(
        "ALTER TABLE tags ADD CONSTRAINT uq_tags_ws_cat_key "
        "UNIQUE NULLS NOT DISTINCT (workspace_id, category, key)"
    )

    op.create_table(
        "document_tags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_tags_workspace_id", "document_tags", ["workspace_id"])
    op.create_index("ix_document_tags_document_id", "document_tags", ["document_id"])
    op.create_index("ix_document_tags_tag_id", "document_tags", ["tag_id"])
    op.create_unique_constraint("uq_document_tags_doc_tag", "document_tags", ["document_id", "tag_id"])

    # Seed system tags
    tags_table = sa.table(
        "tags",
        sa.column("workspace_id", sa.Integer),
        sa.column("category", sa.String),
        sa.column("key", sa.String),
        sa.column("label", sa.String),
        sa.column("is_system", sa.Boolean),
    )
    system_tags = [
        {"workspace_id": None, "category": "framework", "key": "soc2", "label": "SOC 2", "is_system": True},
        {"workspace_id": None, "category": "framework", "key": "iso27001", "label": "ISO 27001", "is_system": True},
        {"workspace_id": None, "category": "framework", "key": "nist", "label": "NIST", "is_system": True},
        {"workspace_id": None, "category": "framework", "key": "hipaa", "label": "HIPAA", "is_system": True},
        {"workspace_id": None, "category": "framework", "key": "hitrust", "label": "HITRUST", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "access_control", "label": "Access Control", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "encryption", "label": "Encryption", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "logging", "label": "Logging", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "incident_response", "label": "Incident Response", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "vendor_management", "label": "Vendor Management", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "data_protection", "label": "Data Protection", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "network_security", "label": "Network Security", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "change_management", "label": "Change Management", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "business_continuity", "label": "Business Continuity", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "physical_security", "label": "Physical Security", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "hr_security", "label": "HR Security", "is_system": True},
        {"workspace_id": None, "category": "topic", "key": "risk_management", "label": "Risk Management", "is_system": True},
        {"workspace_id": None, "category": "document_type", "key": "policy", "label": "Policy", "is_system": True},
        {"workspace_id": None, "category": "document_type", "key": "procedure", "label": "Procedure", "is_system": True},
        {"workspace_id": None, "category": "document_type", "key": "report", "label": "Report", "is_system": True},
        {"workspace_id": None, "category": "document_type", "key": "screenshot", "label": "Screenshot", "is_system": True},
        {"workspace_id": None, "category": "document_type", "key": "training_record", "label": "Training Record", "is_system": True},
        {"workspace_id": None, "category": "document_type", "key": "certificate", "label": "Certificate", "is_system": True},
    ]
    op.bulk_insert(tags_table, system_tags)


def downgrade() -> None:
    op.drop_table("document_tags")
    op.drop_table("tags")
