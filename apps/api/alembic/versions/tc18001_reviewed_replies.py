"""Nullable reviewed-reply provenance and bounded intake, with lossless rollback.

Downgrade moves the added values into hold tables attached to the original rows.
Upgrade restores them without inventing legacy approval. If an old application edits
body text or its request's recipient, subject or workspace while downgraded,
the held approval is retained but is not restored. The reply needs fresh review.
"""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "tc18001_reviewed_replies"
down_revision = "tc10001_job_leases"
branch_labels = None
depends_on = None

NOTE = "trust_request_notes"
NOTE_HOLD = "tc18001_reply_hold"
REQ_HOLD = "tc18001_intake_hold"


def review_hash(row):
    """Bind held review to the immutable text and its delivery/tenant context."""
    context = {
        name: row[name]
        for name in (
            "body",
            "trust_request_id",
            "workspace_id",
            "requester_email",
            "subject",
            "note_type",
        )
    }
    return hashlib.sha256(
        json.dumps(context, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def columns():
    return [
        sa.Column("body_revision", sa.Integer(), nullable=True),
        sa.Column("approved_revision", sa.Integer(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_body_hash", sa.String(64), nullable=True),
        sa.Column("delivery_status", sa.String(24), nullable=True),
        sa.Column("delivery_attempts", sa.Integer(), nullable=True),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_error", sa.String(128), nullable=True),
    ]


CHECKS = {
    "ck_trust_reply_body_revision": "body_revision IS NULL OR (body_revision >= 1 AND body_revision <= 1000000 AND char_length(body) <= 10000)",
    "ck_trust_reply_approved_revision": "approved_revision IS NULL OR (body_revision IS NOT NULL AND approved_revision >= 1 AND approved_revision = body_revision)",
    "ck_trust_reply_delivery_status": "delivery_status IS NULL OR delivery_status IN ('draft','approved','sending','accepted','uncertain','unavailable')",
    "ck_trust_reply_delivery_attempts": "delivery_attempts IS NULL OR (delivery_attempts >= 0 AND delivery_attempts <= 10)",
}


def upgrade():
    bind = op.get_bind()
    for column in columns():
        op.add_column(NOTE, column)
    op.add_column("trust_requests", sa.Column("intake_version", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_trust_reply_approved_by", NOTE, "users", ["approved_by"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_trust_request_notes_approved_by", NOTE, ["approved_by"])
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, NOTE, condition)
    op.create_check_constraint(
        "ck_trust_request_intake_bound",
        "trust_requests",
        "intake_version IS NULL OR (intake_version = 1 AND char_length(message) BETWEEN 1 AND 10000)",
    )
    tables = sa.inspect(bind).get_table_names()
    names = [c.name for c in columns()]
    if NOTE_HOLD in tables:
        held = bind.execute(
            sa.text(
                f"SELECT h.*, n.body, n.trust_request_id, n.note_type, r.workspace_id, r.requester_email, r.subject FROM {NOTE_HOLD} h JOIN {NOTE} n ON n.id=h.note_id JOIN trust_requests r ON r.id=n.trust_request_id"
            )
        ).mappings()
        for row in held:
            values = {name: row[name] for name in names}
            same_context = review_hash(row) == row["review_hash"]
            if not same_context:
                # Old binaries cannot update the hidden revision. Re-review the changed text.
                values.update(
                    body_revision=None,
                    approved_revision=None,
                    approved_by=None,
                    approved_at=None,
                    approved_body_hash=None,
                    delivery_status=None,
                    delivery_attempts=None,
                    delivery_started_at=None,
                    delivery_accepted_at=None,
                    delivery_error=None,
                )
            if (
                values["approved_by"] is not None
                and not bind.execute(
                    sa.text("SELECT id FROM users WHERE id=:id"), {"id": values["approved_by"]}
                ).first()
            ):
                values["approved_by"] = None
            bind.execute(
                sa.text(
                    f"UPDATE {NOTE} SET "
                    + ", ".join(f"{name}=:{name}" for name in names)
                    + " WHERE id=:id"
                ),
                {**values, "id": row["note_id"]},
            )
    if REQ_HOLD in tables:
        # Invalid legacy edits stay unversioned instead of failing upgrade or inventing a valid intake.
        bind.execute(
            sa.text(
                f"UPDATE trust_requests r SET intake_version=h.intake_version FROM {REQ_HOLD} h WHERE r.id=h.request_id AND char_length(r.message) BETWEEN 1 AND 10000"
            )
        )


def downgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if NOTE_HOLD not in tables:
        op.create_table(
            NOTE_HOLD,
            sa.Column(
                "note_id",
                sa.Integer(),
                sa.ForeignKey(f"{NOTE}.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("review_hash", sa.String(64), nullable=False),
            *columns(),
        )
    if REQ_HOLD not in tables:
        op.create_table(
            REQ_HOLD,
            sa.Column(
                "request_id",
                sa.Integer(),
                sa.ForeignKey("trust_requests.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("intake_version", sa.Integer(), nullable=True),
        )
    names = [c.name for c in columns()]
    for row in bind.execute(
        sa.text(
            f"SELECT n.id, n.body, n.trust_request_id, n.note_type, r.workspace_id, r.requester_email, r.subject, {', '.join('n.'+name for name in names)} FROM {NOTE} n JOIN trust_requests r ON r.id=n.trust_request_id"
        )
    ).mappings():
        values = {name: row[name] for name in names}
        if all(value is None for value in values.values()):
            continue
        bind.execute(
            sa.text(
                f"INSERT INTO {NOTE_HOLD} (note_id,review_hash,{','.join(names)}) VALUES (:id,:review_hash,{','.join(':'+n for n in names)}) ON CONFLICT (note_id) DO UPDATE SET review_hash=EXCLUDED.review_hash,"
                + ",".join(f"{n}=EXCLUDED.{n}" for n in names)
            ),
            {
                **values,
                "id": row["id"],
                "review_hash": review_hash(row),
            },
        )
    bind.execute(
        sa.text(
            f"INSERT INTO {REQ_HOLD} (request_id,intake_version) SELECT id,intake_version FROM trust_requests WHERE intake_version IS NOT NULL ON CONFLICT (request_id) DO UPDATE SET intake_version=EXCLUDED.intake_version"
        )
    )
    op.drop_constraint("ck_trust_request_intake_bound", "trust_requests", type_="check")
    op.drop_column("trust_requests", "intake_version")
    for name in CHECKS:
        op.drop_constraint(name, NOTE, type_="check")
    op.drop_index("ix_trust_request_notes_approved_by", table_name=NOTE)
    op.drop_constraint("fk_trust_reply_approved_by", NOTE, type_="foreignkey")
    for name in reversed(names):
        op.drop_column(NOTE, name)
