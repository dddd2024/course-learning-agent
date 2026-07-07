"""Material overview endpoint — objective, verifiable stats (Phase 2 Task C).

``GET /api/v1/materials/{material_id}/overview`` returns chunk_count,
page_range, section_count, top keywords, and rule-based warnings.

No quality grade, no A/B/C score, no percentage — only counts and
ranges the user can verify against the database.
"""
import re
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.schemas.material_overview import MaterialOverviewResponse

router = APIRouter()

# Minimal Chinese/English stopword list for keyword extraction.
_STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "或", "也", "都", "但", "而",
    "这", "那", "它", "他", "她", "我", "你", "们", "一个", "可以",
    "用于", "通过", "进行", "以及", "例如", "如下", "如果", "因为",
    "所以", "但是", "虽然", "然而", "如图", "所示", "其中", "上述",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "and", "or", "but", "if", "then", "for", "of", "to", "in",
    "on", "at", "by", "with", "from", "as", "this", "that", "it",
}

# Token pattern: Chinese chars (2+ for meaningful words) or ASCII words
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_]{2,}")


def _get_owned_material(
    db: Session, material_id: int, user_id: int
) -> Material:
    material = (
        db.query(Material)
        .filter(Material.id == material_id, Material.user_id == user_id)
        .first()
    )
    if material is None:
        raise NotFoundException(message="资料不存在")
    return material


def _extract_keywords(texts: list[str], top_n: int = 10) -> list[str]:
    """Simple frequency-based keyword extraction from a list of texts."""
    counter: Counter[str] = Counter()
    for text in texts:
        if not text:
            continue
        for m in _TOKEN_RE.finditer(text.lower()):
            token = m.group(0)
            if token in _STOPWORDS:
                continue
            counter[token] += 1
    return [w for w, _ in counter.most_common(top_n)]


def _build_warnings(chunks: list[MaterialChunk]) -> list[str]:
    """Rule-based, objective warnings — no quality grade."""
    warnings: list[str] = []
    short = [c for c in chunks if (c.token_count or 0) < 20]
    if short:
        warnings.append(f"发现 {len(short)} 个过短片段")
    no_page = [c for c in chunks if c.page_no is None]
    if no_page:
        warnings.append(f"未识别到 {len(no_page)} 个片段的页码")
    no_title = [c for c in chunks if not c.title]
    if no_title:
        warnings.append(f"有 {len(no_title)} 个片段缺少章节标题")
    return warnings


@router.get(
    "/{material_id}/overview",
    response_model=MaterialOverviewResponse,
)
def get_material_overview(
    material_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialOverviewResponse:
    """Return an objective overview of a parsed material."""
    material = _get_owned_material(db, material_id, current_user.id)
    chunks = (
        db.query(MaterialChunk)
        .filter(MaterialChunk.material_id == material_id)
        .order_by(MaterialChunk.chunk_index.asc())
        .all()
    )

    # Page range
    pages = [c.page_no for c in chunks if c.page_no is not None]
    page_range = [min(pages), max(pages)] if pages else None

    # Section count (distinct titles)
    titles = {c.title for c in chunks if c.title}
    section_count = len(titles)

    # Keywords from keyword_text (cleaned text) — cheaper than full text
    keyword_texts = [c.keyword_text or c.text or "" for c in chunks]
    keywords = _extract_keywords(keyword_texts)

    # Warnings
    warnings = _build_warnings(chunks)

    # Security findings count (Task D) — best-effort, table may not exist
    security_count = 0
    try:
        from app.models.security_finding import MaterialSecurityFinding

        security_count = (
            db.query(MaterialSecurityFinding)
            .filter(MaterialSecurityFinding.material_id == material_id)
            .count()
        )
    except Exception:
        pass

    return MaterialOverviewResponse(
        material_id=material_id,
        status=material.status or "unknown",
        chunk_count=len(chunks),
        page_range=page_range,
        section_count=section_count,
        keywords=keywords,
        warnings=warnings,
        security_findings_count=security_count,
    )
