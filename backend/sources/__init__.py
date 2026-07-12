"""Registry of literature sources. Each module exposes KEY, LABEL, search(), fetch_abstracts(),
and fetch_full_text() with a uniform signature — add a new source by writing a module with that
shape and registering it below."""
from . import crossref, europepmc, openalex, pubmed, semantic_scholar

SOURCES = {
    pubmed.KEY: pubmed,
    semantic_scholar.KEY: semantic_scholar,
    openalex.KEY: openalex,
    europepmc.KEY: europepmc,
    crossref.KEY: crossref,
}

# Crossref is metadata/DOI-focused with inconsistent abstract coverage and no full text,
# so it's opt-in rather than part of the default multi-source search.
DEFAULT_SEARCH_SOURCES = [pubmed.KEY, semantic_scholar.KEY, openalex.KEY, europepmc.KEY]


def source_list() -> list[dict]:
    return [{"key": mod.KEY, "label": mod.LABEL} for mod in SOURCES.values()]


def parse_id(full_id: str) -> tuple[str, str]:
    if ":" not in full_id:
        raise ValueError(f"Invalid id (expected 'source:native_id'): {full_id}")
    source, native_id = full_id.split(":", 1)
    return source, native_id


def group_by_source(ids: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for full_id in ids:
        source, native_id = parse_id(full_id)
        groups.setdefault(source, []).append(native_id)
    return groups


def paper_url(source: str, native_id: str, doi: str = "") -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if source == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{native_id}/"
    if source == "semantic_scholar":
        return f"https://www.semanticscholar.org/paper/{native_id}"
    if source == "openalex":
        return f"https://openalex.org/{native_id}"
    if source == "europepmc":
        return f"https://europepmc.org/article/MED/{native_id}"
    if source == "crossref":
        return f"https://doi.org/{native_id}"
    return ""
