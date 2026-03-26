"""Proof graph and integrity (E5-25..E5-30)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class ProofGraphNode(Base):
    __tablename__ = "proof_graph_nodes"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    node_type = Column(String(32), nullable=False)
    ref_table = Column(String(64), nullable=True)
    ref_id = Column(Integer, nullable=True)
    label = Column(String(512), nullable=True)
    meta_json = Column(Text, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProofGraphEdge(Base):
    __tablename__ = "proof_graph_edges"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    from_node_id = Column(Integer, ForeignKey("proof_graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    to_node_id = Column(Integer, ForeignKey("proof_graph_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(String(64), nullable=False)


class ArtifactIntegrityHash(Base):
    __tablename__ = "artifact_integrity_hashes"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_kind = Column(String(64), nullable=False)
    artifact_id = Column(Integer, nullable=False)
    sha256_hex = Column(String(64), nullable=False)
    content_fingerprint = Column(Text, nullable=True)
    recorded_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ProofGraphDiff(Base):
    __tablename__ = "proof_graph_diffs"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    trigger_event = Column(String(128), nullable=True)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AnswerReuseProvenance(Base):
    __tablename__ = "answer_reuse_provenance"

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_id = Column(Integer, nullable=False, index=True)
    questionnaire_id = Column(Integer, nullable=True)
    deal_id = Column(Integer, ForeignKey("deals.id", ondelete="SET NULL"), nullable=True)
    buyer_ref = Column(String(255), nullable=True)
    answer_version_hint = Column(String(64), nullable=True)
    evidence_ids_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
