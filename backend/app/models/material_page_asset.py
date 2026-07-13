"""Immutable visual page assets for a parsed material version."""
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from app.models.base import Base, TimestampMixin


class MaterialPageAsset(Base, TimestampMixin):
    __tablename__ = "material_page_assets"
    __table_args__ = (
        UniqueConstraint("material_version_id", "page_no", name="uq_material_page_asset_version_page"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    material_version_id = Column(Integer, ForeignKey("material_versions.id"), nullable=False, index=True)
    page_no = Column(Integer, nullable=False)
    asset_path = Column(String(500), nullable=True)
    mime_type = Column(String(64), nullable=False, default="image/png")
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    dpi = Column(Integer, nullable=False, default=144)
    sha256 = Column(String(64), nullable=True, index=True)
    render_status = Column(String(30), nullable=False, default="pending")
    error_code = Column(String(100), nullable=True)
