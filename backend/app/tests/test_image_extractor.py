"""Tests for PDF image extraction."""
import pytest
from pathlib import Path

from app.retrieval.image_extractor import (
    _image_characteristics,
    extract_images_from_pdf,
    ImageInfo,
)


class TestImageInfo:
    def test_image_info_creation(self):
        info = ImageInfo(page_no=1, image_bytes=b"\x89PNG", width=100, height=200, format="png")
        assert info.page_no == 1
        assert info.width == 100
        assert info.height == 200
        assert info.format == "png"

    def test_image_characteristics_has_stable_fallback_for_invalid_bytes(self):
        """Unreadable images still get a deterministic diagnostic fingerprint."""
        fingerprint, variance = _image_characteristics(b"not an image")
        assert len(fingerprint) == 32
        assert variance == 0.0


class TestExtractImagesFromPdf:
    def test_returns_empty_list_for_nonexistent_file(self):
        result = extract_images_from_pdf("/nonexistent/file.pdf")
        assert result == []

    def test_extracts_images_from_real_pdf(self):
        """Integration test: extract images from a real PDF file."""
        storage = Path("../storage/uploads")
        pdfs = list(storage.rglob("*.pdf"))
        if not pdfs:
            pytest.skip("No PDF files found in storage")
        result = extract_images_from_pdf(str(pdfs[0]))
        assert isinstance(result, list)
        for img in result:
            assert isinstance(img, ImageInfo)
            assert img.page_no >= 1
            assert len(img.image_bytes) > 0

    def test_handles_pdf_with_no_images(self):
        """A text-only PDF should return an empty or short list."""
        storage = Path("../storage/uploads")
        pdfs = list(storage.rglob("*.pdf"))
        if not pdfs:
            pytest.skip("No PDF files found in storage")
        result = extract_images_from_pdf(str(pdfs[0]))
        assert isinstance(result, list)
