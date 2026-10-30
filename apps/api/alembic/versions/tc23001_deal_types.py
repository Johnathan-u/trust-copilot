"""Typed deal amount, currency, close dates, stage, and room.

deal_value_arr moves from double precision to numeric(18,2). A stored float is
kept only when it is exactly the float8 image of round(value, 2). Every other
non-null amount is copied to tc23001_deal_amount_hold as text, with a reason,
and the column is set null before the type change. Nothing is rounded into a
different value.

expected_close_date is backfilled from close_date::date. That is the date part
of the existing naive UTC timestamp. actual_close_date, currency, room_id, and
linked_document_ids start null. They are not invented for old rows.

Downgrade archives exact typed values before projecting into the old schema.
Re-upgrade restores unchanged projections for the same row/workspace/creation
identity. Old-version edits win. Invalid references remain unset, and conflicts
or unmatched identities keep their archive for explicit recovery. Quarantined
legacy float text is retained separately and never overwrites a later correction.

down_revision is the single alembic head on master when this file is
parented. Re-parent by changing that one assignment. The revision id is
17 characters.

Revision ID: tc23001_deal_types
"""

from alembic import op
import sqlalchemy as sa

revision = "tc23001_deal_types"
down_revision = "tc07002_session_key_id"
branch_labels = None
depends_on = None

_HOLD = "tc23001_deal_amount_hold"
_ARCHIVE = "tc23001_deal_state_archive"
_REASON = "float value is not exactly representable as numeric(18,2)"
# CASE avoids casting non-finite floats into numeric(18,2).
_UNSAFE_AMOUNT = """deal_value_arr IS NOT NULL AND CASE
    WHEN deal_value_arr::text IN ('NaN', 'Infinity', '-Infinity') THEN true
    ELSE abs(round(deal_value_arr::numeric, 2)) > 9999999999999999.99
        OR round(deal_value_arr::numeric, 2)::double precision
            IS DISTINCT FROM deal_value_arr
    END"""
_STAGES = (
    "prospect",
    "discovery",
    "evaluation",
    "negotiation",
    "closed_won",
    "closed_lost",
)


def _archives() -> None:
    # These tables deliberately survive downgrade. No foreign keys: deleting or
    # moving a live row must not erase its only exact recovery copy.
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_HOLD} (
            id serial PRIMARY KEY, deal_id integer NOT NULL,
            workspace_id integer NOT NULL, original_text text NOT NULL,
            reason text NOT NULL, row_created_at timestamp, row_updated_at timestamp
        )
    """)
    )
    # Also safe when downgrading a database upgraded by the original PR revision.
    op.execute(sa.text(f"ALTER TABLE {_HOLD} ADD COLUMN IF NOT EXISTS row_created_at timestamp"))
    op.execute(sa.text(f"ALTER TABLE {_HOLD} ADD COLUMN IF NOT EXISTS row_updated_at timestamp"))
    op.execute(
        sa.text(f"""
        CREATE TABLE IF NOT EXISTS {_ARCHIVE} (
            archive_id bigserial PRIMARY KEY, deal_id integer NOT NULL,
            workspace_id integer NOT NULL, row_created_at timestamp NOT NULL,
            amount_text text, currency varchar(3), expected_close_date date,
            actual_close_date date, linked_document_ids text, room_id integer,
            close_date timestamp, rollback_amount_text text, restore_issue text
        )
    """)
    )


def upgrade() -> None:
    _archives()
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
    op.execute(
        sa.text(f"""
        CREATE TEMP TABLE tc23001_restore ON COMMIT DROP AS
        SELECT DISTINCT ON (a.deal_id) a.*,
            d.deal_value_arr::text IS NOT DISTINCT FROM a.rollback_amount_text AS amount_matches,
            d.close_date IS NOT DISTINCT FROM a.close_date AS close_matches
        FROM {_ARCHIVE} a JOIN deals d ON d.id = a.deal_id
            AND d.workspace_id = a.workspace_id AND d.created_at = a.row_created_at
        ORDER BY a.deal_id, a.archive_id DESC
    """)
    )
    # Even the float projection of the numeric maximum can exceed numeric(18,2).
    # Keep unchanged projections out of float conversion; restore exact text below.
    op.execute(
        sa.text("""
        UPDATE deals d SET deal_value_arr = NULL FROM tc23001_restore a
        WHERE d.id = a.deal_id AND a.amount_matches
    """)
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_HOLD} (
                deal_id, workspace_id, original_text, reason, row_created_at, row_updated_at
            )
            SELECT id,
                   workspace_id,
                   deal_value_arr::text,
                   '{_REASON}', created_at, updated_at
            FROM deals d
            WHERE {_UNSAFE_AMOUNT}
              AND NOT EXISTS (
                  SELECT 1 FROM {_HOLD} h WHERE h.deal_id = d.id
                    AND h.workspace_id = d.workspace_id
                    AND h.row_created_at = d.created_at
                    AND h.row_updated_at = d.updated_at
                    AND h.original_text = d.deal_value_arr::text
              )
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE deals
            SET deal_value_arr = NULL
            WHERE {_UNSAFE_AMOUNT}
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
    _restore_archives()
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


def _restore_archives() -> None:
    op.execute(
        sa.text(f"""
        UPDATE {_ARCHIVE} a SET restore_issue = 'row_missing_or_identity_changed'
        WHERE NOT EXISTS (
            SELECT 1 FROM deals d WHERE d.id = a.deal_id
              AND d.workspace_id = a.workspace_id AND d.created_at = a.row_created_at
        );
        DO $$
        DECLARE
            snapshot record;
            docs jsonb;
            docs_valid boolean;
            room_valid boolean;
            issues text[];
        BEGIN
            FOR snapshot IN SELECT * FROM tc23001_restore LOOP
                issues := ARRAY[]::text[];
                IF NOT snapshot.amount_matches THEN
                    issues := array_append(issues, 'rollback_amount_changed');
                END IF;
                IF NOT snapshot.close_matches THEN
                    issues := array_append(issues, 'rollback_close_date_changed');
                END IF;
                docs_valid := true;
                IF snapshot.linked_document_ids IS NOT NULL THEN
                    BEGIN
                        docs := snapshot.linked_document_ids::jsonb;
                        docs_valid := jsonb_typeof(docs) = 'array';
                        IF docs_valid THEN
                            SELECT NOT EXISTS (
                                SELECT 1 FROM jsonb_array_elements(docs) AS entries(entry)
                                WHERE jsonb_typeof(entry) <> 'number'
                                   OR entry::text !~ '^[1-9][0-9]*$'
                                   OR NOT EXISTS (
                                       SELECT 1 FROM documents d
                                       WHERE d.id::text = entry::text
                                         AND d.workspace_id = snapshot.workspace_id
                                         AND d.deleted_at IS NULL
                                   )
                            ) INTO docs_valid;
                        END IF;
                    EXCEPTION WHEN invalid_text_representation THEN
                        docs_valid := false;
                    END;
                END IF;
                IF NOT docs_valid THEN
                    issues := array_append(issues, 'invalid_document_refs');
                END IF;
                room_valid := snapshot.room_id IS NULL OR EXISTS (
                    SELECT 1 FROM shareable_spaces s WHERE s.id = snapshot.room_id
                      AND s.workspace_id = snapshot.workspace_id
                );
                IF NOT room_valid THEN
                    issues := array_append(issues, 'invalid_room_reference');
                END IF;
                UPDATE deals SET
                    deal_value_arr = CASE WHEN snapshot.amount_matches
                        THEN snapshot.amount_text::numeric(18,2) ELSE deal_value_arr END,
                    currency = snapshot.currency,
                    expected_close_date = CASE WHEN snapshot.close_matches
                        THEN snapshot.expected_close_date ELSE expected_close_date END,
                    actual_close_date = snapshot.actual_close_date,
                    linked_document_ids = CASE WHEN docs_valid
                        THEN snapshot.linked_document_ids ELSE NULL END,
                    room_id = CASE WHEN room_valid THEN snapshot.room_id ELSE NULL END
                WHERE id = snapshot.deal_id AND workspace_id = snapshot.workspace_id
                  AND created_at = snapshot.row_created_at;
                IF cardinality(issues) = 0 THEN
                    DELETE FROM {_ARCHIVE} WHERE archive_id = snapshot.archive_id;
                ELSE
                    UPDATE {_ARCHIVE} SET restore_issue = array_to_string(issues, ',')
                    WHERE archive_id = snapshot.archive_id;
                END IF;
            END LOOP;
        END $$;
    """)
    )


def downgrade() -> None:
    _archives()
    # Snapshot and projection must observe the same rows even with active writers.
    op.execute(sa.text("LOCK TABLE deals IN ACCESS EXCLUSIVE MODE"))
    op.execute(
        sa.text(f"""
        CREATE TEMP TABLE tc23001_saved (archive_id bigint, deal_id integer) ON COMMIT DROP;
        WITH saved AS (
            INSERT INTO {_ARCHIVE} (
                deal_id, workspace_id, row_created_at, amount_text, currency,
                expected_close_date, actual_close_date, linked_document_ids, room_id, close_date
            )
            SELECT id, workspace_id, created_at, deal_value_arr::text, currency,
                   expected_close_date, actual_close_date, linked_document_ids, room_id, close_date
            FROM deals
            RETURNING archive_id, deal_id
        ) INSERT INTO tc23001_saved SELECT * FROM saved
    """)
    )
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
            WHERE d.id = h.deal_id AND d.workspace_id = h.workspace_id
              AND d.created_at = h.row_created_at AND d.updated_at = h.row_updated_at
              AND d.deal_value_arr IS NULL
            """
        )
    )
    op.execute(
        sa.text(f"""
        UPDATE {_ARCHIVE} a SET rollback_amount_text = d.deal_value_arr::text
        FROM deals d, tc23001_saved s
        WHERE a.archive_id = s.archive_id AND d.id = s.deal_id
    """)
    )
    op.drop_constraint("fk_deals_room_id_shareable_spaces", "deals", type_="foreignkey")
    op.drop_column("deals", "room_id")
    op.drop_column("deals", "linked_document_ids")
    op.drop_column("deals", "actual_close_date")
    op.drop_column("deals", "expected_close_date")
    op.drop_column("deals", "currency")
