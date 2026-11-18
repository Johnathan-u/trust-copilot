"""TC-11-001a: TC-11-001 evidence wording.

The post-merge review of #212 (comment 6789647959) found two documentation
errors. The child ticket also requires result.json to cite master run
42886627596. This module fails while those errors are present and passes
once the release doc, the acceptance README, and result.json say the
corrected facts.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
TICKET = REPO_ROOT / "docs" / "release" / "tickets" / "TC-11-001.md"
README = REPO_ROOT / "artifacts" / "acceptance" / "TC-11-001" / "README.md"
RESULT = REPO_ROOT / "artifacts" / "acceptance" / "TC-11-001" / "result.json"

# The review asked for this exact pin so the 27-revision count cannot be read
# as the live head after the next migration.
_AS_OF = "as of `edd3320`"
_IMAGE_DIGEST = "sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a"
_MASTER_SHA = "edd332013d09af4222b9c700a489f9b4c7709091"
_MASTER_RUN = 42886627596


def _revision_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines() if "27 revision" in line or "27 later revision" in line
    ]


def test_tc11001a_ci_environment_does_not_state_postgresql_16_15():
    """The CI environment no longer gives the bare server version 16.15.

    That string is the local run. CI logs show only the image digest, so the
    field is removed or labelled as local.
    """
    environment = json.loads(RESULT.read_text(encoding="utf-8"))["environment"]
    assert _IMAGE_DIGEST in environment["postgresql_image"]
    version = environment.get("postgresql")
    assert version != "16.15"
    if version is None:
        note = environment["postgresql_note"].lower()
        assert "local" in note
        assert "digest" in note
    else:
        assert "local" in version.lower()


def test_tc11001a_revision_count_is_pinned_to_edd3320():
    """The release doc and README pin the 27-revision count as of edd3320."""
    for path in (TICKET, README):
        text = path.read_text(encoding="utf-8")
        assert _AS_OF in text, path.name
        lines = _revision_lines(text)
        assert lines, path.name
        for line in lines:
            assert "current master" not in line.lower(), line
            assert "edd3320" in line, line


def test_tc11001a_result_cites_master_run():
    """result.json cites the master push of edd3320, run 42886627596."""
    cited = json.loads(RESULT.read_text(encoding="utf-8"))["master_run"]
    assert cited["run_id"] == _MASTER_RUN
    assert cited["sha"] == _MASTER_SHA
    assert cited["event"] == "push"
    assert cited["conclusion"] == "success"
    assert str(_MASTER_RUN) in cited["url"]
