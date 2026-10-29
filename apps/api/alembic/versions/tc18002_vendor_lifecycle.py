"""Durable vendor request grants, delivery and final responses.

Nullable additions preserve legacy provenance. Downgrade parks populated values
in a bounded hold table; upgrade restores only the matching original row.
"""

from alembic import op
import sqlalchemy as sa

revision = "tc18002_vendor_lifecycle"
down_revision = "tc10001_job_leases"
branch_labels = None
depends_on = None

TABLE = "vendor_requests"
HOLD = "tc18002_vendor_hold"
SPECS = (
    ("link_token_hash", sa.String(64)),
    ("expires_at", sa.DateTime(timezone=True)),
    ("revoked_at", sa.DateTime(timezone=True)),
    ("delivery_status", sa.String(16)),
    ("last_delivery_at", sa.DateTime(timezone=True)),
    ("last_delivery_error", sa.String(128)),
    ("submitted_at", sa.DateTime(timezone=True)),
    ("response_payload", sa.String(20000)),
    ("response_digest", sa.String(64)),
)
CHECKS = {
    "ck_vendor_delivery_status": "delivery_status IS NULL OR delivery_status IN ('not_sent','sending','accepted','uncertain','unavailable')",
    "ck_vendor_submission_fields": "(submitted_at IS NULL AND response_payload IS NULL AND response_digest IS NULL) OR (submitted_at IS NOT NULL AND response_payload IS NOT NULL AND response_digest IS NOT NULL)",
}
INDEX = "ix_vendor_requests_link_token_hash"


def fingerprint(alias):
    columns = ", ".join(
        f"{alias}.{name}"
        for name in (
            "workspace_id",
            "vendor_email",
            "questionnaire_id",
            "message",
            "status",
            "link_token",
            "created_at",
        )
    )
    return f"md5(jsonb_build_array({columns})::text)"


def upgrade():
    for name, type_ in SPECS:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True))
    op.create_index(INDEX, TABLE, ["link_token_hash"], unique=True)
    for name, sql in CHECKS.items():
        op.create_check_constraint(name, TABLE, sql)
    # IF NOT EXISTS also renders correctly in offline migration SQL and on re-upgrade.
    types = ", ".join(
        f"{name} {type_.compile(dialect=op.get_bind().dialect)}" for name, type_ in SPECS
    )
    op.execute(
        sa.text(
            f"CREATE TABLE IF NOT EXISTS {HOLD} (id INTEGER PRIMARY KEY, workspace_id INTEGER NOT NULL, created_at TIMESTAMP, legacy_fingerprint VARCHAR(32) NOT NULL, {types})"
        )
    )
    # An older application may edit base fields while this revision is down.
    # Preserve the hold and refuse restoration to a changed row rather than
    # attaching prior submission/delivery provenance to a different request.
    op.execute(
        sa.text(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM {HOLD} h JOIN {TABLE} r ON r.id=h.id
                     WHERE h.legacy_fingerprint <> {fingerprint('r')}) THEN
            RAISE EXCEPTION 'Vendor request changed while lifecycle schema was downgraded; reconcile preserved lifecycle data before upgrading';
          END IF;
        END $$;
    """)
    )
    assignments = ", ".join(f"{name}=h.{name}" for name, _ in SPECS)
    op.execute(
        sa.text(
            f"UPDATE {TABLE} r SET {assignments} FROM {HOLD} h WHERE r.id=h.id AND r.workspace_id=h.workspace_id AND r.created_at IS NOT DISTINCT FROM h.created_at"
        )
    )
    op.execute(
        sa.text(
            f"DELETE FROM {HOLD} h USING {TABLE} r WHERE r.id=h.id AND r.workspace_id=h.workspace_id AND r.created_at IS NOT DISTINCT FROM h.created_at"
        )
    )


def downgrade():
    names = ", ".join(name for name, _ in SPECS)
    nonnull = " OR ".join(f"{name} IS NOT NULL" for name, _ in SPECS)
    # Repeated down/up cycles refresh the current provenance without losing values.
    assignments = ", ".join(
        f"{name}=EXCLUDED.{name}"
        for name in ("workspace_id", "created_at", "legacy_fingerprint", *(n for n, _ in SPECS))
    )
    op.execute(
        sa.text(
            f"INSERT INTO {HOLD} (id, workspace_id, created_at, legacy_fingerprint, {names}) SELECT id, workspace_id, created_at, {fingerprint(TABLE)}, {names} FROM {TABLE} WHERE {nonnull} ON CONFLICT (id) DO UPDATE SET {assignments}"
        )
    )
    for name in CHECKS:
        op.drop_constraint(name, TABLE, type_="check")
    op.drop_index(INDEX, table_name=TABLE)
    for name, _ in reversed(SPECS):
        op.drop_column(TABLE, name)
