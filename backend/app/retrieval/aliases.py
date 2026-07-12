"""Small, auditable course terminology aliases used by lexical retrieval."""
ALIASES = {
    "快表": ["TLB", "translation lookaside buffer"],
    "tlb": ["快表"],
    "自动重传请求": ["ARQ"],
    "arq": ["自动重传请求"],
}


def expand(query: str) -> list[str]:
    lowered = (query or "").lower()
    values = [query]
    for key, alternatives in ALIASES.items():
        if key in lowered:
            values.extend(alternatives)
    return list(dict.fromkeys(value for value in values if value))
