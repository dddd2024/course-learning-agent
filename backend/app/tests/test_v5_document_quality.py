from app.retrieval.chunker import build_chunks, clean_material_text
from app.retrieval.parsers import ParsedPage, TextBlock

def test_page_semantics_keep_title_and_remove_footer_noise():
    page = ParsedPage(1, [TextBlock("虚拟内存", (0, 0, 10, 10), 24, "title"), TextBlock("TLB 是页表高速缓存。", (0, 20, 10, 30)), TextBlock("第 1 页", (0, 90, 10, 100), block_type="footer")], "pdf")
    chunks = build_chunks([page])
    assert chunks[0]["page_no"] == 1 and chunks[0]["text"].startswith("虚拟内存")
    assert "第 1 页" not in clean_material_text(chunks[0]["text"])
