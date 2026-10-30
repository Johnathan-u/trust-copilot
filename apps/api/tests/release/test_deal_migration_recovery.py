"""Real PostgreSQL rollback/re-upgrade recovery; no mocked migration execution."""

import json
import uuid

import pytest
from sqlalchemy import text

from app.core.database import engine
from tests.release.test_domain_deals import HOLD, _alembic, _migration_parent

ARCHIVE = "tc23001_deal_state_archive"


def _sql(statement, **params):
    with engine.begin() as connection:
        result = connection.execute(text(statement), params)
        return result.mappings().all() if result.returns_rows else []


@pytest.fixture
def recovery_rows(migrated_db):
    ids = {"deals": [], "documents": [], "shareable_spaces": []}
    try:
        yield ids
    finally:
        _alembic("upgrade", "head")
        for table in (HOLD, ARCHIVE):
            _sql(f"DELETE FROM {table} WHERE deal_id = ANY(:ids)", ids=ids["deals"])
        for table, keys in ids.items():
            _sql(f"DELETE FROM {table} WHERE id = ANY(:ids)", ids=keys)


def _deal(ids, amount="10.00"):
    row = _sql(
        """
        INSERT INTO deals (workspace_id, company_name, deal_value_arr, stage,
                           close_date, notes, created_at, updated_at)
        VALUES (1, :name, :amount, 'prospect', '2026-04-15 12:30:00',
                'before rollback', now(), now()) RETURNING id
    """,
        name=f"Synthetic recovery {uuid.uuid4().hex}",
        amount=amount,
    )[0]
    ids["deals"].append(row["id"])
    return row["id"]


def _refs(ids):
    doc = _sql(
        """
        INSERT INTO documents (workspace_id, filename, storage_key, created_at, updated_at)
        VALUES (1, 'synthetic.txt', :key, now(), now()) RETURNING id
    """,
        key=f"synthetic/recovery-{uuid.uuid4().hex}",
    )[0]["id"]
    room = _sql("""
        INSERT INTO shareable_spaces (workspace_id, name, is_active, created_at, updated_at)
        VALUES (1, 'Synthetic recovery room', true, now(), now()) RETURNING id
    """)[0]["id"]
    ids["documents"].append(doc)
    ids["shareable_spaces"].append(room)
    return doc, room


def _typed_fields(deal_id, doc, room, amount=None):
    _sql(
        """
        UPDATE deals SET currency = 'XTS', expected_close_date = '2027-06-30',
            actual_close_date = '2027-07-01', linked_document_ids = :docs,
            room_id = :room, updated_at = now()
        WHERE id = :id
    """,
        id=deal_id,
        docs=json.dumps([doc]),
        room=room,
    )
    if amount is not None:
        _sql("UPDATE deals SET deal_value_arr = :amount WHERE id = :id", id=deal_id, amount=amount)


def _read(ids):
    return _sql(
        """
        SELECT id, workspace_id, deal_value_arr::text AS amount, currency,
               expected_close_date::text AS expected, actual_close_date::text AS actual,
               linked_document_ids, room_id, close_date::text AS close, notes
        FROM deals WHERE id = ANY(:ids) ORDER BY id
    """,
        ids=ids,
    )


def test_corrected_legacy_and_new_typed_rows_round_trip_exactly(recovery_rows):
    ids = recovery_rows
    doc, room = _refs(ids)
    _alembic("downgrade", _migration_parent())
    legacy = _deal(ids, "0.3333333333333333")
    _alembic("upgrade", "head")
    assert _read([legacy])[0]["amount"] is None
    # A correction must win over the held legacy float, even on downgrade.
    _typed_fields(legacy, doc, room, "50.02")
    for amount in ("90071992547409.91", "9999999999999999.99"):
        new = _deal(ids, amount)
        _typed_fields(new, doc, room)
    before = _read(ids["deals"])
    for _ in range(2):
        _alembic("downgrade", _migration_parent())
        assert (
            _sql("SELECT deal_value_arr::text AS amount FROM deals WHERE id = :id", id=legacy)[0][
                "amount"
            ]
            == "50.02"
        )
        archived = _sql(
            f"SELECT amount_text FROM {ARCHIVE} WHERE deal_id = ANY(:ids)", ids=ids["deals"]
        )
        assert {row["amount_text"] for row in archived} == {
            "50.02",
            "90071992547409.91",
            "9999999999999999.99",
        }
        _alembic("upgrade", "head")
        assert _read(ids["deals"]) == before
        assert _sql(f"SELECT * FROM {ARCHIVE} WHERE deal_id = ANY(:ids)", ids=ids["deals"]) == []
    assert _sql(f"SELECT original_text FROM {HOLD} WHERE deal_id = :id", id=legacy) == [
        {"original_text": "0.3333333333333333"}
    ]


def test_old_version_edits_win_and_exact_snapshot_remains_recoverable(recovery_rows):
    ids = recovery_rows
    doc, room = _refs(ids)
    existing = _deal(ids, "90071992547409.91")
    _typed_fields(existing, doc, room)
    _alembic("downgrade", _migration_parent())
    # Execute real writes in the parent schema, which has no typed columns.
    _sql(
        """
        UPDATE deals SET deal_value_arr = 12.34, close_date = '2028-08-09 13:14:15',
            notes = 'edited by old version', updated_at = now() WHERE id = :id
    """,
        id=existing,
    )
    old_version_new = _deal(ids, "98.76")
    _alembic("upgrade", "head")
    current = _read([existing])[0]
    assert current["amount"] == "12.34"
    assert current["close"] == "2028-08-09 13:14:15"
    assert current["expected"] == "2028-08-09"
    assert current["notes"] == "edited by old version"
    assert current["currency"] == "XTS"
    assert current["actual"] == "2027-07-01"
    assert current["linked_document_ids"] == json.dumps([doc])
    assert current["room_id"] == room
    new = _read([old_version_new])[0]
    assert new["amount"] == "98.76"
    assert new["currency"] is None
    assert new["expected"] == "2026-04-15"
    assert new["actual"] is None and new["room_id"] is None
    saved = _sql(f"SELECT * FROM {ARCHIVE} WHERE deal_id = :id", id=existing)[0]
    assert saved["amount_text"] == "90071992547409.91"
    assert str(saved["expected_close_date"]) == "2027-06-30"
    assert saved["restore_issue"] == "rollback_amount_changed,rollback_close_date_changed"
    # A second cycle must neither restore the stale amount nor erase that recovery copy.
    _alembic("downgrade", _migration_parent())
    _alembic("upgrade", "head")
    assert _read([existing])[0] == current
    assert _sql(f"SELECT * FROM {ARCHIVE} WHERE archive_id = :id", id=saved["archive_id"]) == [
        saved
    ]


@pytest.mark.parametrize(
    "change",
    [
        "deleted_document",
        "missing_document",
        "foreign_document",
        "malformed_document",
        "noninteger_document",
        "missing_room",
        "foreign_room",
    ],
)
def test_unavailable_refs_are_not_restored_or_discarded(recovery_rows, change):
    ids = recovery_rows
    doc, room = _refs(ids)
    deal = _deal(ids, "123.45")
    _typed_fields(deal, doc, room)
    _alembic("downgrade", _migration_parent())
    if change == "deleted_document":
        _sql("UPDATE documents SET deleted_at = now() WHERE id = :id", id=doc)
    elif change == "missing_document":
        _sql("DELETE FROM documents WHERE id = :id", id=doc)
    elif change in ("malformed_document", "noninteger_document"):
        _sql(
            f"UPDATE {ARCHIVE} SET linked_document_ids = :docs WHERE deal_id = :id",
            id=deal,
            docs="not-json" if change == "malformed_document" else '[true, "1"]',
        )
    elif change == "foreign_document":
        # Keep the original reference unavailable; inject a real foreign reference
        # into the recovery snapshot without bypassing parent-workspace constraints.
        foreign = _sql(
            """
            INSERT INTO documents (workspace_id, filename, storage_key, created_at, updated_at)
            VALUES (2, 'synthetic-foreign.txt', :key, now(), now()) RETURNING id
        """,
            key=f"synthetic/recovery-{uuid.uuid4().hex}",
        )[0]["id"]
        ids["documents"].append(foreign)
        _sql(
            f"UPDATE {ARCHIVE} SET linked_document_ids = :docs WHERE deal_id = :id",
            id=deal,
            docs=json.dumps([foreign]),
        )
    elif change == "missing_room":
        _sql("DELETE FROM shareable_spaces WHERE id = :id", id=room)
    else:
        foreign = _sql("""
            INSERT INTO shareable_spaces (workspace_id, name, is_active, created_at, updated_at)
            VALUES (2, 'Synthetic foreign room', true, now(), now()) RETURNING id
        """)[0]["id"]
        ids["shareable_spaces"].append(foreign)
        _sql(f"UPDATE {ARCHIVE} SET room_id = :room WHERE deal_id = :id", id=deal, room=foreign)
    _alembic("upgrade", "head")
    current = _read([deal])[0]
    invalid_docs = "document" in change
    assert current["linked_document_ids"] == (None if invalid_docs else json.dumps([doc]))
    assert current["room_id"] == (room if invalid_docs else None)
    assert current["amount"] == "123.45"
    saved = _sql(f"SELECT * FROM {ARCHIVE} WHERE deal_id = :id", id=deal)[0]
    assert saved["restore_issue"] == (
        "invalid_document_refs" if invalid_docs else "invalid_room_reference"
    )
    assert saved["linked_document_ids"] is not None and saved["room_id"] is not None


@pytest.mark.parametrize("change", ["deleted", "workspace", "reused_id"])
def test_missing_or_changed_row_identity_never_resurrects_archived_data(recovery_rows, change):
    ids = recovery_rows
    original = _deal(ids, "90071992547409.91")
    _sql("UPDATE deals SET currency = 'USD' WHERE id = :id", id=original)
    _alembic("downgrade", _migration_parent())
    if change == "workspace":
        _sql("UPDATE deals SET workspace_id = 2, deal_value_arr = 20 WHERE id = :id", id=original)
    else:
        _sql("DELETE FROM deals WHERE id = :id", id=original)
        if change == "reused_id":
            _sql(
                """
                INSERT INTO deals (id, workspace_id, company_name, stage, deal_value_arr,
                                   created_at, updated_at)
                VALUES (:id, 1, 'Synthetic reused id', 'prospect', 20, now(), now())
            """,
                id=original,
            )
    _alembic("upgrade", "head")
    current = _read([original])
    if change == "deleted":
        assert current == []
    else:
        assert current[0]["amount"] == "20.00"
        assert current[0]["currency"] is None
        assert current[0]["workspace_id"] == (2 if change == "workspace" else 1)
    saved = _sql(f"SELECT * FROM {ARCHIVE} WHERE deal_id = :id", id=original)[0]
    assert saved["amount_text"] == "90071992547409.91"
    assert saved["restore_issue"] == "row_missing_or_identity_changed"
