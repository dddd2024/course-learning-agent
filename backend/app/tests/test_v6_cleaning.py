"""V6-13: Unify cleaning rules and fix technical terms.

Tests verify that:
- Technical terms (TCP/IP, CSMA/CD, HTTP/2, I/O) are NOT removed by the
  URL cleaning rule.
- Actual URLs (http://, https://, ftp://, www.) ARE removed.
- Page numbers and repeated headers/footers are removed.
- Short single-line titles are NOT removed (not too aggressive).
- Cleaning decisions are recorded in a user-friendly format.
- Raw pages show uncleaned text and clean pages show cleaned text.
"""
import json

from app.models.material import Material
from app.models.material_page import MaterialPage
from app.services.material_cleaner import (
    CleanPage,
    clean_pages,
    get_clean_pages,
    get_cleaning_decisions,
    get_raw_pages,
)


# ---------------------------------------------------------------------------
# Pure-function tests for clean_pages() — no DB needed
# ---------------------------------------------------------------------------

def test_tcp_ip_not_removed_by_url_cleaning():
    """TCP/IP is a protocol name, not a URL — must survive cleaning."""
    pages = clean_pages(["TCP/IP 协议是互联网的基础"])
    assert "TCP/IP" in pages[0].text


def test_csma_cd_not_removed_by_url_cleaning():
    """CSMA/CD is a protocol name, not a URL — must survive cleaning."""
    pages = clean_pages(["CSMA/CD 是局域网中使用的介质访问控制协议"])
    assert "CSMA/CD" in pages[0].text


def test_http2_not_removed_by_url_cleaning():
    """HTTP/2 is a protocol version, not a URL — must survive cleaning."""
    pages = clean_pages(["HTTP/2 引入了多路复用和头部压缩"])
    assert "HTTP/2" in pages[0].text


def test_io_not_removed_by_url_cleaning():
    """I/O is a standard abbreviation, not a URL — must survive cleaning."""
    pages = clean_pages(["I/O 系统是操作系统的重要组成部分"])
    assert "I/O" in pages[0].text


def test_actual_urls_are_removed():
    """Lines that are actual URLs must be removed by cleaning."""
    pages = clean_pages([
        "http://example.com/page1\n"
        "Some content here\n"
        "https://test.org/resource\n"
        "ftp://files.example.com/file.txt\n"
        "www.example.com\n"
        "More content"
    ])
    text = pages[0].text
    assert "http://example.com" not in text
    assert "https://test.org" not in text
    assert "ftp://files.example.com" not in text
    assert "www.example.com" not in text
    # Legitimate content must survive
    assert "Some content here" in text
    assert "More content" in text


def test_page_numbers_are_removed():
    """Isolated page numbers must be removed."""
    pages = clean_pages(["Introduction\n12\nConclusion"])
    text = pages[0].text
    assert "12" not in text.split("\n")
    assert "Introduction" in text
    assert "Conclusion" in text


def test_repeated_headers_footers_are_removed():
    """Lines repeated as first/last on multiple pages are header/footer."""
    pages = clean_pages([
        "Course Header\nPage 1 content\nCourse Footer",
        "Course Header\nPage 2 content\nCourse Footer",
    ])
    for p in pages:
        assert "Course Header" not in p.text
        assert "Course Footer" not in p.text
    assert "Page 1 content" in pages[0].text
    assert "Page 2 content" in pages[1].text


def test_short_single_line_titles_not_removed():
    """Short content lines that are not noise must survive cleaning.

    A single page with a short title like 'TCP/IP' must not be treated
    as a repeated header (it only appears on one page).
    """
    pages = clean_pages(["TCP/IP"])
    assert "TCP/IP" in pages[0].text


def test_file_path_not_removed_as_url():
    """File paths with forward slashes are not URLs — must survive.

    C:/Users/... is a file path, not a URL. The cleaner should not
    remove it as a standalone_url.
    """
    pages = clean_pages(["File: C:/Users/student/notes.txt"])
    # The line contains content beyond just a URL, so it's kept
    assert "C:/Users" in pages[0].text


# ---------------------------------------------------------------------------
# get_cleaning_decisions() tests
# ---------------------------------------------------------------------------

def test_cleaning_decisions_recorded_with_all_fields():
    """get_cleaning_decisions returns user-friendly decision dicts.

    Each decision must include: original_line, action, reason, cleaned_line.
    """
    pages = clean_pages([
        "http://example.com\n"
        "TCP/IP protocol overview\n"
        "42\n"
        "TCP/IP protocol overview\n"
    ])
    decisions = get_cleaning_decisions(pages[0])

    assert isinstance(decisions, list)
    assert len(decisions) == 4

    # Every decision must have the required fields
    for d in decisions:
        assert "original_line" in d
        assert "action" in d
        assert "reason" in d
        assert "cleaned_line" in d

    # The URL line should be removed
    url_decision = next(d for d in decisions if "example.com" in d["original_line"])
    assert url_decision["action"] == "removed"
    assert url_decision["reason"] == "standalone_url"
    assert url_decision["cleaned_line"] is None

    # The page number should be removed
    page_num_decision = next(d for d in decisions if d["original_line"] == "42")
    assert page_num_decision["action"] == "removed"
    assert page_num_decision["reason"] == "isolated_page_number"
    assert page_num_decision["cleaned_line"] is None

    # The first TCP/IP line should be kept
    kept = [d for d in decisions if d["action"] == "kept"]
    assert len(kept) >= 1
    for k in kept:
        assert k["cleaned_line"] == k["original_line"]
        assert k["reason"] == "semantic_content"

    # The duplicate TCP/IP line should be merged
    merged = [d for d in decisions if d["action"] == "merged"]
    assert len(merged) >= 1
    for m in merged:
        assert m["reason"] == "adjacent_duplicate"
        assert m["cleaned_line"] is None


def test_cleaning_decisions_kept_lines_have_cleaned_line():
    """Kept lines must have cleaned_line equal to the original line."""
    pages = clean_pages(["Hello World"])
    decisions = get_cleaning_decisions(pages[0])
    assert len(decisions) == 1
    d = decisions[0]
    assert d["action"] == "kept"
    assert d["cleaned_line"] == "Hello World"


def test_cleaning_decisions_removed_lines_have_none_cleaned_line():
    """Removed lines must have cleaned_line = None."""
    pages = clean_pages(["http://example.com\nReal content"])
    decisions = get_cleaning_decisions(pages[0])
    url_d = next(d for d in decisions if "example.com" in d["original_line"])
    assert url_d["action"] == "removed"
    assert url_d["cleaned_line"] is None


# ---------------------------------------------------------------------------
# DB-based tests for get_raw_pages() and get_clean_pages()
# ---------------------------------------------------------------------------

def _create_material_with_pages(db_session, sample_course, sample_user):
    """Helper: create a Material with MaterialPage rows for testing."""
    material = Material(
        user_id=sample_user.id,
        course_id=sample_course.id,
        filename="test.pdf",
        file_type="pdf",
        file_path="test/test.pdf",
        status="ready",
    )
    db_session.add(material)
    db_session.flush()

    # Page 1: raw has noise, clean has noise removed
    db_session.add(MaterialPage(
        material_id=material.id,
        page_no=1,
        page_type="text",
        parser_version="legacy",
        raw_text="http://example.com\nTCP/IP protocol\n42",
        clean_text="TCP/IP protocol",
        decisions_json=json.dumps([
            {"raw_text": "http://example.com", "decision": "removed", "reason": "standalone_url"},
            {"raw_text": "TCP/IP protocol", "decision": "kept", "reason": "semantic_content"},
            {"raw_text": "42", "decision": "removed", "reason": "isolated_page_number"},
        ]),
    ))

    # Page 2: raw has header/footer, clean has them removed
    db_session.add(MaterialPage(
        material_id=material.id,
        page_no=2,
        page_type="text",
        parser_version="legacy",
        raw_text="Course Header\nCSMA/CD protocol\nCourse Footer",
        clean_text="CSMA/CD protocol",
        decisions_json=json.dumps([
            {"raw_text": "Course Header", "decision": "removed", "reason": "repeated_header_footer"},
            {"raw_text": "CSMA/CD protocol", "decision": "kept", "reason": "semantic_content"},
            {"raw_text": "Course Footer", "decision": "removed", "reason": "repeated_header_footer"},
        ]),
    ))

    db_session.commit()
    return material


def test_get_raw_pages_returns_uncleaned_text(db_session, sample_course, sample_user):
    """get_raw_pages returns the raw (uncleaned) text for each page."""
    material = _create_material_with_pages(db_session, sample_course, sample_user)
    raw_pages = get_raw_pages(material.id, db_session)

    assert len(raw_pages) == 2
    assert raw_pages[0]["page_no"] == 1
    assert "http://example.com" in raw_pages[0]["text"]
    assert "42" in raw_pages[0]["text"]
    assert raw_pages[1]["page_no"] == 2
    assert "Course Header" in raw_pages[1]["text"]


def test_get_clean_pages_returns_cleaned_text(db_session, sample_course, sample_user):
    """get_clean_pages returns only the cleaned text (noise removed)."""
    material = _create_material_with_pages(db_session, sample_course, sample_user)
    clean_pages_result = get_clean_pages(material.id, db_session)

    assert len(clean_pages_result) == 2
    assert clean_pages_result[0]["page_no"] == 1
    # Clean text should NOT contain the URL or page number
    assert "http://example.com" not in clean_pages_result[0]["text"]
    assert "42" not in clean_pages_result[0]["text"]
    assert "TCP/IP protocol" in clean_pages_result[0]["text"]

    assert clean_pages_result[1]["page_no"] == 2
    assert "Course Header" not in clean_pages_result[1]["text"]
    assert "CSMA/CD protocol" in clean_pages_result[1]["text"]


def test_raw_and_clean_pages_are_different(db_session, sample_course, sample_user):
    """Raw and clean pages must differ when noise was removed."""
    material = _create_material_with_pages(db_session, sample_course, sample_user)
    raw_pages = get_raw_pages(material.id, db_session)
    clean_pages_result = get_clean_pages(material.id, db_session)

    for raw, clean in zip(raw_pages, clean_pages_result):
        assert raw["text"] != clean["text"], (
            "Raw and clean text should differ when noise was removed"
        )
