"""OpenAlex source. Free, open catalog. Anonymous search is heavily rate-limited (OpenAlex now
returns 503s under load without one) — set OPENALEX_API_KEY (free, from openalex.org) for reliable
access, and optionally OPENALEX_MAILTO to also join the 'polite pool'."""
import os

from .common import request_with_retry

KEY = "openalex"
LABEL = "OpenAlex"

_WORKS = "https://api.openalex.org/works"


def _params(extra: dict) -> dict:
    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        extra["mailto"] = mailto
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        extra["api_key"] = api_key
    return extra


def _short_id(openalex_url: str) -> str:
    return openalex_url.rsplit("/", 1)[-1]


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return "(no abstract available)"
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def search(query: str, max_results: int = 8) -> list[dict]:
    resp = request_with_retry(
        "GET",
        _WORKS,
        params=_params({"search": query, "per-page": min(max_results, 20)}),
        timeout=10,
    )
    papers = []
    for doc in resp.json().get("results", []):
        authors = ", ".join(
            (a.get("author") or {}).get("display_name", "") for a in (doc.get("authorships") or [])[:3]
        )
        papers.append({
            "id": f"{KEY}:{_short_id(doc['id'])}",
            "source": KEY,
            "title": doc.get("display_name", ""),
            "authors": authors,
            "year": doc.get("publication_year", ""),
            "doi": (doc.get("doi") or "").replace("https://doi.org/", ""),
            "evidence_tier": "unclassified",
        })
    return papers


def fetch_abstracts(work_ids: list[str]) -> tuple[str, list[str]]:
    parts, ids = [], []
    for work_id in work_ids[:20]:
        try:
            resp = request_with_retry("GET", f"{_WORKS}/{work_id}", params=_params({}), timeout=10)
            doc = resp.json()
        except Exception as e:
            parts.append(f"{work_id}: failed to fetch — {e}")
            continue
        authors = ", ".join(
            (a.get("author") or {}).get("display_name", "") for a in (doc.get("authorships") or [])[:3]
        )
        abstract = _reconstruct_abstract(doc.get("abstract_inverted_index"))
        parts.append(
            f"Title: {doc.get('display_name', '')}\nAuthors: {authors}\n"
            f"Year: {doc.get('publication_year', '')}\nAbstract: {abstract}"
        )
        ids.append(f"{KEY}:{work_id}")
    return "\n\n".join(parts), ids


def fetch_full_text(work_ids: list[str]) -> list[dict]:
    results = []
    for work_id in work_ids[:5]:
        composite_id = f"{KEY}:{work_id}"
        try:
            resp = request_with_retry("GET", f"{_WORKS}/{work_id}", params=_params({}), timeout=10)
            doc = resp.json()
        except Exception as e:
            results.append({"id": composite_id, "error": f"failed to fetch — {e}"})
            continue
        oa_url = (doc.get("open_access") or {}).get("oa_url") or (doc.get("best_oa_location") or {}).get("pdf_url")
        if oa_url:
            results.append({"id": composite_id, "error": f"full text not extractable via API; open-access link: {oa_url}"})
        else:
            results.append({"id": composite_id, "error": "no open-access full text available"})
    return results
