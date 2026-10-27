"""TC-21-002: canonical control pairing columns.

Additive only. Existing control rows and their status values are not rewritten.
content_version is a null slot until TC-01-007; this revision does not store a
licensed version and does not insert framework text.

Revision ID: tc21002_control_contract
Revises: tc24001_stripe_webhook_events
"""

from alembic import op
import sqlalchemy as sa

revision = "tc21002_control_contract"
down_revision = "tc24001_stripe_webhook_events"
branch_labels = None
depends_on = None

# Frozen. This module must not import the application package.
_CONTROLS = "controls"
_WORKSPACE_CONTROLS = "workspace_controls"
_EVIDENCE = "control_evidence"
_EVENTS = "control_contract_events"
_KEY_LEN = 160
_VERSION_LEN = 32
_TEAM_LEN = 128
_LIFECYCLE_LEN = 32
_REQUEST_LEN = 64
_OUTCOME_LEN = 32


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in sa.inspect(bind).get_columns(table)}


def _has_constraint(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
        {"name": name},
    ).first()
    return row is not None


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _column_names(table):
        op.add_column(table, column)


def _add_fk(name: str, sql: str) -> None:
    if not _has_constraint(name):
        op.execute(sa.text(sql))


def upgrade() -> None:
    _add_column(_CONTROLS, sa.Column("canonical_key", sa.String(_KEY_LEN), nullable=True))
    _add_column(_CONTROLS, sa.Column("content_version", sa.String(_VERSION_LEN), nullable=True))
    _add_column(_CONTROLS, sa.Column("owner_user_id", sa.Integer(), nullable=True))
    _add_column(_CONTROLS, sa.Column("owner_team", sa.String(_TEAM_LEN), nullable=True))
    _add_column(_CONTROLS, sa.Column("lifecycle", sa.String(_LIFECYCLE_LEN), nullable=True))
    _add_column(_CONTROLS, sa.Column("workspace_control_id", sa.Integer(), nullable=True))
    _add_column(_WORKSPACE_CONTROLS, sa.Column("canonical_key", sa.String(_KEY_LEN), nullable=True))
    _add_column(
        _WORKSPACE_CONTROLS, sa.Column("content_version", sa.String(_VERSION_LEN), nullable=True)
    )
    _add_column(
        _WORKSPACE_CONTROLS, sa.Column("lifecycle", sa.String(_LIFECYCLE_LEN), nullable=True)
    )
    _add_column(_EVIDENCE, sa.Column("evidence_item_id", sa.Integer(), nullable=True))

    _add_fk(
        "fk_controls_owner_user_id",
        "ALTER TABLE controls ADD CONSTRAINT fk_controls_owner_user_id "
        "FOREIGN KEY (owner_user_id) REFERENCES users (id) ON DELETE SET NULL",
    )
    _add_fk(
        "fk_controls_workspace_control_id",
        "ALTER TABLE controls ADD CONSTRAINT fk_controls_workspace_control_id "
        "FOREIGN KEY (workspace_control_id) REFERENCES workspace_controls (id) ON DELETE SET NULL",
    )
    _add_fk(
        "fk_control_evidence_evidence_item_id",
        "ALTER TABLE control_evidence ADD CONSTRAINT fk_control_evidence_evidence_item_id "
        "FOREIGN KEY (evidence_item_id) REFERENCES evidence_items (id) ON DELETE SET NULL",
    )

    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _EVENTS not in tables:
        op.create_table(
            _EVENTS,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("legacy_control_id", sa.Integer(), nullable=True),
            sa.Column("workspace_control_id", sa.Integer(), nullable=True),
            sa.Column("canonical_key", sa.String(_KEY_LEN), nullable=False),
            sa.Column("lifecycle", sa.String(_LIFECYCLE_LEN), nullable=False),
            sa.Column("request_id", sa.String(_REQUEST_LEN), nullable=True),
            sa.Column("outcome", sa.String(_OUTCOME_LEN), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["legacy_control_id"], ["controls.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["workspace_control_id"],
                ["workspace_controls.id"],
                ondelete="SET NULL",
            ),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_control_contract_events_workspace_id "
        "ON control_contract_events (workspace_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_controls_canonical_key ON controls (canonical_key)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workspace_controls_canonical_key "
        "ON workspace_controls (canonical_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_control_evidence_evidence_item_id "
        "ON control_evidence (evidence_item_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_controls_owner_user_id ON controls (owner_user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_controls_workspace_control_id "
        "ON controls (workspace_control_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_control_contract_events_legacy_control_id "
        "ON control_contract_events (legacy_control_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_control_contract_events_workspace_control_id "
        "ON control_contract_events (workspace_control_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_controls_owner_user_id")
    op.execute("DROP INDEX IF EXISTS ix_controls_workspace_control_id")
    op.execute("DROP INDEX IF EXISTS ix_control_contract_events_legacy_control_id")
    op.execute("DROP INDEX IF EXISTS ix_control_contract_events_workspace_control_id")
    op.execute("DROP INDEX IF EXISTS ix_control_evidence_evidence_item_id")
    op.execute("DROP INDEX IF EXISTS ix_workspace_controls_canonical_key")
    op.execute("DROP INDEX IF EXISTS ix_controls_canonical_key")
    op.execute("DROP INDEX IF EXISTS ix_control_contract_events_workspace_id")
    bind = op.get_bind()
    if _EVENTS in set(sa.inspect(bind).get_table_names()):
        op.drop_table(_EVENTS)
    for table, constraint in (
        (_EVIDENCE, "fk_control_evidence_evidence_item_id"),
        (_CONTROLS, "fk_controls_workspace_control_id"),
        (_CONTROLS, "fk_controls_owner_user_id"),
    ):
        if _has_constraint(constraint):
            op.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"))
    for table, column in (
        (_EVIDENCE, "evidence_item_id"),
        (_WORKSPACE_CONTROLS, "lifecycle"),
        (_WORKSPACE_CONTROLS, "content_version"),
        (_WORKSPACE_CONTROLS, "canonical_key"),
        (_CONTROLS, "workspace_control_id"),
        (_CONTROLS, "lifecycle"),
        (_CONTROLS, "owner_team"),
        (_CONTROLS, "owner_user_id"),
        (_CONTROLS, "content_version"),
        (_CONTROLS, "canonical_key"),
    ):
        if column in _column_names(table):
            op.drop_column(table, column)
