"""MaterialImage model."""
from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy import Float
from app.models.base import Base, TimestampMixin

class MaterialImage(Base, TimestampMixin):
    __tablename__ = "material_images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    material_version_id = Column(Integer, ForeignKey("material_versions.id"), nullable=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    chunk_id = Column(Integer, ForeignKey("material_chunks.id"), nullable=True, index=True)
    page_no = Column(Integer, nullable=False)
    image_filename = Column(String(255), nullable=False)
    image_path = Column(String(500), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    format = Column(String(10), default="png")
    is_decorative = Column(Integer, nullable=False, default=0)
    decorative_reason = Column(String(255))
    perceptual_hash = Column(String(64), index=True)
    sha256 = Column(String(64), index=True)
    xref = Column(Integer, nullable=True)
    bbox_json = Column(Text, nullable=True)
    render_status = Column(String(30), nullable=False, default="ready")
    error_code = Column(String(100), nullable=True)
    color_variance = Column(Float, nullable=True)
    coverage_ratio = Column(Float, nullable=True)
