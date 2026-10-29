"""Typed deal amount, currency, close dates, stage, and room.

deal_value_arr moves from double precision to numeric(18,2). A stored float is
kept only when it is exactly the float8 image of round(value, 2). Every other
non-null amount is copied to tc23001_deal_amount_hold as text, with a reason,
and the column is set null before the type change. Nothing is rounded into a
different value.

expected_close_date is backfilled from close_date::date. That is the date part
of the existing naive UTC timestamp. actual_close_date, currency, room_id, and
linked_document_ids start null. They are not invented for old rows.

Downgrade restores held float text, casts exact numeric values back to
double precision, and drops the columns this revision added. Re-upgrade
re-holds the same float text and does not invent currency, room, document, or
actual-close values that were never stored on the old row. close_date is left
in place, so the expected-close backfill can be derived again.

Parent is the single alembic head on origin/master a2458c9 (tc10001_job_leases).
tc21006_gap_evaluation already has descendants, so parenting there would add a
second head. The revision id is 17 characters.

Revision ID: tc23001_deal_types
Revises: tc10001_job_leases
"""

from alembic import op
import sqlalchemy as sa

revision = "tc23001_deal_types"
down_revision = "tc10001_job_leases"
branch_labels = None
depends_on = None

_HOLD = "tc23001_deal_amount_hold"
_REASON = "float value is not exactly representable as numeric(18,2)"
_STAGES = (
    "prospect",
    "discovery",
    "evaluation",
    "negotiation",
    "closed_won",
    "closed_lost",
)


def upgrade() -> None:
    op.add_column("deals", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column("deals", sa.Column("expected_close_date", sa.Date(), nullable=True))
    op.add_column("deals", sa.Column("actual_close_date", sa.Date(), nullable=True))
    op.add_column("deals", sa.Column("linked_document_ids", sa.Text(), nullable=True))
    op.add_column(
        "deals",
        sa.Column("room_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_deals_room_id_shareable_spaces",
        "deals",
        "shareable_spaces",
        ["room_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        _HOLD,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_HOLD} (deal_id, workspace_id, original_text, reason)
            SELECT id,
                   workspace_id,
                   deal_value_arr::text,
                   '{_REASON}'
            FROM deals
            WHERE deal_value_arr IS NOT NULL
              AND round(deal_value_arr::numeric, 2)::double precision
                  IS DISTINCT FROM deal_value_arr
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE deals
            SET deal_value_arr = NULL
            WHERE id IN (SELECT deal_id FROM {_HOLD})
            """
        )
    )
    op.execute(
        sa.text(
            """
            ALTER TABLE deals
            ALTER COLUMN deal_value_arr TYPE numeric(18, 2)
            USING CASE
                WHEN deal_value_arr IS NULL THEN NULL
                ELSE round(deal_value_arr::numeric, 2)
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE deals
            SET expected_close_date = close_date::date
            WHERE close_date IS NOT NULL
              AND expected_close_date IS NULL
            """
        )
    )
    stage_list = ", ".join("'" + stage + "'" for stage in _STAGES)
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE bad text;
            BEGIN
                SELECT string_agg(id::text || ':' || stage, ', ' ORDER BY id)
                  INTO bad
                FROM deals
                WHERE stage NOT IN ({stage_list});
                IF bad IS NOT NULL THEN
                    RAISE EXCEPTION
                        'deals.stage values are outside the typed enum: %', bad;
                END IF;
            END $$;
            """
        )
    )
    op.create_check_constraint(
        "ck_deals_stage",
        "deals",
        f"stage IN ({stage_list})",
    )
    op.create_check_constraint(
        "ck_deals_currency",
        "deals",
        "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_deals_currency", "deals", type_="check")
    op.drop_constraint("ck_deals_stage", "deals", type_="check")
    op.execute(
        sa.text(
            """
            ALTER TABLE deals
            ALTER COLUMN deal_value_arr TYPE double precision
            USING deal_value_arr::double precision
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE deals AS d
            SET deal_value_arr = h.original_text::double precision
            FROM {_HOLD} AS h
            WHERE d.id = h.deal_id
            """
        )
    )
    op.drop_constraint("fk_deals_room_id_shareable_spaces", "deals", type_="foreignkey")
    op.drop_column("deals", "room_id")
    op.drop_column("deals", "linked_document_ids")
    op.drop_column("deals", "actual_close_date")
    op.drop_column("deals", "expected_close_date")
    op.drop_column("deals", "currency")
    op.drop_table(_HOLD)
