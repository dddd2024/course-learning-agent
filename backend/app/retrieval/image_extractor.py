"""Extract embedded images from PDF files using PyMuPDF (fitz)."""
from __future__ import annotations

import logging
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ImageInfo:
    """Metadata for a single extracted image."""
    page_no: int
    image_bytes: bytes
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = "png"
    xref: Optional[int] = None
    is_decorative: bool = False
    decorative_reason: Optional[str] = None
    perceptual_hash: Optional[str] = None
    color_variance: Optional[float] = None
    coverage_ratio: Optional[float] = None


def _image_characteristics(image_bytes: bytes) -> tuple[str, float]:
    """Return a compact perceptual hash and RGB variance without OCR."""
    try:
        from PIL import Image, ImageStat
        with Image.open(io.BytesIO(image_bytes)) as image:
            rgb = image.convert("RGB")
            variance = sum(ImageStat.Stat(rgb).var) / 3
            small = rgb.convert("L").resize((8, 8))
            values = list(small.getdata())
            average = sum(values) / len(values)
            bits = "".join("1" if value >= average else "0" for value in values)
            return f"{int(bits, 2):016x}", float(variance)
    except Exception:
        return hashlib.sha256(image_bytes).hexdigest()[:32], 0.0


def extract_images_from_pdf(file_path: str, *, min_size: int = 50) -> List[ImageInfo]:
    """Extract embedded images from a PDF file.

    Args:
        file_path: Absolute path to the PDF file.
        min_size: Minimum width/height in pixels to include (filters out tiny icons/logos).

    Returns:
        List of ImageInfo objects, one per extracted image.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("PDF file not found: %s", file_path)
        return []

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Run: pip install PyMuPDF")
        return []

    images: List[ImageInfo] = []
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", file_path, e)
        return []

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_no = page_index + 1
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image or not base_image.get("image"):
                        continue

                    img_bytes = base_image["image"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    if width < min_size or height < min_size:
                        continue

                    img_format = base_image.get("ext", "png")
                    if img_format in ("jpeg", "jpg"):
                        img_format = "jpg"
                    else:
                        img_format = "png"

                    ratio = max(width, height) / max(1, min(width, height))
                    digest, color_variance = _image_characteristics(img_bytes)
                    rects = page.get_image_rects(xref)
                    page_area = max(float(page.rect.width * page.rect.height), 1.0)
                    coverage_ratio = max(
                        (float(rect.width * rect.height) / page_area for rect in rects),
                        default=0.0,
                    )
                    reason = None
                    if ratio > 8:
                        reason = "extreme_aspect_ratio"
                    elif color_variance < 4:
                        reason = "low_color_variance"
                    elif coverage_ratio > 0.8 and color_variance < 30:
                        reason = "background_coverage"
                    images.append(ImageInfo(
                        page_no=page_no,
                        image_bytes=img_bytes,
                        width=width,
                        height=height,
                        format=img_format,
                        xref=xref,
                        is_decorative=reason is not None,
                        decorative_reason=reason,
                        perceptual_hash=digest,
                        color_variance=color_variance,
                        coverage_ratio=coverage_ratio,
                    ))
                except Exception as e:
                    logger.debug("Failed to extract image xref=%s on page %d: %s", xref, page_no, e)
                    continue
    finally:
        doc.close()

    logger.info("Extracted %d images from %s", len(images), file_path)
    return images
