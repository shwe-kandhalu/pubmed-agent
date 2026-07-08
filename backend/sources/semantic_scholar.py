"""Semantic Scholar source. Free Graph API; optional SEMANTIC_SCHOLAR_API_KEY env var raises rate limits."""
import os

from .common import request_with_retry

KEY = "semantic_scholar"
LABEL = "Semantic Scholar"

_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
_BATCH = "https://api.semanticscholar.org/graph/v1/paper/batch"


def _headers() -> dict:
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": api_key} if api_key else {}


def search(query: str, max_results: int = 8) -> list[dict]:
    resp = request_with_retry(
        "GET",
        _SEARCH,
        params={
            "query": query,
            "limit": min(max_results, 20),
            "fields": "title,authors,year,externalIds",
        },
        headers=_headers(),
        timeout=10,
    )
    papers = []
    for doc in resp.json().get("data", []):
        authors = ", ".join(a.get("name", "") for a in (doc.get("authors") or [])[:3])
        papers.append({
            "id": f"{KEY}:{doc['paperId']}",
            "source": KEY,
            "title": doc.get("title", ""),
            "authors": authors,
            "year": doc.get("year", ""),
            "doi": (doc.get("externalIds") or {}).get("DOI", ""),
        })
    return papers


def fetch_abstracts(paper_ids: list[str]) -> tuple[str, list[str]]:
    if not paper_ids:
        return "", []
    resp = request_with_retry(
        "POST",
        _BATCH,
        params={"fields": "title,abstract,authors,year"},
        json={"ids": paper_ids[:20]},
        headers=_headers(),
        timeout=15,
    )
    parts, ids = [], []
    for doc in resp.json():
        if not doc:
            continue
        authors = ", ".join(a.get("name", "") for a in (doc.get("authors") or [])[:3])
        abstract = doc.get("abstract") or "(no abstract available)"
        parts.append(
            f"Title: {doc.get('title', '')}\nAuthors: {authors}\nYear: {doc.get('year', '')}\nAbstract: {abstract}"
        )
        ids.append(f"{KEY}:{doc['paperId']}")
    return "\n\n".join(parts), ids


def fetch_full_text(paper_ids: list[str]) -> list[dict]:
    if not paper_ids:
        return []
    resp = request_with_retry(
        "POST",
        _BATCH,
        params={"fields": "title,openAccessPdf"},
        json={"ids": paper_ids[:5]},
        headers=_headers(),
        timeout=15,
    )
    results = []
    for doc in resp.json():
        if not doc:
            continue
        composite_id = f"{KEY}:{doc['paperId']}"
        pdf = (doc.get("openAccessPdf") or {}).get("url")
        if pdf:
            results.append({"id": composite_id, "error": f"full text not extractable via API; open-access PDF: {pdf}"})
        else:
            results.append({"id": composite_id, "error": "no open-access full text available"})
    return results
