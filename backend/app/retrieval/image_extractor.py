"""Extract embedded images from PDF files using PyMuPDF (fitz)."""
from __future__ import annotations

import logging
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

                    images.append(ImageInfo(
                        page_no=page_no,
                        image_bytes=img_bytes,
                        width=width,
                        height=height,
                        format=img_format,
                        xref=xref,
                    ))
                except Exception as e:
                    logger.debug("Failed to extract image xref=%s on page %d: %s", xref, page_no, e)
                    continue
    finally:
        doc.close()

    logger.info("Extracted %d images from %s", len(images), file_path)
    return images
