"""
Export mapping quality stats for a questionnaire (JSON + CSV + stdout summary).

Run inside API container:
  docker compose exec api python -m scripts.audit_questionnaire_mapping_quality --questionnaire-id 130

Does not change ranking logic.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import FrameworkControl, Question, Questionnaire, WorkspaceControl
from app.models.ai_mapping import QuestionMappingPreference


def _band_for_row(mapped: bool, conf: float | None) -> str:
    if not mapped:
        return "0.00"
    c = float(conf) if conf is not None else 0.0
    if c <= 0:
        return "0.00"
    if c < 0.39:
        return "0.01-0.38"
    if c < 0.60:
        return "0.39-0.59"
    return "0.60+"


def _keywords(s: str) -> list[str]:
    low = (s or "").lower()
    tags: list[str] = []
    if any(x in low for x in ("encrypt", "tls", "ssl", "crypto", "cipher", "at rest", "in transit")):
        tags.append("encryption")
    if any(x in low for x in ("log", "siem", "audit trail", "retention", "monitor")):
        tags.append("logging")
    if any(x in low for x in ("backup", "disaster", "recovery", "continuity", "bcdr", "restore")):
        tags.append("dr_backup")
    if any(x in low for x in ("access", "iam", "identity", "privilege", "mfa", "authentication")):
        tags.append("iam_access")
    if any(x in low for x in ("incident", "breach", "response")):
        tags.append("incident")
    if any(x in low for x in ("policy", "governance", "risk register", "security program", "written policy")):
        tags.append("governance")
    return tags


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questionnaire-id", type=int, required=True)
    p.add_argument("--out-dir", type=Path, default=API_ROOT / "scripts")
    args = p.parse_args()
    qnr_id = args.questionnaire_id
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    db: Session = SessionLocal()
    try:
        qnr = db.query(Questionnaire).filter(Questionnaire.id == qnr_id).first()
        if not qnr:
            print("Questionnaire not found:", qnr_id)
            sys.exit(1)

        rows_out: list[dict] = []
        mappings = (
            db.query(QuestionMappingPreference)
            .filter(QuestionMappingPreference.questionnaire_id == qnr_id)
            .all()
        )
        q_by_id = {
            q.id: q
            for q in db.query(Question).filter(Question.questionnaire_id == qnr_id).all()
        }

        for m in mappings:
            q = q_by_id.get(m.question_id) if m.question_id else None
            text = (q.text if q else None) or (m.normalized_question_text or "")
            conf = m.confidence
            mapped = m.preferred_control_id is not None
            fc_key = ""
            fc_title = ""
            if m.preferred_control_id:
                wc = (
                    db.query(WorkspaceControl)
                    .filter(WorkspaceControl.id == m.preferred_control_id)
                    .first()
                )
                if wc and wc.framework_control_id:
                    fc = (
                        db.query(FrameworkControl)
                        .filter(FrameworkControl.id == wc.framework_control_id)
                        .first()
                    )
                    if fc:
                        fc_key = fc.control_key or ""
                        fc_title = (fc.title or "")[:120]

            band = _band_for_row(mapped, conf)
            tags = _keywords(text)
            rows_out.append(
                {
                    "mapping_id": m.id,
                    "question_id": m.question_id,
                    "question_text": (text or "")[:500],
                    "preferred_workspace_control_id": m.preferred_control_id,
                    "framework_control_key": fc_key,
                    "framework_control_title": fc_title,
                    "confidence": conf,
                    "confidence_band": band,
                    "status": m.status,
                    "source": m.source,
                    "domain_tags": tags,
                }
            )

        total = len(rows_out)
        mapped_n = sum(1 for r in rows_out if r["preferred_workspace_control_id"] is not None)
        unmapped_n = total - mapped_n

        band_counts: dict[str, int] = defaultdict(int)
        for r in rows_out:
            band_counts[r["confidence_band"]] += 1

        zero_n = sum(1 for r in rows_out if r["confidence_band"] == "0.00")
        low_n = sum(1 for r in rows_out if r["confidence_band"] == "0.01-0.38")
        mid_n = sum(1 for r in rows_out if r["confidence_band"] == "0.39-0.59")
        high_n = sum(1 for r in rows_out if r["confidence_band"] == "0.60+")

        summary = {
            "questionnaire_id": qnr_id,
            "display_id": getattr(qnr, "display_id", None),
            "total_rows": total,
            "mapped_rows": mapped_n,
            "unmapped_rows": unmapped_n,
            "confidence_distribution": {
                "0.00": zero_n,
                "0.01-0.38": low_n,
                "0.39-0.59": mid_n,
                "0.60+": high_n,
            },
            "band_counts_raw": dict(band_counts),
        }

        stem = f"qnr_{qnr_id}_mapping_audit"
        json_path = out_dir / f"{stem}.json"
        csv_path = out_dir / f"{stem}.csv"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "rows": rows_out}, f, indent=2, ensure_ascii=False)

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "mapping_id",
                    "question_id",
                    "confidence",
                    "confidence_band",
                    "framework_control_key",
                    "framework_control_title",
                    "preferred_workspace_control_id",
                    "status",
                    "domain_tags",
                    "question_text",
                ],
            )
            w.writeheader()
            for r in rows_out:
                w.writerow(
                    {
                        "mapping_id": r["mapping_id"],
                        "question_id": r["question_id"],
                        "confidence": r["confidence"],
                        "confidence_band": r["confidence_band"],
                        "framework_control_key": r["framework_control_key"],
                        "framework_control_title": r["framework_control_title"],
                        "preferred_workspace_control_id": r["preferred_workspace_control_id"],
                        "status": r["status"],
                        "domain_tags": ";".join(r["domain_tags"]),
                        "question_text": r["question_text"],
                    }
                )

        print(json.dumps(summary, indent=2))
        print("Wrote:", json_path)
        print("Wrote:", csv_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
