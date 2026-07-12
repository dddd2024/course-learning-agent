"""Page-level parsed material state retained alongside retrieval chunks."""
from sqlalchemy import Column, ForeignKey, Integer, String, Text
from app.models.base import Base, TimestampMixin


class MaterialPage(Base, TimestampMixin):
    __tablename__ = "material_pages"
    id = Column(Integer, primary_key=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    material_version_id = Column(Integer, ForeignKey("material_versions.id"), nullable=True, index=True)
    page_no = Column(Integer, nullable=False)
    page_type = Column(String(30), nullable=False, default="text")
    parser_version = Column(String(32), nullable=False, default="legacy")
    raw_text = Column(Text, nullable=True)
    clean_text = Column(Text, nullable=True)
    blocks_json = Column(Text, nullable=True)
    decisions_json = Column(Text, nullable=True)
