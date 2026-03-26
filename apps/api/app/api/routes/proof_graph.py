"""Proof graph API (E5-25..E5-30)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin, require_session
from app.core.database import get_db
from app.models.proof_graph import ProofGraphNode
from app.services import proof_graph_service as pgs

router = APIRouter(prefix="/proof-graph", tags=["proof-graph"])


@router.post("/sync")
def sync_graph(
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    stats = pgs.sync_with_diff_record(
        db, session["workspace_id"], trigger_event="manual_sync"
    )
    db.commit()
    return stats


@router.get("/nodes")
def get_nodes(
    limit: int = Query(500, ge=1, le=20000),
    node_type: str | None = Query(None),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {
        "nodes": pgs.list_nodes(
            db, session["workspace_id"], limit=limit, node_type=node_type
        ),
    }


@router.get("/edges")
def get_edges(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"edges": pgs.list_edges(db, session["workspace_id"])}


@router.get("/chain/answer/{answer_id}")
def chain_for_answer(
    answer_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    out = pgs.chain_for_answer(db, session["workspace_id"], answer_id)
    if not out:
        raise HTTPException(status_code=404, detail="Answer not in proof graph")
    return out


@router.get("/freshness/node/{node_id}")
def node_freshness(
    node_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    n = (
        db.query(ProofGraphNode)
        .filter(
            ProofGraphNode.id == node_id,
            ProofGraphNode.workspace_id == session["workspace_id"],
        )
        .first()
    )
    if not n:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"node_id": node_id, "freshness": pgs.freshness_for_node(db, n)}


class RecordHashBody(BaseModel):
    artifact_kind: str = Field(..., max_length=64)
    artifact_id: int
    content_base64: str | None = None
    content_text: str | None = None
    fingerprint: str | None = None


@router.post("/artifacts/hash")
def record_hash(
    body: RecordHashBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    import base64

    raw: bytes
    if body.content_base64:
        try:
            raw = base64.b64decode(body.content_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64")
    elif body.content_text is not None:
        raw = body.content_text.encode("utf-8")
    else:
        raise HTTPException(status_code=400, detail="Provide content_base64 or content_text")
    out = pgs.record_artifact_hash(
        db,
        session["workspace_id"],
        body.artifact_kind,
        body.artifact_id,
        raw,
        fingerprint=body.fingerprint,
        user_id=session.get("user_id"),
    )
    db.commit()
    return out


class VerifyHashBody(BaseModel):
    artifact_kind: str
    artifact_id: int
    content_base64: str | None = None
    content_text: str | None = None


@router.post("/artifacts/verify")
def verify_hash(
    body: VerifyHashBody,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    import base64

    if body.content_base64:
        try:
            raw = base64.b64decode(body.content_base64)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid base64")
    elif body.content_text is not None:
        raw = body.content_text.encode("utf-8")
    else:
        raise HTTPException(status_code=400, detail="Provide content_base64 or content_text")
    return pgs.verify_artifact_hash(
        db,
        session["workspace_id"],
        body.artifact_kind,
        body.artifact_id,
        raw,
    )


@router.get("/diffs")
def list_diffs(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {"diffs": pgs.list_graph_diffs(db, session["workspace_id"])}


class ReuseBody(BaseModel):
    answer_id: int
    questionnaire_id: int | None = None
    deal_id: int | None = None
    buyer_ref: str | None = None
    answer_version_hint: str | None = None
    evidence_ids: list[int] | None = None


@router.post("/reuse-provenance")
def record_reuse(
    body: ReuseBody,
    session: dict = Depends(require_can_admin),
    db: Session = Depends(get_db),
):
    out = pgs.record_reuse_provenance(
        db,
        session["workspace_id"],
        body.answer_id,
        questionnaire_id=body.questionnaire_id,
        deal_id=body.deal_id,
        buyer_ref=body.buyer_ref,
        answer_version_hint=body.answer_version_hint,
        evidence_ids=body.evidence_ids,
    )
    db.commit()
    return out


@router.get("/reuse-provenance/answer/{answer_id}")
def list_reuse(
    answer_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    return {
        "instances": pgs.list_reuse_for_answer(
            db, session["workspace_id"], answer_id
        ),
    }
