"""Proof graph sync, chain, freshness, hashes, diffs, reuse provenance (E5-25..E5-30)."""

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.answer import Answer
from app.models.evidence_item import EvidenceItem
from app.models.golden_answer import GoldenAnswer
from app.models.proof_graph import (
    AnswerReuseProvenance,
    ArtifactIntegrityHash,
    ProofGraphDiff,
    ProofGraphEdge,
    ProofGraphNode,
)
from app.models.questionnaire import Question, Questionnaire
from app.models.workspace_control import WorkspaceControl


NODE_EVIDENCE = "evidence"
NODE_CONTROL = "control"
NODE_GOLDEN = "golden_answer"
NODE_ANSWER = "answer"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def sync_workspace_graph(db: Session, workspace_id: int) -> dict:
    """Rebuild proof graph nodes/edges for a workspace from evidence, controls, golden answers, questionnaire answers."""
    db.query(ProofGraphEdge).filter(ProofGraphEdge.workspace_id == workspace_id).delete(
        synchronize_session=False
    )
    db.query(ProofGraphNode).filter(ProofGraphNode.workspace_id == workspace_id).delete(
        synchronize_session=False
    )

    id_map: dict[tuple[str, int], int] = {}

    def add_node(
        node_type: str,
        ref_table: str | None,
        ref_id: int | None,
        label: str | None,
        meta: dict | None = None,
    ) -> int:
        key = (ref_table or node_type, ref_id or 0)
        if key in id_map:
            return id_map[key]
        n = ProofGraphNode(
            workspace_id=workspace_id,
            node_type=node_type,
            ref_table=ref_table,
            ref_id=ref_id,
            label=(label or "")[:512] if label else None,
            meta_json=json.dumps(meta) if meta else None,
            version=1,
        )
        db.add(n)
        db.flush()
        nid = n.id
        id_map[key] = nid
        return nid

    ev_rows = db.query(EvidenceItem).filter(EvidenceItem.workspace_id == workspace_id).all()
    for ev in ev_rows:
        add_node(
            NODE_EVIDENCE,
            "evidence_items",
            ev.id,
            ev.title,
            {"approval_status": ev.approval_status, "source_type": ev.source_type},
        )

    wc_rows = db.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == workspace_id).all()
    for wc in wc_rows:
        lbl = wc.custom_name or f"control-{wc.id}"
        add_node(
            NODE_CONTROL,
            "workspace_controls",
            wc.id,
            lbl,
            {"status": wc.status},
        )

    ga_rows = db.query(GoldenAnswer).filter(GoldenAnswer.workspace_id == workspace_id).all()
    for ga in ga_rows:
        gid = add_node(
            NODE_GOLDEN,
            "golden_answers",
            ga.id,
            (ga.question_text or "")[:512],
            {"status": ga.status, "confidence": ga.confidence},
        )
        try:
            eids = json.loads(ga.evidence_ids_json or "[]") or []
        except json.JSONDecodeError:
            eids = []
        for eid in eids:
            ek = ("evidence_items", int(eid))
            if ek in id_map:
                e = ProofGraphEdge(
                    workspace_id=workspace_id,
                    from_node_id=id_map[ek],
                    to_node_id=gid,
                    edge_type="evidence_to_golden",
                )
                db.add(e)
        try:
            cids = json.loads(ga.control_ids_json or "[]") or []
        except json.JSONDecodeError:
            cids = []
        for cid in cids:
            ck = ("workspace_controls", int(cid))
            if ck in id_map:
                e = ProofGraphEdge(
                    workspace_id=workspace_id,
                    from_node_id=id_map[ck],
                    to_node_id=gid,
                    edge_type="control_to_golden",
                )
                db.add(e)

    qn_ids = [
        q[0]
        for q in db.query(Questionnaire.id)
        .filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.deleted_at.is_(None),
        )
        .all()
    ]
    if qn_ids:
        ans_rows = (
            db.query(Answer, Question)
            .join(Question, Answer.question_id == Question.id)
            .filter(Question.questionnaire_id.in_(qn_ids))
            .all()
        )
        for ans, qu in ans_rows:
            aid = add_node(
                NODE_ANSWER,
                "answers",
                ans.id,
                (qu.text or "")[:200],
                {
                    "status": ans.status,
                    "confidence": ans.confidence,
                    "questionnaire_id": qu.questionnaire_id,
                },
            )
            best_ga = None
            best_score = 0.0
            nq = " ".join((qu.text or "").lower().split())
            wq = set(nq.split()) if nq else set()
            for ga in ga_rows:
                ng = " ".join((ga.question_text or "").lower().split())
                wg = set(ng.split()) if ng else set()
                if not wq or not wg:
                    continue
                overlap = len(wq & wg) / max(len(wq), 1)
                if nq in ng or ng in nq:
                    overlap = max(overlap, 0.85)
                if overlap > best_score:
                    best_score = overlap
                    best_ga = ga
            if best_ga and best_score >= 0.2:
                gk = ("golden_answers", best_ga.id)
                if gk in id_map:
                    db.add(
                        ProofGraphEdge(
                            workspace_id=workspace_id,
                            from_node_id=id_map[gk],
                            to_node_id=aid,
                            edge_type="golden_to_answer",
                        )
                    )

    db.flush()
    ncount = db.query(ProofGraphNode).filter(ProofGraphNode.workspace_id == workspace_id).count()
    ecount = db.query(ProofGraphEdge).filter(ProofGraphEdge.workspace_id == workspace_id).count()
    return {"nodes": ncount, "edges": ecount}


def list_nodes(
    db: Session,
    workspace_id: int,
    limit: int = 500,
    node_type: str | None = None,
) -> list[dict]:
    q = db.query(ProofGraphNode).filter(ProofGraphNode.workspace_id == workspace_id)
    if node_type:
        q = q.filter(ProofGraphNode.node_type == node_type)
    rows = q.order_by(ProofGraphNode.id).limit(limit).all()
    return [_node_dict(r) for r in rows]


def list_edges(db: Session, workspace_id: int, limit: int = 2000) -> list[dict]:
    rows = (
        db.query(ProofGraphEdge)
        .filter(ProofGraphEdge.workspace_id == workspace_id)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "from_node_id": r.from_node_id,
            "to_node_id": r.to_node_id,
            "edge_type": r.edge_type,
        }
        for r in rows
    ]


def _freshness_bucket(node: ProofGraphNode, db: Session) -> str:
    """live / recent / aging / stale from ref row timestamps."""
    if not node.ref_table or not node.ref_id:
        return "aging"
    now = _now()
    if node.ref_table == "evidence_items":
        ev = db.query(EvidenceItem).filter(EvidenceItem.id == node.ref_id).first()
        if not ev or not ev.created_at:
            return "stale"
        dt = ev.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = now - dt
    elif node.ref_table == "golden_answers":
        ga = db.query(GoldenAnswer).filter(GoldenAnswer.id == node.ref_id).first()
        if not ga:
            return "stale"
        dt = ga.last_reviewed_at or ga.updated_at or ga.created_at
        if not dt:
            return "aging"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = now - dt
        if ga.expires_at:
            exp = ga.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now > exp:
                return "stale"
    elif node.ref_table == "workspace_controls":
        wc = db.query(WorkspaceControl).filter(WorkspaceControl.id == node.ref_id).first()
        if not wc:
            return "stale"
        dt = wc.verified_at or wc.updated_at or wc.created_at
        if not dt:
            return "aging"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = now - dt
    elif node.ref_table == "answers":
        ans = db.query(Answer).filter(Answer.id == node.ref_id).first()
        if not ans or not ans.updated_at:
            return "aging"
        dt = ans.updated_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = now - dt
    else:
        return "aging"

    h = age.total_seconds() / 3600.0
    if h < 6:
        return "live"
    if h < 24 * 3:
        return "recent"
    if h < 24 * 21:
        return "aging"
    return "stale"


def chain_for_answer(db: Session, workspace_id: int, answer_id: int) -> dict | None:
    """Return answer node and upstream nodes via golden/evidence/control edges."""
    ans_node = (
        db.query(ProofGraphNode)
        .filter(
            ProofGraphNode.workspace_id == workspace_id,
            ProofGraphNode.ref_table == "answers",
            ProofGraphNode.ref_id == answer_id,
        )
        .first()
    )
    if not ans_node:
        return None

    visited: set[int] = set()
    chain: list[dict] = []

    def walk(nid: int):
        if nid in visited:
            return
        visited.add(nid)
        n = db.query(ProofGraphNode).filter(ProofGraphNode.id == nid).first()
        if not n:
            return
        chain.append(
            {
                **_node_dict(n),
                "freshness": _freshness_bucket(n, db),
            }
        )
        preds = (
            db.query(ProofGraphEdge)
            .filter(
                ProofGraphEdge.workspace_id == workspace_id,
                ProofGraphEdge.to_node_id == nid,
            )
            .all()
        )
        for e in preds:
            walk(e.from_node_id)

    walk(ans_node.id)
    chain.reverse()
    return {"answer_id": answer_id, "chain": chain}


def record_artifact_hash(
    db: Session,
    workspace_id: int,
    artifact_kind: str,
    artifact_id: int,
    content_bytes: bytes,
    fingerprint: str | None = None,
    user_id: int | None = None,
) -> dict:
    h = hashlib.sha256(content_bytes).hexdigest()
    row = ArtifactIntegrityHash(
        workspace_id=workspace_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        sha256_hex=h,
        content_fingerprint=fingerprint,
        recorded_by_user_id=user_id,
    )
    db.add(row)
    db.flush()
    return {
        "id": row.id,
        "sha256_hex": h,
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
    }


def verify_artifact_hash(
    db: Session,
    workspace_id: int,
    artifact_kind: str,
    artifact_id: int,
    content_bytes: bytes,
) -> dict:
    expected = hashlib.sha256(content_bytes).hexdigest()
    row = (
        db.query(ArtifactIntegrityHash)
        .filter(
            ArtifactIntegrityHash.workspace_id == workspace_id,
            ArtifactIntegrityHash.artifact_kind == artifact_kind,
            ArtifactIntegrityHash.artifact_id == artifact_id,
        )
        .order_by(ArtifactIntegrityHash.recorded_at.desc())
        .first()
    )
    if not row:
        return {"ok": False, "reason": "no_recorded_hash"}
    return {
        "ok": row.sha256_hex == expected,
        "recorded_sha256": row.sha256_hex,
        "computed_sha256": expected,
    }


def record_graph_diff(
    db: Session,
    workspace_id: int,
    trigger_event: str | None,
    before_json: str | None,
    after_json: str | None,
    summary: str | None,
) -> dict:
    d = ProofGraphDiff(
        workspace_id=workspace_id,
        trigger_event=trigger_event,
        before_json=before_json,
        after_json=after_json,
        summary=summary,
    )
    db.add(d)
    db.flush()
    return {"id": d.id, "created_at": d.created_at.isoformat() if d.created_at else None}


def list_graph_diffs(db: Session, workspace_id: int, limit: int = 50) -> list[dict]:
    rows = (
        db.query(ProofGraphDiff)
        .filter(ProofGraphDiff.workspace_id == workspace_id)
        .order_by(ProofGraphDiff.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "trigger_event": r.trigger_event,
            "summary": r.summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def record_reuse_provenance(
    db: Session,
    workspace_id: int,
    answer_id: int,
    questionnaire_id: int | None = None,
    deal_id: int | None = None,
    buyer_ref: str | None = None,
    answer_version_hint: str | None = None,
    evidence_ids: list[int] | None = None,
) -> dict:
    p = AnswerReuseProvenance(
        workspace_id=workspace_id,
        answer_id=answer_id,
        questionnaire_id=questionnaire_id,
        deal_id=deal_id,
        buyer_ref=buyer_ref,
        answer_version_hint=answer_version_hint,
        evidence_ids_json=json.dumps(evidence_ids or []),
    )
    db.add(p)
    db.flush()
    return {
        "id": p.id,
        "answer_id": answer_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def list_reuse_for_answer(
    db: Session, workspace_id: int, answer_id: int
) -> list[dict]:
    rows = (
        db.query(AnswerReuseProvenance)
        .filter(
            AnswerReuseProvenance.workspace_id == workspace_id,
            AnswerReuseProvenance.answer_id == answer_id,
        )
        .order_by(AnswerReuseProvenance.created_at.desc())
        .all()
    )
    out = []
    for r in rows:
        try:
            ev = json.loads(r.evidence_ids_json or "[]")
        except json.JSONDecodeError:
            ev = []
        out.append(
            {
                "id": r.id,
                "questionnaire_id": r.questionnaire_id,
                "deal_id": r.deal_id,
                "buyer_ref": r.buyer_ref,
                "answer_version_hint": r.answer_version_hint,
                "evidence_ids": ev,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


def snapshot_graph_json(db: Session, workspace_id: int) -> str:
    nodes = list_nodes(db, workspace_id, limit=10000)
    edges = list_edges(db, workspace_id, limit=50000)
    return json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True)


def sync_with_diff_record(db: Session, workspace_id: int, trigger_event: str) -> dict:
    before = snapshot_graph_json(db, workspace_id)
    stats = sync_workspace_graph(db, workspace_id)
    after = snapshot_graph_json(db, workspace_id)
    record_graph_diff(
        db,
        workspace_id,
        trigger_event,
        before,
        after,
        summary=f"sync nodes={stats['nodes']} edges={stats['edges']}",
    )
    return stats


def freshness_for_node(db: Session, node: ProofGraphNode) -> str:
    return _freshness_bucket(node, db)


def _node_dict(n: ProofGraphNode) -> dict:
    return {
        "id": n.id,
        "node_type": n.node_type,
        "ref_table": n.ref_table,
        "ref_id": n.ref_id,
        "label": n.label,
        "meta_json": n.meta_json,
        "version": n.version,
    }
