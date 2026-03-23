"""Cross-framework control mappings."""

from sqlalchemy import Column, ForeignKey, Integer

from app.core.database import Base


class ControlMapping(Base):
    __tablename__ = "control_mappings"

    id = Column(Integer, primary_key=True, index=True)
    source_control_id = Column(Integer, ForeignKey("framework_controls.id", ondelete="CASCADE"), nullable=False, index=True)
    target_control_id = Column(Integer, ForeignKey("framework_controls.id", ondelete="CASCADE"), nullable=False, index=True)
