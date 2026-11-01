"""Owner-approved public security claims with proof references.

Creates security_claims: one row per workspace and catalogue key, holding the
latest owner decision (claimed or not), the public statement or value, an
optional proof evidence reference and the decision provenance. Nothing is
backfilled: every workspace starts with no claims, which the public page shows
as "not attested" / "not yet verified", exactly as before.

Downgrade copies every row into tc17003_security_claim_archive (no foreign
keys, so it survives the drop) before dropping the table. Upgrade restores
archived rows whose workspace still exists; a proof or decider reference that
no longer resolves inside the same workspace is restored as NULL, so a
restored claim can never point at another workspace's evidence. Restored
archive rows are removed and an emptied archive is dropped; rows whose
workspace is gone stay in the archive for recovery.

down_revision is the single alembic head on master when this file is
parented. Re-parent by changing that one assignment.

Revision ID: tc17003_security_claims
"""

from alembic import op
import sqlalchemy as sa

revision = "tc17003_security_claims"
down_revision = "tc23001_deal_types"
branch_labels = None
depends_on = None

_ARCHIVE = "tc17003_security_claim_archive"


def upgrade() -> None:
    op.create_table(
        "security_claims",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claim_key", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="not_claimed"),
        sa.Column("statement", sa.String(500), nullable=True),
        sa.Column("value", sa.String(320), nullable=True),
        sa.Column(
            "evidence_item_id",
            sa.Integer(),
            sa.ForeignKey(
                "evidence_items.id", name="fk_security_claims_evidence", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column(
            "decided_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_security_claims_decider", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "claim_key", name="uq_security_claims_workspace_key"),
        sa.CheckConstraint("status IN ('not_claimed','claimed')", name="ck_security_claims_status"),
        sa.CheckConstraint("revision >= 1", name="ck_security_claims_revision"),
        sa.CheckConstraint(
            "status <> 'claimed' OR decided_at IS NOT NULL",
            name="ck_security_claims_claimed_decided",
        ),
    )
    op.create_index("ix_security_claims_workspace_id", "security_claims", ["workspace_id"])
    op.create_index("ix_security_claims_evidence_item_id", "security_claims", ["evidence_item_id"])
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_ARCHIVE):
        op.execute(
            sa.text(f"""
            INSERT INTO security_claims (
                workspace_id, claim_key, status, statement, value, evidence_item_id,
                decided_by_user_id, decided_at, revision, updated_at
            )
            SELECT a.workspace_id, a.claim_key, a.status, a.statement, a.value,
                   CASE WHEN e.id IS NOT NULL THEN a.evidence_item_id END,
                   CASE WHEN m.user_id IS NOT NULL THEN a.decided_by_user_id END,
                   a.decided_at, a.revision, a.updated_at
            FROM {_ARCHIVE} a
            JOIN workspaces w ON w.id = a.workspace_id
            LEFT JOIN evidence_items e
                ON e.id = a.evidence_item_id AND e.workspace_id = a.workspace_id
            LEFT JOIN workspace_members m
                ON m.user_id = a.decided_by_user_id AND m.workspace_id = a.workspace_id
            ON CONFLICT (workspace_id, claim_key) DO NOTHING
            """)
        )
        op.execute(
            sa.text(f"""
            DELETE FROM {_ARCHIVE} a
            USING security_claims c
            WHERE c.workspace_id = a.workspace_id AND c.claim_key = a.claim_key
            """)
        )
        # Fully restored: drop the archive. Unmatched rows keep it for recovery.
        op.execute(
            sa.text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM {_ARCHIVE}) THEN
                    DROP TABLE {_ARCHIVE};
                END IF;
            END $$
            """)
        )


def downgrade() -> None:
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_ARCHIVE} (
            workspace_id integer NOT NULL,
            claim_key varchar(48) NOT NULL,
            status varchar(16) NOT NULL,
            statement varchar(500),
            value varchar(320),
            evidence_item_id integer,
            decided_by_user_id integer,
            decided_at timestamptz,
            revision integer NOT NULL,
            updated_at timestamptz NOT NULL,
            archived_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, claim_key)
        )
        """)
    )
    op.execute(
        sa.text(f"""
        INSERT INTO {_ARCHIVE} (
            workspace_id, claim_key, status, statement, value, evidence_item_id,
            decided_by_user_id, decided_at, revision, updated_at
        )
        SELECT workspace_id, claim_key, status, statement, value, evidence_item_id,
               decided_by_user_id, decided_at, revision, updated_at
        FROM security_claims
        ON CONFLICT (workspace_id, claim_key) DO UPDATE SET
            status = EXCLUDED.status,
            statement = EXCLUDED.statement,
            value = EXCLUDED.value,
            evidence_item_id = EXCLUDED.evidence_item_id,
            decided_by_user_id = EXCLUDED.decided_by_user_id,
            decided_at = EXCLUDED.decided_at,
            revision = EXCLUDED.revision,
            updated_at = EXCLUDED.updated_at,
            archived_at = now()
        """)
    )
    op.drop_index("ix_security_claims_evidence_item_id", table_name="security_claims")
    op.drop_index("ix_security_claims_workspace_id", table_name="security_claims")
    op.drop_table("security_claims")
