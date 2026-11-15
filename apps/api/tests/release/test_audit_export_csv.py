"""Compliance audit CSV must neutralize formula-like text cells.

Spreadsheet apps treat a cell that starts with ``=``, ``+``, ``-``, ``@``, tab,
carriage return, a full-width equivalent, or those characters after leading
spaces, as a formula. The audit export must prefix each such text cell with
one apostrophe and leave the original characters after it. CSV quoting still
has to round-trip the cell.

``id`` and ``user_id`` are integer columns from the audit row. They are written
as canonical decimals, so a negative identifier stays ``-7`` and is not
prefixed. The same characters in a text column (an email of ``-7``, a details
JSON number) are prefixed, because that CSV cell is text. Digit strings that
are not formula-like (``123``) stay unchanged. A hyphen that is not the first
character (``AES-256``, ``No - see policy``, an ISO timestamp) stays unchanged.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.services.fallback_export import neutralize_csv_cell
from app.services.xlsx_writer import is_formula_like
from tests.release.test_export_literal_text import FORMULA_LIKE_ANSWERS, PLAIN_ANSWERS

HEADER = [
    "id",
    "occurred_at",
    "action",
    "actor",
    "user_id",
    "email",
    "resource_type",
    "resource_id",
    "details",
]
COL = {name: index for index, name in enumerate(HEADER)}
TEXT_COLUMNS = (
    "occurred_at",
    "action",
    "actor",
    "email",
    "resource_type",
    "resource_id",
    "details",
)

# Same payload set as the answer-export literal-text tests, plus leading
# whitespace that the shared detector treats as formula-like.
LEADING_WHITESPACE_PAYLOADS = (
    "  =1+1",
    "   +SUM(A1)",
    " -2+3",
    "\t@SUM(A1)",
    "\r+1",
    " \t=1+1",
    " \r=1+1",
)
FORMULA_PAYLOADS = (
    list(FORMULA_LIKE_ANSWERS) + list(LEADING_WHITESPACE_PAYLOADS) + ["@auditor.example"]
)
PLAIN_PAYLOADS = list(PLAIN_ANSWERS) + ["Yes, with comma"]
# A raw CR inside an unquoted field splits the row, so those payloads are
# exported on their own. The other payloads parse cleanly even before the fix.
CR_PAYLOADS = [payload for payload in FORMULA_PAYLOADS if "\r" in payload]
CELL_PAYLOADS = [payload for payload in FORMULA_PAYLOADS if "\r" not in payload]

_ACTION_PREFIX = "compliance."
_ACTION_LIMIT = 64
_TEXT_LIMITS = {"email": 255, "resource_type": 64, "resource_id": 128}
_BASE_TIME = datetime(2099, 6, 1)


def _expected_text(payload: str) -> str:
    """One apostrophe on formula-like text; every other string unchanged."""
    if is_formula_like(payload):
        return "'" + payload
    return payload


def _quoted_field(value: str) -> str:
    buf = io.StringIO()
    csv.writer(buf).writerow([value])
    encoded = buf.getvalue()
    assert encoded.endswith("\r\n"), repr(encoded)
    return encoded[:-2]


def _needs_quotes(value: str) -> bool:
    return any(char in value for char in ',"\r\n')


@pytest.mark.parametrize("payload", FORMULA_PAYLOADS)
def test_shared_neutralizer_prefixes_formula_payload_once(payload: str) -> None:
    """The export oracle matches the shared neutralizer, including a second pass."""
    assert is_formula_like(payload)
    assert neutralize_csv_cell(payload) == "'" + payload
    assert neutralize_csv_cell("'" + payload) == "'" + payload


@pytest.mark.parametrize("payload", PLAIN_PAYLOADS)
def test_shared_neutralizer_leaves_benign_text_unchanged(payload: str) -> None:
    assert not is_formula_like(payload)
    assert neutralize_csv_cell(payload) == payload


def _login(client: TestClient) -> int:
    response = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert response.status_code == 200, response.text
    return int(response.json()["workspace_id"])


def _add_event(
    db: Session,
    workspace_id: int,
    *,
    second: int,
    action: str,
    email: str | None,
    resource_type: str | None,
    resource_id: str | None,
    user_id: int | None,
    details: str | None,
) -> AuditEvent:
    stored_action = _ACTION_PREFIX + action
    assert len(stored_action) <= _ACTION_LIMIT, repr(stored_action)
    for column, value in (
        ("email", email),
        ("resource_type", resource_type),
        ("resource_id", resource_id),
    ):
        if value is not None:
            assert len(value) <= _TEXT_LIMITS[column], column
    event = AuditEvent(
        occurred_at=_BASE_TIME + timedelta(seconds=second),
        action=stored_action,
        user_id=user_id,
        email=email,
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )
    db.add(event)
    db.flush()
    return event


def _export_csv(client: TestClient) -> str:
    response = client.get(
        "/api/compliance/audit-history/export", params={"format": "csv", "limit": 5000}
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    return response.text


def _rows_by_id(raw: str) -> dict[str, list[str]]:
    parsed = list(csv.reader(io.StringIO(raw)))
    assert parsed, raw
    assert parsed[0] == HEADER
    found: dict[str, list[str]] = {}
    for row in parsed[1:]:
        assert len(row) == len(HEADER), row
        found[row[COL["id"]]] = row
    return found


def _check_row(problems: list[str], row: list[str], expected: dict[str, str], raw: str) -> None:
    label = expected.get("email") or expected.get("action") or row[COL["id"]]
    for column, want in expected.items():
        got = row[COL[column]]
        if got != want:
            problems.append(f"{label} {column}: expected {want!r} got {got!r}")
        if column in TEXT_COLUMNS and _needs_quotes(want) and _quoted_field(want) not in raw:
            problems.append(f"{label} {column}: CSV did not quote {want!r}")
        if column in TEXT_COLUMNS and is_formula_like(got):
            problems.append(f"{label} {column}: exported cell is still formula-like: {got!r}")
        if column in TEXT_COLUMNS and got.startswith("''"):
            problems.append(f"{label} {column}: neutralizer applied twice: {got!r}")
        if column in TEXT_COLUMNS and got.startswith("'") and neutralize_csv_cell(got) != got:
            problems.append(f"{label} {column}: a second pass would change {got!r}")


def test_endpoint_neutralizes_formula_text_and_keeps_benign_cells(
    client: TestClient, db_session: Session
) -> None:
    """Formula text is prefixed once; plain text and integer columns are not."""
    workspace_id = _login(client)
    created: list[tuple[int, dict[str, str]]] = []
    second = 0

    def expect_for(payload: str) -> dict[str, str]:
        text = _expected_text(payload)
        actor = "System" if payload == "" else text
        return {
            "action": text,
            "actor": actor,
            "user_id": "",
            "email": text,
            "resource_type": text,
            "resource_id": text,
            "details": "",
        }

    try:
        for payload in CELL_PAYLOADS + PLAIN_PAYLOADS:
            event = _add_event(
                db_session,
                workspace_id,
                second=second,
                action=payload,
                email=payload,
                resource_type=payload,
                resource_id=payload,
                user_id=None,
                details=None,
            )
            expected = expect_for(payload)
            expected["occurred_at"] = event.occurred_at.isoformat()
            expected["id"] = str(event.id)
            created.append((event.id, expected))
            second += 1

        numeric = _add_event(
            db_session,
            workspace_id,
            second=second,
            action="numeric",
            email=None,
            resource_type="control",
            resource_id="15",
            user_id=-7,
            details=None,
        )
        created.append(
            (
                numeric.id,
                {
                    "id": str(numeric.id),
                    "occurred_at": numeric.occurred_at.isoformat(),
                    "action": "numeric",
                    "actor": "User #-7",
                    "user_id": "-7",
                    "email": "",
                    "resource_type": "control",
                    "resource_id": "15",
                    "details": "",
                },
            )
        )
        second += 1
        number_details = _add_event(
            db_session,
            workspace_id,
            second=second,
            action="details-number",
            email="auditor@example.invalid",
            resource_type="control",
            resource_id="16",
            user_id=4,
            details="-42",
        )
        created.append(
            (
                number_details.id,
                {
                    "id": str(number_details.id),
                    "occurred_at": number_details.occurred_at.isoformat(),
                    "action": "details-number",
                    "actor": "auditor@example.invalid",
                    "user_id": "4",
                    "email": "auditor@example.invalid",
                    "resource_type": "control",
                    "resource_id": "16",
                    "details": "'-42",
                },
            )
        )
        second += 1
        object_details = json.dumps({"note": "=1+1"})
        object_row = _add_event(
            db_session,
            workspace_id,
            second=second,
            action="details-object",
            email="auditor@example.invalid",
            resource_type="control",
            resource_id="17",
            user_id=5,
            details=object_details,
        )
        created.append(
            (
                object_row.id,
                {
                    "id": str(object_row.id),
                    "occurred_at": object_row.occurred_at.isoformat(),
                    "action": "details-object",
                    "actor": "auditor@example.invalid",
                    "user_id": "5",
                    "email": "auditor@example.invalid",
                    "resource_type": "control",
                    "resource_id": "17",
                    "details": object_details,
                },
            )
        )
        db_session.commit()
        raw = _export_csv(client)
        rows = _rows_by_id(raw)
        problems: list[str] = []
        for event_id, expected in created:
            row = rows.get(str(event_id))
            if row is None:
                problems.append(f"missing csv row for audit event {event_id}")
                continue
            _check_row(problems, row, expected, raw)
            if not str(event_id).isdigit() or row[COL["id"]] != str(event_id):
                problems.append(f"id column changed: {row[COL['id']]!r}")
        assert not problems, "audit CSV cells\n" + "\n".join(problems)
    finally:
        if created:
            db_session.rollback()
            db_session.query(AuditEvent).filter(
                AuditEvent.id.in_([event_id for event_id, _expected in created])
            ).delete(synchronize_session=False)
            db_session.commit()


def test_endpoint_quotes_neutralized_carriage_return_cells(
    client: TestClient, db_session: Session
) -> None:
    """A cell that starts with CR is prefixed and quoted so it stays one field."""
    workspace_id = _login(client)
    created: list[int] = []
    try:
        for second, payload in enumerate(CR_PAYLOADS):
            event = _add_event(
                db_session,
                workspace_id,
                second=40 + second,
                action=payload,
                email=payload,
                resource_type="note",
                resource_id=payload,
                user_id=None,
                details=None,
            )
            created.append(event.id)
        db_session.commit()
        raw = _export_csv(client)
        problems: list[str] = []
        for payload in CR_PAYLOADS:
            neutralized = "'" + payload
            quoted = _quoted_field(neutralized)
            if quoted not in raw:
                problems.append(f"missing quoted neutralized cell {quoted!r} for {payload!r}")
            bare = _quoted_field(payload)
            if bare in raw or f",{payload}," in raw:
                problems.append(f"raw formula cell still present for {payload!r}")
        parsed = list(csv.reader(io.StringIO(raw)))
        ours = [row for row in parsed[1:] if row and row[COL["id"]] in {str(i) for i in created}]
        if len(ours) != len(created):
            problems.append(f"parsed {len(ours)} carriage-return rows, expected {len(created)}")
        for row in ours:
            for column in ("action", "email", "resource_id"):
                value = row[COL[column]]
                if not value.startswith("'") or value.startswith("''"):
                    problems.append(f"{column} not neutralized once: {value!r}")
                if is_formula_like(value):
                    problems.append(f"{column} still formula-like: {value!r}")
        assert not problems, "carriage-return audit cells\n" + "\n".join(problems)
    finally:
        if created:
            db_session.rollback()
            db_session.query(AuditEvent).filter(AuditEvent.id.in_(created)).delete(
                synchronize_session=False
            )
            db_session.commit()


def test_endpoint_neutralizes_each_text_cell_once(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route passes each text cell through the shared neutralizer one time."""
    calls: list[object] = []
    real = neutralize_csv_cell

    def _record(value: object) -> str:
        calls.append(value)
        return real(value)

    monkeypatch.setattr(
        "app.api.routes.compliance_audit.neutralize_csv_cell", _record, raising=False
    )
    workspace_id = _login(client)
    event_id: int | None = None
    try:
        event = _add_event(
            db_session,
            workspace_id,
            second=70,
            action="=1+1",
            email="=1+1",
            resource_type="=1+1",
            resource_id="=1+1",
            user_id=11,
            details=None,
        )
        event_id = event.id
        db_session.commit()
        raw = _export_csv(client)
        row = _rows_by_id(raw)[str(event_id)]
        problems: list[str] = []
        for column in ("action", "actor", "email", "resource_type", "resource_id"):
            if row[COL[column]] != "'=1+1":
                problems.append(f'{column}: expected "\'=1+1" got {row[COL[column]]!r}')
        if row[COL["user_id"]] != "11":
            problems.append(f"user_id changed: {row[COL['user_id']]!r}")
        if calls.count("=1+1") != 5:
            problems.append(
                f"neutralize_csv_cell calls for '=1+1': {calls.count('=1+1')} (expected 5); "
                f"calls={calls!r}"
            )
        if any(isinstance(value, int) and not isinstance(value, bool) for value in calls):
            problems.append(f"integer columns were neutralized: {calls!r}")
        assert not problems, "audit export neutralizer\n" + "\n".join(problems)
    finally:
        if event_id is not None:
            db_session.rollback()
            db_session.query(AuditEvent).filter(AuditEvent.id == event_id).delete(
                synchronize_session=False
            )
            db_session.commit()


def test_json_export_keeps_formula_text_unchanged(client: TestClient, db_session: Session) -> None:
    """JSON is not a spreadsheet. Formula text stays exactly as stored."""
    workspace_id = _login(client)
    event_id: int | None = None
    try:
        event = _add_event(
            db_session,
            workspace_id,
            second=80,
            action="=1+1",
            email="=1+1",
            resource_type="@SUM(A1)",
            resource_id="-2+3",
            user_id=-7,
            details=json.dumps({"note": "=1+1"}),
        )
        event_id = event.id
        db_session.commit()
        response = client.get(
            "/api/compliance/audit-history/export", params={"format": "json", "limit": 5000}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        row = next(item for item in body if item["id"] == event_id)
        assert row["action"] == "=1+1"
        assert row["email"] == "=1+1"
        assert row["actor"] == "=1+1"
        assert row["resource_type"] == "@SUM(A1)"
        assert row["resource_id"] == "-2+3"
        assert row["user_id"] == -7
        assert row["details"] == {"note": "=1+1"}
        assert "'" not in json.dumps(row["action"])
    finally:
        if event_id is not None:
            db_session.rollback()
            db_session.query(AuditEvent).filter(AuditEvent.id == event_id).delete(
                synchronize_session=False
            )
            db_session.commit()


def _render():
    from app.api.routes.compliance_audit import render_audit_history_csv

    return render_audit_history_csv


def _sample_row(payload: str, *, row_id: int = 5, user_id: int = 8) -> dict:
    return {
        "id": row_id,
        "occurred_at": "2026-11-15T12:00:00",
        "action": payload,
        "actor": payload,
        "user_id": user_id,
        "email": payload,
        "resource_type": payload,
        "resource_id": payload,
        "details": {"note": payload} if payload else None,
    }


def test_writer_neutralizes_formula_text_once() -> None:
    render = _render()
    problems: list[str] = []
    for payload in FORMULA_PAYLOADS + PLAIN_PAYLOADS:
        raw = render([_sample_row(payload)])
        rows = list(csv.reader(io.StringIO(raw)))
        assert rows[0] == HEADER
        assert len(rows) == 2
        row = rows[1]
        text = _expected_text(payload)
        for column in ("action", "actor", "email", "resource_type", "resource_id"):
            if row[COL[column]] != text:
                problems.append(f"{payload!r} {column}: {row[COL[column]]!r} != {text!r}")
            if _needs_quotes(text) and _quoted_field(text) not in raw:
                problems.append(f"{payload!r} {column}: not quoted in {raw!r}")
        if row[COL["id"]] != "5" or row[COL["user_id"]] != "8":
            problems.append(f"{payload!r} integer columns changed: {row!r}")
        if row[COL["occurred_at"]] != "2026-11-15T12:00:00":
            problems.append(f"timestamp changed: {row[COL['occurred_at']]!r}")
        if payload:
            details = json.dumps({"note": payload})
            if row[COL["details"]] != details:
                problems.append(f"details JSON changed: {row[COL['details']]!r}")
        elif row[COL["details"]] != "":
            problems.append(f"empty details changed: {row[COL['details']]!r}")
    assert not problems, "writer helper\n" + "\n".join(problems)


def test_writer_keeps_negative_integers_and_neutralizes_the_same_text() -> None:
    """Negative id and user_id stay numeric. The same text in other columns does not."""
    render = _render()
    raw = render(
        [
            {
                "id": -3,
                "occurred_at": "2026-11-15T12:00:00",
                "action": "view",
                "actor": "User #-7",
                "user_id": -7,
                "email": "-7",
                "resource_type": "control",
                "resource_id": "123",
                "details": -42,
            }
        ]
    )
    row = list(csv.reader(io.StringIO(raw)))[1]
    assert row[COL["id"]] == "-3"
    assert row[COL["user_id"]] == "-7"
    assert not row[COL["id"]].startswith("'")
    assert not row[COL["user_id"]].startswith("'")
    assert row[COL["email"]] == "'-7"
    assert row[COL["details"]] == "'-42"
    assert row[COL["actor"]] == "User #-7"
    assert row[COL["resource_id"]] == "123"
    assert row[COL["action"]] == "view"
    assert row[COL["occurred_at"]] == "2026-11-15T12:00:00"


def test_writer_applies_neutralizer_once_per_text_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    real = neutralize_csv_cell

    def _record(value: object) -> str:
        calls.append(value)
        return real(value)

    monkeypatch.setattr(
        "app.api.routes.compliance_audit.neutralize_csv_cell", _record, raising=False
    )
    render = _render()
    render([_sample_row("=1+1", row_id=9, user_id=11)])
    assert calls, "writer did not call neutralize_csv_cell"
    assert calls.count("=1+1") == 5
    assert calls.count(9) == 0
    assert calls.count(11) == 0
    assert calls.count("9") == 0
    assert calls.count("11") == 0
    details = json.dumps({"note": "=1+1"})
    assert calls.count(details) == 1
    assert calls.count("2026-11-15T12:00:00") == 1


def test_writer_empty_export_is_the_header_only() -> None:
    assert _render()([]) == (
        "id,occurred_at,action,actor,user_id,email,resource_type,resource_id,details\n"
    )
