"""TC-10-002a: the TC-10-002 rollback note and the CI PostgreSQL label.

The post-merge review of #211 (comment 6789737115) found two documentation
errors. This module fails while those errors are present and passes once the
release doc, the acceptance README, and result.json say the corrected facts.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TICKET = REPO_ROOT / "docs" / "release" / "tickets" / "TC-10-002.md"
README = REPO_ROOT / "artifacts" / "acceptance" / "TC-10-002" / "README.md"
RESULT = REPO_ROOT / "artifacts" / "acceptance" / "TC-10-002" / "result.json"

# The review named these revisions. tc23001 is only a partial restore.
_FULL_RESTORES = ("tc17003", "tc17004", "tc19010")
_PARTIAL_RESTORE = "tc23001"
_FORBIDDEN = (
    "does not put those rows back",
    "never restores",
    "upgrading again does not",
    "upgrading again never",
)


def _rollback_section(text: str) -> str:
    start = text.index("**Rollback.**")
    end = text.index("**Safe TC-10-002-only rollback:**")
    return text[start:end]


def test_tc10002a_rollback_doc_names_archive_restores():
    """Upgrade restores archives for tc17003, tc17004, tc19010, and in part tc23001."""
    text = TICKET.read_text(encoding="utf-8")
    lowered = text.lower()
    for phrase in _FORBIDDEN:
        assert phrase not in lowered, phrase
    section = _rollback_section(text)
    restore_at = section.lower().index("restores archived rows")
    restore_wording = section[restore_at:]
    for revision in _FULL_RESTORES:
        assert revision in restore_wording, revision
    assert f"`{_PARTIAL_RESTORE}` restores archived rows only in part" in section


def test_tc10002a_postgresql_16_15_is_labelled_inferred():
    """README and result.json label PostgreSQL 16.15 as inferred from the digest."""
    readme_line = next(
        line
        for line in README.read_text(encoding="utf-8").splitlines()
        if "PostgreSQL 16.15" in line
    )
    assert "inferred" in readme_line.lower()
    assert "digest" in readme_line.lower()

    environment = json.loads(RESULT.read_text(encoding="utf-8"))["environment"]
    version = environment["postgresql"]
    note = environment["postgresql_note"]
    assert isinstance(version, str)
    assert "16.15" in version
    assert "inferred" in version.lower()
    assert version != "16.15"
    note_lower = note.lower()
    assert "inferred" in note_lower
    assert "digest" in note_lower
    assert "select version()" in note_lower
