"""Render PDF pages into deterministic, hash-addressed visual assets."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenderedPage:
    page_no: int
    filename: str
    width: int
    height: int
    dpi: int
    sha256: str


def render_pdf_pages(source: str | Path, output_dir: str | Path, *, dpi: int = 144) -> list[RenderedPage]:
    """Render every PDF page as PNG without relying on embedded image objects."""
    import fitz

    source_path = Path(source)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72
    results: list[RenderedPage] = []
    with fitz.open(source_path) as document:
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            payload = pixmap.tobytes("png")
            digest = hashlib.sha256(payload).hexdigest()
            filename = f"page-{index:04d}-{digest[:12]}.png"
            (target / filename).write_bytes(payload)
            results.append(RenderedPage(index, filename, pixmap.width, pixmap.height, dpi, digest))
    return results
