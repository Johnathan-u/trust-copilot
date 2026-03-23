"""Registry list metadata across core modules.

Revision ID: 038
Revises: 037
"""

import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def _backfill_table(conn, table_name: str, prefix: str) -> None:
    rows = conn.execute(
        sa.text(
            f"""
            SELECT id, created_at, updated_at, frameworks_json, subject_areas_json
            FROM {table_name}
            ORDER BY id
            """
        )
    ).mappings().all()
    for row in rows:
        created_at = row["created_at"] or row["updated_at"] or datetime.now(timezone.utc)
        frameworks = row["frameworks_json"] or json.dumps(["Other"])
        subjects = row["subject_areas_json"] or json.dumps(["Other"])
        conn.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET
                    display_id = :display_id,
                    created_at = :created_at,
                    frameworks_json = :frameworks_json,
                    subject_areas_json = :subject_areas_json
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "display_id": f"{prefix}-{int(row['id']):06d}",
                "created_at": created_at,
                "frameworks_json": frameworks,
                "subject_areas_json": subjects,
            },
        )


def _backfill_documents_from_tags(conn) -> None:
    doc_rows = conn.execute(
        sa.text(
            """
            SELECT dt.document_id, t.category, t.label
            FROM document_tags dt
            JOIN tags t ON t.id = dt.tag_id
            WHERE t.category IN ('framework', 'topic')
            """
        )
    ).mappings().all()
    by_doc: dict[int, dict[str, list[str]]] = {}
    for row in doc_rows:
        doc_id = int(row["document_id"])
        bucket = by_doc.setdefault(doc_id, {"framework": [], "topic": []})
        label = str(row["label"]).strip()
        if label and label not in bucket[row["category"]]:
            bucket[row["category"]].append(label)

    for doc_id, values in by_doc.items():
        frameworks = values["framework"] or ["Other"]
        subjects = values["topic"] or ["Other"]
        conn.execute(
            sa.text(
                """
                UPDATE documents
                SET frameworks_json = :frameworks_json, subject_areas_json = :subject_areas_json
                WHERE id = :id
                """
            ),
            {
                "id": doc_id,
                "frameworks_json": json.dumps(frameworks),
                "subject_areas_json": json.dumps(subjects),
            },
        )


def upgrade() -> None:
    op.add_column("documents", sa.Column("display_id", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("frameworks_json", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("subject_areas_json", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("documents", sa.Column("deleted_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_documents_deleted_by_users", "documents", "users", ["deleted_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_documents_display_id", "documents", ["display_id"], unique=True)
    op.create_index("ix_documents_created_at", "documents", ["created_at"], unique=False)
    op.create_index("ix_documents_status", "documents", ["status"], unique=False)
    op.create_index("ix_documents_deleted_at", "documents", ["deleted_at"], unique=False)

    op.add_column("trust_requests", sa.Column("display_id", sa.String(length=32), nullable=True))
    op.add_column("trust_requests", sa.Column("frameworks_json", sa.Text(), nullable=True))
    op.add_column("trust_requests", sa.Column("subject_areas_json", sa.Text(), nullable=True))
    op.add_column("trust_requests", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("trust_requests", sa.Column("deleted_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_trust_requests_deleted_by_users", "trust_requests", "users", ["deleted_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_trust_requests_display_id", "trust_requests", ["display_id"], unique=True)
    op.create_index("ix_trust_requests_created_at", "trust_requests", ["created_at"], unique=False)
    # ix_trust_requests_status already exists from 008; use if_not_exists for idempotency
    op.create_index("ix_trust_requests_status", "trust_requests", ["status"], unique=False, if_not_exists=True)
    op.create_index("ix_trust_requests_deleted_at", "trust_requests", ["deleted_at"], unique=False)

    op.add_column("questionnaires", sa.Column("display_id", sa.String(length=32), nullable=True))
    op.add_column("questionnaires", sa.Column("frameworks_json", sa.Text(), nullable=True))
    op.add_column("questionnaires", sa.Column("subject_areas_json", sa.Text(), nullable=True))
    op.add_column("questionnaires", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("questionnaires", sa.Column("deleted_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_questionnaires_deleted_by_users", "questionnaires", "users", ["deleted_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_questionnaires_display_id", "questionnaires", ["display_id"], unique=True)
    op.create_index("ix_questionnaires_created_at", "questionnaires", ["created_at"], unique=False)
    op.create_index("ix_questionnaires_status", "questionnaires", ["status"], unique=False)
    op.create_index("ix_questionnaires_deleted_at", "questionnaires", ["deleted_at"], unique=False)

    conn = op.get_bind()
    _backfill_table(conn, "documents", "DOC")
    _backfill_table(conn, "trust_requests", "TR")
    _backfill_table(conn, "questionnaires", "QNR")
    _backfill_documents_from_tags(conn)


def downgrade() -> None:
    op.drop_index("ix_questionnaires_deleted_at", table_name="questionnaires")
    op.drop_index("ix_questionnaires_status", table_name="questionnaires")
    op.drop_index("ix_questionnaires_created_at", table_name="questionnaires")
    op.drop_index("ix_questionnaires_display_id", table_name="questionnaires")
    op.drop_constraint("fk_questionnaires_deleted_by_users", "questionnaires", type_="foreignkey")
    op.drop_column("questionnaires", "deleted_by")
    op.drop_column("questionnaires", "deleted_at")
    op.drop_column("questionnaires", "subject_areas_json")
    op.drop_column("questionnaires", "frameworks_json")
    op.drop_column("questionnaires", "display_id")

    op.drop_index("ix_trust_requests_deleted_at", table_name="trust_requests")
    # ix_trust_requests_status was created by 008, not 038; do not drop it
    op.drop_index("ix_trust_requests_created_at", table_name="trust_requests")
    op.drop_index("ix_trust_requests_display_id", table_name="trust_requests")
    op.drop_constraint("fk_trust_requests_deleted_by_users", "trust_requests", type_="foreignkey")
    op.drop_column("trust_requests", "deleted_by")
    op.drop_column("trust_requests", "deleted_at")
    op.drop_column("trust_requests", "subject_areas_json")
    op.drop_column("trust_requests", "frameworks_json")
    op.drop_column("trust_requests", "display_id")

    op.drop_index("ix_documents_deleted_at", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_display_id", table_name="documents")
    op.drop_constraint("fk_documents_deleted_by_users", "documents", type_="foreignkey")
    op.drop_column("documents", "deleted_by")
    op.drop_column("documents", "deleted_at")
    op.drop_column("documents", "subject_areas_json")
    op.drop_column("documents", "frameworks_json")
    op.drop_column("documents", "display_id")
