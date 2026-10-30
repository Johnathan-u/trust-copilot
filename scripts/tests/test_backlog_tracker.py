"""Behavioral checks for the offline backlog and its single-writer update path."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/backlog_tracker.py"
SOURCE = Path("docs/planning/TrustCopilot_Execution_Backlog.json")
STATE = Path("docs/planning/backlog-state.json")
DISPLAY = Path("docs/tracker/data.js")
SHA = "b2bd1e0df5cdeb03b8d0cd240f5a161835ea621d"
WHEN = "2026-10-30T10:00:00Z"
EVIDENCE = "https://github.com/Johnathan-u/trust-copilot/issues/85"


def pending_fixture(plan, canonical_bytes):
    """Independent, minimal test ledger; never read mutable repository execution state."""
    observed = "2026-10-30T09:00:00Z"
    tickets = {}
    for ticket in plan["tickets"]:
        acceptance = {
            "state": "PENDING",
            "assessed_by": None,
            "assessed_at": None,
            "assessed_sha": None,
            "assessment_evidence_urls": [],
            "tested_sha": None,
            "implemented_by": [],
            "independent_reviewer": None,
            "reviewed_at": None,
            "reviewed_sha": None,
            "review_evidence_urls": [],
            "note": "Deterministic unassessed test fixture.",
        }
        for field, ids in (
            ("criteria", ticket["acceptance_ids"]),
            (
                "definition_of_done",
                [f"{ticket['id']}-DOD{i + 1}" for i in range(len(ticket["definition_of_done"]))],
            ),
        ):
            acceptance[field] = [
                {
                    "id": requirement,
                    "status": "NOT_VERIFIED",
                    "evidence_urls": [],
                    "tested_sha": None,
                }
                for requirement in ids
            ]
        tickets[ticket["id"]] = {
            "status": "BASELINE_RECONCILIATION",
            "evidence_state": "BASELINE_RECONCILIATION",
            "owner": None,
            "blockers": [],
            "next_action": "Assess the original contract.",
            "updated_at": observed,
            "source_sha": SHA,
            "acceptance": acceptance,
            "pr_links": [],
            "evidence_links": [],
            "audit": {},
        }
    evidence_parent = tickets["TC-02-007"]
    evidence_parent["status"] = evidence_parent["evidence_state"] = "EVIDENCE_RECONCILIATION"
    evidence_parent["pr_links"] = [
        {
            "number": 140,
            "title": "Merged child fixture; parent acceptance pending",
            "url": "https://github.com/Johnathan-u/trust-copilot/pull/140",
            "state": "merged",
            "head_sha": SHA,
        }
    ]
    metrics = {
        "scope_version": 1,
        "accepted_points": None,
        "completion_percentage": None,
        "assessed_tickets": 0,
        "total_tickets": 384,
        "total_points": 1864,
        "state_counts": {"BASELINE_RECONCILIATION": 383, "EVIDENCE_RECONCILIATION": 1},
        "accepted_claim_points": 0,
        "accepted_tickets": 0,
        "baseline_status": "PENDING",
    }
    return {
        "schema_version": 1,
        "scope_version": 1,
        "revision": 1,
        "as_of_utc": observed,
        "source_sha": SHA,
        "baseline_status": "PENDING",
        "scope": {
            "canonical_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
            "total_tickets": 384,
            "total_points": 1864,
            "total_epics": 30,
            "weights": {ticket["id"]: ticket["story_points"] for ticket in plan["tickets"]},
            "scope_changes": [],
        },
        "tickets": tickets,
        "release_gates": [
            {
                "id": f"G{i}",
                "title": f"Fixture gate {i}",
                "status": "NOT_VERIFIED",
                "note": "Gate evidence pending in this test fixture.",
                "evidence_urls": [],
                "ticket_ids": [],
                "owner": None,
            }
            for i in range(7)
        ],
        "operational_gates": [],
        "followups": [
            {
                "id": ticket_id,
                "title": f"Supplemental fixture {ticket_id}",
                "parent_id": parent,
                "story_points": points,
                "source_url": EVIDENCE,
                "source_path": path,
            }
            for ticket_id, parent, points, path in (
                ("TC-02-007b", "TC-02-007", 2, "docs/release/tickets/TC-02-007b.md"),
                ("TC-16-BUG-001", None, None, "docs/release/tickets/TC-16-BUG-001.md"),
                ("TC-01-007", None, None, "docs/acceptance/scope-freeze.md"),
            )
        ],
        "history": [
            {
                "revision": 1,
                "at": observed,
                "actor": "test-fixture",
                "reason": "Seed pending tests",
                "source_sha": SHA,
                "before": None,
                "after": metrics,
                "changes": {},
            }
        ],
        "audit_context": {"source_sha": SHA, "as_of_utc": observed},
        "pull_requests": [],
        "reconciliation_queue": [],
    }


class BacklogTrackerTests(unittest.TestCase):
    fixture_source = REPO

    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "backlog tracker CLI must be implemented")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        destination = self.root / SOURCE
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.fixture_source / SOURCE, destination)
        self.plan = self.read(SOURCE)
        self.initial = pending_fixture(self.plan, destination.read_bytes())
        self.write(STATE, self.initial)

    def read(self, relative):
        return json.loads((self.root / relative).read_text())

    def write(self, relative, value):
        (self.root / relative).write_text(json.dumps(value))

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def update(self, patch, revision=None, actor="coordinator"):
        patch_path = self.root / "patch.json"
        self.write("patch.json", patch)
        return self.cli(
            "update",
            "--expected-revision",
            str(self.initial["revision"] if revision is None else revision),
            "--actor",
            actor,
            "--reason",
            "Record inspected original-parent evidence",
            "--patch",
            str(patch_path),
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def assessment(self, ticket, accepted=False):
        acceptance = copy.deepcopy(self.initial["tickets"][ticket["id"]]["acceptance"])
        acceptance.update(
            state="ACCEPTED" if accepted else "NOT_ACCEPTED",
            assessed_by="reviewer",
            assessed_at=WHEN,
            assessed_sha=SHA,
            assessment_evidence_urls=[EVIDENCE],
        )
        for requirement in acceptance["criteria"] + acceptance["definition_of_done"]:
            requirement.update(
                status="PASS" if accepted else "FAIL",
                evidence_urls=[EVIDENCE],
                tested_sha=SHA,
            )
        if accepted:
            acceptance.update(
                tested_sha=SHA,
                implemented_by=["implementer"],
                independent_reviewer="reviewer",
                reviewed_at=WHEN,
                reviewed_sha=SHA,
                review_evidence_urls=[EVIDENCE],
            )
        return acceptance

    def full_assessment_patch(self, accepted_id="TC-01-001"):
        return {
            "source_sha": SHA,
            "as_of_utc": WHEN,
            "tickets": {
                ticket["id"]: {
                    "status": "DONE" if ticket["id"] == accepted_id else "READY",
                    "acceptance": self.assessment(ticket, ticket["id"] == accepted_id),
                }
                for ticket in self.plan["tickets"]
            },
        }

    def test_later_complete_source_ledger_does_not_change_pending_semantics(self):
        later = self.full_assessment_patch()
        later["as_of_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assert_ok(self.update(later))
        self.assertEqual(self.read(STATE)["baseline_status"], "VERIFIED")
        live_check = LiveBacklogSnapshotTests("test_live_snapshot_matches_actual_ledger")
        live_check.source_root = self.root
        result = unittest.TestResult()
        live_check.run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        for name in (
            "test_pending_audit_preserves_full_contract_and_has_no_percentage",
            "test_full_assessment_counts_original_points_once_and_reopen_removes_credit",
        ):
            with self.subTest(probe=name):
                probe = BacklogTrackerTests(name)
                probe.fixture_source = self.root
                result = unittest.TestResult()
                probe.run(result)
                self.assertTrue(result.wasSuccessful(), result.failures + result.errors)

    def test_pending_audit_preserves_full_contract_and_has_no_percentage(self):
        self.assert_ok(self.cli("build"))
        raw = (self.root / DISPLAY).read_text()
        payload = json.loads(raw.split("window.TRUSTCOPILOT_BACKLOG = ", 1)[1].rstrip(";\n"))
        self.assertEqual(payload["summary"]["total_tickets"], 384)
        self.assertEqual(payload["summary"]["total_points"], 1864)
        self.assertEqual(payload["summary"]["assessed_tickets"], 0)
        self.assertIsNone(payload["summary"]["accepted_points"])
        self.assertIsNone(payload["summary"]["completion_percentage"])
        self.assertEqual(
            payload["summary"]["state_counts"],
            {
                "BASELINE_RECONCILIATION": 383,
                "EVIDENCE_RECONCILIATION": 1,
            },
        )
        self.assertEqual(len(payload["epics"]), 30)
        for original, displayed in zip(self.plan["tickets"], payload["tickets"], strict=False):
            self.assertEqual({key: displayed[key] for key in original}, original)
        self.assertEqual(
            {g["id"] for g in payload["release_gates"]}, set("G" + str(i) for i in range(7))
        )
        self.assertEqual(len(payload["followups"]), 3)

    def test_summary_identifies_revision_and_snapshot_for_the_update_workflow(self):
        result = self.cli("summary")
        self.assert_ok(result)
        summary = json.loads(result.stdout)
        for field in ("revision", "scope_version", "source_sha", "as_of_utc"):
            self.assertEqual(summary.get(field), self.initial[field])
        self.assertEqual(summary.get("metric_label"), "Accepted original-parent points")
        self.assert_ok(
            self.update(
                {"tickets": {"TC-01-001": {"next_action": "Use the reported revision."}}},
                revision=summary["revision"],
            )
        )
        refreshed = json.loads(self.cli("summary").stdout)
        self.assertEqual(refreshed["revision"], summary["revision"] + 1)
        self.assertEqual(refreshed["as_of_utc"], self.read(STATE)["as_of_utc"])

    def test_dependency_rulings_replace_engineering_edges_and_preserve_frozen_source(self):
        original_bytes = (self.root / SOURCE).read_bytes()
        self.assert_ok(self.cli("build"))
        raw = (self.root / DISPLAY).read_text()
        payload = json.loads(raw.split("window.TRUSTCOPILOT_BACKLOG = ", 1)[1].rstrip(";\n"))
        tickets = {ticket["id"]: ticket for ticket in payload["tickets"]}
        self.assertEqual(
            tickets["TC-12-004"].get("effective_depends_on"), ["TC-12-002", "TC-12-003"]
        )
        self.assertEqual(
            tickets["TC-12-004"]["depends_on"], ["TC-11-003", "TC-11-001", "TC-06-001"]
        )
        self.assertEqual(tickets["TC-12-004"]["dependency_ruling_ids"], ["R1"])
        self.assertEqual(tickets["TC-26-018"]["effective_depends_on"], ["TC-26-014", "TC-07-011"])
        self.assertEqual(
            tickets["TC-26-018"]["depends_on"], ["TC-26-014", "TC-24-005", "TC-07-011"]
        )
        self.assertEqual(tickets["TC-26-018"]["dependency_ruling_ids"], ["R2"])
        rulings = {ruling["id"]: ruling for ruling in payload["dependency_rulings"]}
        self.assertEqual(set(rulings), {"R1", "R2", "R3", "R4"})
        for ruling in rulings.values():
            self.assertEqual(
                ruling["source_url"],
                f"https://github.com/Johnathan-u/trust-copilot/blob/{SHA}/"
                "docs/acceptance/scope-freeze.md#8-coordinator-rulings-recorded-at-freeze",
            )
        self.assertEqual((self.root / SOURCE).read_bytes(), original_bytes)
        for original in self.plan["tickets"]:
            self.assertEqual({key: tickets[original["id"]][key] for key in original}, original)

    def test_legal_rulings_separate_release_gates_but_preserve_transfer_prerequisites(self):
        self.assert_ok(self.cli("build"))
        raw = (self.root / DISPLAY).read_text()
        payload = json.loads(raw.split("window.TRUSTCOPILOT_BACKLOG = ", 1)[1].rstrip(";\n"))
        tickets = {ticket["id"]: ticket for ticket in payload["tickets"]}
        self.assertEqual(tickets["TC-02-002"].get("effective_depends_on"), ["TC-02-001"])
        self.assertEqual(tickets["TC-02-002"]["release_gate_dependencies"], ["TC-01-003"])
        for ticket_id in ("TC-09-007", "TC-09-008"):
            self.assertEqual(tickets[ticket_id]["effective_depends_on"], ["TC-07-007", "TC-09-002"])
            self.assertEqual(tickets[ticket_id]["release_gate_dependencies"], ["TC-01-003"])
            self.assertEqual(tickets[ticket_id]["dependency_ruling_ids"], ["R4"])
        for ticket_id in ["TC-21-001"] + [f"TC-21-{number:03}" for number in range(14, 23)]:
            expected_start = [] if ticket_id == "TC-21-001" else ["TC-21-001"]
            self.assertEqual(tickets[ticket_id]["effective_depends_on"], expected_start)
            self.assertEqual(
                tickets[ticket_id]["release_gate_dependencies"], ["TC-01-003", "TC-01-007"]
            )
            self.assertEqual(tickets[ticket_id]["dependency_ruling_ids"], ["R3", "R4"])
        for ticket_id, dependencies in (
            ("TC-29-006", ["TC-28-006", "TC-01-004", "TC-01-002"]),
            ("TC-30-004", ["TC-29-006", "TC-01-002"]),
        ):
            self.assertEqual(tickets[ticket_id]["effective_depends_on"], dependencies)
            self.assertEqual(tickets[ticket_id]["release_gate_dependencies"], [])
            self.assertEqual(tickets[ticket_id]["dependency_ruling_ids"], ["R4"])
        supplemental = next(item for item in payload["followups"] if item["id"] == "TC-01-007")
        self.assertEqual(supplemental["source_path"], "docs/acceptance/scope-freeze.md")
        self.assertEqual(payload["summary"]["total_points"], 1864)

    def test_merged_pr_or_child_never_grants_parent_acceptance(self):
        ticket = self.initial["tickets"]["TC-02-007"]
        self.assertTrue(ticket["pr_links"])
        self.assertEqual(ticket["acceptance"]["state"], "PENDING")
        self.assert_ok(self.cli("summary"))
        summary = json.loads(self.cli("summary").stdout)
        self.assertIsNone(summary["accepted_points"])
        self.assertEqual(summary["accepted_claim_points"], 0)
        self.assertEqual(summary["total_points"], 1864)

    def test_false_done_missing_properties_and_self_review_are_rejected(self):
        original = next(t for t in self.plan["tickets"] if t["id"] == "TC-01-001")
        valid = self.assessment(original, accepted=True)
        changes = [
            {"status": "DONE"},
            {"status": "DONE", "acceptance": {}},
            {"status": "DONE", "acceptance": {**valid, "tested_sha": "abc123"}},
            {"status": "DONE", "acceptance": {**valid, "independent_reviewer": "implementer"}},
            {"status": "DONE", "owner": "REVIEWER", "acceptance": valid},
            {"status": "DONE", "acceptance": {**valid, "criteria": valid["criteria"][:-1]}},
            {"status": "DONE", "acceptance": {**valid, "definition_of_done": []}},
            {"status": "DONE", "acceptance": {**valid, "reviewed_sha": "a" * 40}},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assert_rejected(self.update({"tickets": {"TC-01-001": change}}))
                self.assertEqual(self.read(STATE), self.initial)

    def test_each_accepted_requirement_needs_evidence_at_tested_sha(self):
        original = self.plan["tickets"][0]
        for field in ("criteria", "definition_of_done"):
            for corrupt in ({"status": "FAIL"}, {"evidence_urls": []}, {"tested_sha": "a" * 40}):
                with self.subTest(field=field, corrupt=corrupt):
                    acceptance = self.assessment(original, accepted=True)
                    acceptance[field][0].update(corrupt)
                    self.assert_rejected(
                        self.update(
                            {
                                "tickets": {
                                    original["id"]: {"status": "DONE", "acceptance": acceptance}
                                }
                            }
                        )
                    )

    def test_baseline_cannot_be_completed_by_flag_or_partial_assessment(self):
        self.assert_rejected(self.update({"baseline_status": "VERIFIED"}))
        hand_edited = copy.deepcopy(self.initial)
        hand_edited["baseline_status"] = "VERIFIED"
        self.write(STATE, hand_edited)
        self.assert_rejected(self.cli("build"))
        self.write(STATE, self.initial)
        self.assert_ok(
            self.update(
                {
                    "tickets": {
                        "TC-01-001": {
                            "status": "DONE",
                            "acceptance": self.assessment(self.plan["tickets"][0], True),
                        }
                    }
                }
            )
        )
        summary = json.loads(self.cli("summary").stdout)
        self.assertEqual(summary["assessed_tickets"], 1)
        self.assertEqual(summary["accepted_claim_points"], 3)
        self.assertIsNone(summary["accepted_points"])
        self.assertIsNone(summary["completion_percentage"])

    def test_full_assessment_counts_original_points_once_and_reopen_removes_credit(self):
        self.assert_ok(self.update(self.full_assessment_patch()))
        summary = json.loads(self.cli("summary").stdout)
        self.assertEqual(summary["assessed_tickets"], 384)
        self.assertEqual(summary["accepted_points"], 3)
        self.assertAlmostEqual(summary["completion_percentage"], 100 * 3 / 1864, places=2)
        accepted = self.read(STATE)
        previous_event = copy.deepcopy(accepted["history"][-1])
        self.assert_ok(
            self.update(
                {
                    "tickets": {
                        "TC-01-001": {
                            "status": "REOPENED",
                            "blockers": ["Regression found in scope inventory"],
                            "next_action": "Revalidate the inventory against the current source.",
                        }
                    }
                },
                revision=accepted["revision"],
            )
        )
        summary = json.loads(self.cli("summary").stdout)
        self.assertEqual(summary["accepted_points"], 0)
        latest = self.read(STATE)
        self.assertEqual(latest["tickets"]["TC-01-001"]["acceptance"]["state"], "REVOKED")
        self.assertEqual(latest["tickets"]["TC-01-001"]["evidence_state"], "REGRESSION")
        self.assertEqual(latest["history"][-2], previous_event)
        self.assertEqual(latest["history"][-1]["before"]["accepted_points"], 3)
        self.assertEqual(latest["history"][-1]["after"]["accepted_points"], 0)
        self.assertEqual(latest["history"][-1]["before"]["total_points"], 1864)

    def test_reopening_with_explicit_revocation_clears_verified_evidence_label(self):
        ticket = self.plan["tickets"][0]
        self.assert_ok(
            self.update(
                {
                    "tickets": {
                        ticket["id"]: {
                            "status": "DONE",
                            "acceptance": self.assessment(ticket, True),
                        }
                    }
                }
            )
        )
        accepted = self.read(STATE)
        self.assertEqual(accepted["tickets"][ticket["id"]]["evidence_state"], "VERIFIED_ACCEPTED")
        revoked = copy.deepcopy(accepted["tickets"][ticket["id"]]["acceptance"])
        revoked["state"] = "REVOKED"
        self.assert_ok(
            self.update(
                {"tickets": {ticket["id"]: {"status": "REOPENED", "acceptance": revoked}}},
                revision=accepted["revision"],
            )
        )
        reopened = self.read(STATE)["tickets"][ticket["id"]]
        self.assertEqual(reopened["evidence_state"], "REGRESSION")
        self.assertEqual(reopened["acceptance"]["state"], "REVOKED")
        self.assertEqual(json.loads(self.cli("summary").stdout)["accepted_claim_points"], 0)

    def test_pending_work_cannot_claim_verified_accepted_evidence(self):
        self.assert_rejected(
            self.update({"tickets": {"TC-01-001": {"evidence_state": "VERIFIED_ACCEPTED"}}})
        )
        self.assertEqual(self.read(STATE), self.initial)
        hand_edited = copy.deepcopy(self.initial)
        hand_edited["tickets"]["TC-01-001"]["evidence_state"] = "VERIFIED_ACCEPTED"
        self.write(STATE, hand_edited)
        self.assert_rejected(self.cli("build"))

    def test_unknown_ids_statuses_and_unsafe_evidence_urls_fail_closed(self):
        for patch in (
            {"tickets": {"TC-99-999": {"status": "READY"}}},
            {"tickets": {"TC-01-001": {"status": "NOT STARTED"}}},
            {"tickets": {"TC-01-001": {"story_points": 100}}},
            {"tickets": {"TC-01-001": {"evidence_links": ["javascript:alert(1)"]}}},
            {"release_gates": {"G99": {"status": "PASSED"}}},
            {"release_gates": {"G0": {"ticket_ids": ["TC-99-999"]}}},
            {"release_gates": {"G0": {"status": "PASSED", "evidence_urls": []}}},
            {"source_sha": "main"},
            {"as_of_utc": "yesterday"},
        ):
            with self.subTest(patch=patch):
                self.assert_rejected(self.update(patch))
                self.assertEqual(self.read(STATE), self.initial)

    def test_stale_revision_preserves_first_writer_and_records_reason(self):
        self.assert_ok(
            self.update({"tickets": {"TC-01-001": {"next_action": "Review the scope inventory."}}})
        )
        first = self.read(STATE)
        self.assert_rejected(
            self.update({"tickets": {"TC-01-001": {"next_action": "Overwrite first writer."}}})
        )
        self.assertEqual(self.read(STATE), first)
        event = first["history"][-1]
        self.assertEqual(event["actor"], "coordinator")
        self.assertEqual(event["reason"], "Record inspected original-parent evidence")
        self.assertEqual(event["before"]["scope_version"], 1)
        self.assertIsNone(event["before"]["accepted_points"])
        self.assertIsNone(event["after"]["completion_percentage"])

    def test_simultaneous_processes_cannot_both_update_same_revision(self):
        patch = self.root / "patch.json"
        patch.write_text(
            json.dumps({"tickets": {"TC-01-001": {"next_action": "Concurrent review."}}})
        )
        args = [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(self.root),
            "update",
            "--expected-revision",
            str(self.initial["revision"]),
            "--actor",
            "coordinator",
            "--reason",
            "concurrent review",
            "--patch",
            str(patch),
        ]
        processes = [
            subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        results = [(process, process.communicate(timeout=30)) for process in processes]
        self.assertEqual(sorted(process.returncode for process, _ in results), [0, 1])
        self.assertEqual(self.read(STATE)["revision"], self.initial["revision"] + 1)

    def test_frozen_canonical_bytes_and_weights_cannot_drift_together(self):
        tampered = copy.deepcopy(self.plan)
        tampered["tickets"][0]["story_points"] += 1
        self.write(SOURCE, tampered)
        self.assert_rejected(self.cli("build"))
        state = copy.deepcopy(self.initial)
        state["scope"]["total_points"] += 1
        state["scope"]["weights"]["TC-01-001"] += 1
        state["scope"]["canonical_sha256"] = hashlib.sha256(
            (self.root / SOURCE).read_bytes()
        ).hexdigest()
        self.write(STATE, state)
        self.assert_rejected(self.cli("build"))

    def test_check_rejects_generated_drift_and_build_repairs_it(self):
        self.assert_ok(self.cli("build"))
        self.assert_ok(self.cli("check"))
        with (self.root / DISPLAY).open("a") as output:
            output.write("// manual override\n")
        self.assert_rejected(self.cli("check"))
        self.assert_ok(self.cli("build"))
        self.assert_ok(self.cli("check"))

    def test_future_snapshots_and_impossible_historical_credit_are_rejected(self):
        self.assert_rejected(self.update({"as_of_utc": "2099-01-01T00:00:00Z"}))
        self.assert_ok(
            self.update({"tickets": {"TC-01-001": {"next_action": "Review historical evidence."}}})
        )
        state = self.read(STATE)
        state["history"][0]["after"]["accepted_claim_points"] = 9999
        state["history"][1]["before"] = copy.deepcopy(state["history"][0]["after"])
        self.write(STATE, state)
        self.assert_rejected(self.cli("build"))

    def test_browser_payload_keeps_untrusted_text_inert(self):
        note = '</script><script>alert("unsafe")</script>\u2028\u2029'
        self.assert_ok(self.update({"tickets": {"TC-01-001": {"next_action": note}}}))
        self.assert_ok(self.cli("build"))
        raw = (self.root / DISPLAY).read_text()
        self.assertNotIn("</script", raw)
        self.assertNotIn("\u2028", raw)
        self.assertNotIn("\u2029", raw)
        payload = json.loads(raw.split("window.TRUSTCOPILOT_BACKLOG = ", 1)[1].rstrip(";\n"))
        self.assertEqual(payload["tickets"][0]["current"]["next_action"], note)


class LiveBacklogSnapshotTests(unittest.TestCase):
    source_root = REPO

    def test_live_snapshot_matches_actual_ledger(self):
        """Live status is allowed to advance; its checked-in projection must follow it."""
        state = json.loads((self.source_root / STATE).read_text())
        plan = json.loads((self.source_root / SOURCE).read_text())
        results = {}
        for command in ("check", "summary"):
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--root", str(self.source_root), command],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            results[command] = result.stdout
        summary = json.loads(results["summary"])
        raw = (self.source_root / DISPLAY).read_text()
        payload = json.loads(raw.split("window.TRUSTCOPILOT_BACKLOG = ", 1)[1].rstrip(";\n"))
        for field in ("revision", "scope_version", "source_sha", "as_of_utc", "baseline_status"):
            self.assertEqual(summary[field], state[field])
            self.assertEqual(payload["meta"][field], state[field])
        currents = state["tickets"].values()
        assessed = sum(current["acceptance"]["state"] != "PENDING" for current in currents)
        accepted_points = sum(
            ticket["story_points"]
            for ticket in plan["tickets"]
            if state["tickets"][ticket["id"]]["status"] == "DONE"
        )
        self.assertEqual(summary["assessed_tickets"], assessed)
        self.assertEqual(summary["state_counts"], dict(Counter(c["status"] for c in currents)))
        self.assertEqual(summary["accepted_claim_points"], accepted_points)
        self.assertEqual(
            summary["accepted_points"],
            accepted_points if assessed == len(plan["tickets"]) else None,
        )
        self.assertEqual(payload["followups"], state["followups"])
        displayed = {ticket["id"]: ticket for ticket in payload["tickets"]}
        self.assertEqual(set(displayed), set(state["tickets"]))
        for ticket in plan["tickets"]:
            self.assertEqual(displayed[ticket["id"]]["current"], state["tickets"][ticket["id"]])
            self.assertEqual({key: displayed[ticket["id"]][key] for key in ticket}, ticket)


if __name__ == "__main__":
    unittest.main()
