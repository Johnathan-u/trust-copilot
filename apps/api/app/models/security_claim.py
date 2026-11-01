"""Owner-approved public security claims with proof references (TC-17-003)."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)

from app.core.database import Base


class SecurityClaim(Base):
    """One configured claim per workspace and catalogue key.

    A row records the latest owner decision. ``claimed`` rows must carry a decision
    time; whether the claim is shown as verified is decided at read time from the
    current proof (an approved evidence item in the same workspace).
    """

    __tablename__ = "security_claims"
    __table_args__ = (
        UniqueConstraint("workspace_id", "claim_key", name="uq_security_claims_workspace_key"),
        CheckConstraint("status IN ('not_claimed','claimed')", name="ck_security_claims_status"),
        CheckConstraint("revision >= 1", name="ck_security_claims_revision"),
        CheckConstraint(
            "status <> 'claimed' OR decided_at IS NOT NULL",
            name="ck_security_claims_claimed_decided",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_key = Column(String(48), nullable=False)
    status = Column(String(16), nullable=False, default="not_claimed", server_default="not_claimed")
    statement = Column(String(500), nullable=True)
    value = Column(String(320), nullable=True)
    evidence_item_id = Column(
        Integer,
        ForeignKey("evidence_items.id", name="fk_security_claims_evidence", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_by_user_id = Column(
        Integer,
        ForeignKey("users.id", name="fk_security_claims_decider", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
