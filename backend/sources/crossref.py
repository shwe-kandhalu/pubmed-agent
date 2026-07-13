"""Crossref source. Free API, no key required. Best for DOI/metadata resolution: abstract coverage
is inconsistent and it has no full text, so it's excluded from the default multi-source search."""
import re
import requests

KEY = "crossref"
LABEL = "Crossref"

_WORKS = "https://api.crossref.org/works"
_JATS_TAG = re.compile(r"<[^>]+>")


def search(query: str, max_results: int = 8) -> list[dict]:
    resp = requests.get(
        _WORKS,
        params={"query": query, "rows": min(max_results, 20)},
        timeout=10,
    )
    resp.raise_for_status()
    papers = []
    for doc in resp.json().get("message", {}).get("items", []):
        titles = doc.get("title") or []
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip() for a in (doc.get("author") or [])[:3]
        )
        year = ""
        date_parts = (doc.get("issued", {}) or {}).get("date-parts", [[]])
        if date_parts and date_parts[0]:
            year = date_parts[0][0]
        papers.append({
            "id": f"{KEY}:{doc['DOI']}",
            "source": KEY,
            "title": titles[0] if titles else "",
            "authors": authors,
            "year": year,
            "doi": doc["DOI"],
            "evidence_tier": "unclassified",
        })
    return papers


def fetch_abstracts(dois: list[str]) -> tuple[str, list[str]]:
    parts, ids = [], []
    for doi in dois[:20]:
        try:
            resp = requests.get(f"{_WORKS}/{doi}", timeout=10)
            resp.raise_for_status()
            doc = resp.json()["message"]
        except Exception as e:
            parts.append(f"{doi}: failed to fetch: {e}")
            continue
        titles = doc.get("title") or []
        raw_abstract = doc.get("abstract")
        abstract = _JATS_TAG.sub("", raw_abstract).strip() if raw_abstract else \
            "(Crossref has no abstract for this DOI: it primarily provides bibliographic metadata)"
        parts.append(f"Title: {titles[0] if titles else ''}\nDOI: {doi}\nAbstract: {abstract}")
        ids.append(f"{KEY}:{doi}")
    return "\n\n".join(parts), ids


def fetch_full_text(dois: list[str]) -> list[dict]:
    return [
        {"id": f"{KEY}:{doi}", "error": "Crossref does not provide full text: use its DOI to locate the publisher page"}
        for doi in dois[:5]
    ]
