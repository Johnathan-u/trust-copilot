"""Credit ledger models for questionnaire-based billing."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)

from app.core.database import Base


class CreditLedger(Base):
    """Per-workspace credit balance and billing-cycle metadata."""

    __tablename__ = "credit_ledgers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    balance = Column(Integer, nullable=False, server_default=text("0"))
    monthly_allocation = Column(Integer, nullable=False, server_default=text("15"))
    cycle_start = Column(DateTime(timezone=True), nullable=True)
    cycle_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CreditTransaction(Base):
    """Immutable record of every credit change (allocation, consumption, purchase, adjustment)."""

    __tablename__ = "credit_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(32), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_credit_tx_ws_id"),
    )
