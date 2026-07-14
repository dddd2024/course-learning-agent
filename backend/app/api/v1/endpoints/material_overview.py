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
from app.core.exceptions import BusinessException, NotFoundException
from app.agents.audit import AgentAudit
from app.agents.llm import call_llm_with_meta
from app.models.material import Material
from app.models.material_chunk import MaterialChunk
from app.models.user import User
from app.schemas.material_overview import MaterialOverviewResponse, MaterialStudyGuideResponse
from app.services.llm_config_service import build_user_config, get_active_config
from app.services.material_identity_service import resolve_owned_material

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
    db: Session, material_id: str | int, user_id: int
) -> Material:
    material = resolve_owned_material(db, material_id, user_id)
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


def _sample_chunks_by_page(chunks: list[MaterialChunk], limit: int = 12) -> list[MaterialChunk]:
    """Sample evidence across pages instead of truncating to the first chunks."""
    usable = [chunk for chunk in chunks if chunk.is_active and chunk.is_indexable]
    if len(usable) <= limit:
        return usable
    by_page: dict[int, MaterialChunk] = {}
    for chunk in usable:
        by_page.setdefault(chunk.page_no or 0, chunk)
    candidates = list(by_page.values())
    if len(candidates) >= limit:
        step = (len(candidates) - 1) / (limit - 1)
        return [candidates[round(index * step)] for index in range(limit)]
    remaining = [chunk for chunk in usable if chunk not in candidates]
    return (candidates + remaining)[:limit]


@router.get(
    "/{material_id}/overview",
    response_model=MaterialOverviewResponse,
)
def get_material_overview(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialOverviewResponse:
    """Return an objective overview of a parsed material."""
    material = _get_owned_material(db, material_id, current_user.id)
    chunks = (
        db.query(MaterialChunk)
        .filter(MaterialChunk.material_id == material.id)
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
            .filter(MaterialSecurityFinding.material_id == material.id)
            .count()
        )
    except Exception:
        pass

    return MaterialOverviewResponse(
        material_id=material.id,
        status=material.status or "unknown",
        chunk_count=len(chunks),
        page_range=page_range,
        section_count=section_count,
        keywords=keywords,
        warnings=warnings,
        security_findings_count=security_count,
    )


@router.post("/{material_id}/study-guide", response_model=MaterialStudyGuideResponse)
def generate_material_study_guide(
    material_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MaterialStudyGuideResponse:
    """Generate a guide from evenly sampled active evidence, never chat text."""
    material = _get_owned_material(db, material_id, current_user.id)
    chunks = db.query(MaterialChunk).filter(
        MaterialChunk.material_id == material.id,
        MaterialChunk.is_active == 1,
        MaterialChunk.is_indexable == 1,
    ).order_by(MaterialChunk.chunk_index.asc()).all()
    samples = _sample_chunks_by_page(chunks)
    if not samples:
        raise BusinessException(message="资料没有可用正文证据，无法生成内容速览")
    evidence_ids = [chunk.id for chunk in samples]
    evidence_text = "\n\n".join(
        f"[证据{index} id={chunk.id} page={chunk.page_no or '未知'}]\n{chunk.text[:700]}"
        for index, chunk in enumerate(samples, start=1)
    )
    config = get_active_config(db, current_user.id)
    user_config = build_user_config(config) if config else None
    run = AgentAudit.create_run(
        db, user_id=current_user.id, run_type="material_overview",
        input_summary={"material_id": material.id, "evidence_ids": evidence_ids},
        prompt_version="material_overview_v1",
        model_name=(config.model if config else "mock"),
        provider=("user" if config else "mock"), config_id=(config.id if config else None),
    )
    prompt = (
        "你是课程资料速览助手。只能依据下列证据生成 Markdown 速览，首句必须说明覆盖范围，"
        "不得添加证据外事实。严格返回 JSON：{\"answer\":\"...\"}。\n\n" + evidence_text
    )
    output, meta = call_llm_with_meta(prompt, "material_overview", user_config=user_config)
    AgentAudit.update_run_meta(db, run.id, meta.get("actual_model"), meta.get("actual_provider"), meta)
    answer = str(output.get("answer") or "资料不足，无法生成内容速览。")
    AgentAudit.finish_run(
        db, run.id, status="degraded" if meta.get("degraded") else "success",
        output_summary={"evidence_ids": evidence_ids, "provider": meta.get("actual_provider")},
    )
    db.commit()
    return MaterialStudyGuideResponse(
        material_id=material.id, answer=answer, evidence_ids=evidence_ids,
        sampled_pages=sorted({chunk.page_no for chunk in samples if chunk.page_no is not None}),
        coverage_note=f"本速览均匀抽样了 {len(samples)} 个证据片段，不代表整份资料的完整覆盖。",
        provider=meta.get("actual_provider", meta.get("provider", "mock")),
        fallback_used=bool(meta.get("fallback_used")), fallback_reason=meta.get("fallback_reason"),
        agent_run_id=run.id,
    )
