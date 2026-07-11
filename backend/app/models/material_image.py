"""MaterialImage model."""
from sqlalchemy import Column, Integer, String, ForeignKey
from app.models.base import Base, TimestampMixin

class MaterialImage(Base, TimestampMixin):
    __tablename__ = "material_images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
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
