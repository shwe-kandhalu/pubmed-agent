"""Europe PMC source. Free REST API, no key required. Broader than PubMed (includes preprints) and
supports open-access full text for many PMC-indexed articles."""
import requests

from .common import classify_evidence_tier, parse_jats_xml

KEY = "europepmc"
LABEL = "Europe PMC"

_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def search(query: str, max_results: int = 8) -> list[dict]:
    resp = requests.get(
        _SEARCH,
        params={"query": query, "format": "json", "pageSize": min(max_results, 25)},
        timeout=10,
    )
    resp.raise_for_status()
    papers = []
    for doc in resp.json().get("resultList", {}).get("result", []):
        pub_types = [t.strip() for t in doc.get("pubType", "").split(";") if t.strip()]
        papers.append({
            "id": f"{KEY}:{doc['id']}",
            "source": KEY,
            "title": doc.get("title", ""),
            "authors": doc.get("authorString", ""),
            "year": doc.get("pubYear", ""),
            "doi": doc.get("doi", ""),
            "evidence_tier": classify_evidence_tier(pub_types),
        })
    return papers


def _fetch_core(ext_id: str) -> dict | None:
    resp = requests.get(
        _SEARCH,
        params={"query": f"EXT_ID:{ext_id}", "resultType": "core", "format": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("resultList", {}).get("result", [])
    return results[0] if results else None


def fetch_abstracts(ext_ids: list[str]) -> tuple[str, list[str]]:
    parts, ids = [], []
    for ext_id in ext_ids[:20]:
        doc = _fetch_core(ext_id)
        if not doc:
            parts.append(f"{ext_id}: not found")
            continue
        abstract = doc.get("abstractText", "(no abstract available)")
        parts.append(f"Title: {doc.get('title', '')}\nAuthors: {doc.get('authorString', '')}\nAbstract: {abstract}")
        ids.append(f"{KEY}:{ext_id}")
    return "\n\n".join(parts), ids


def fetch_full_text(ext_ids: list[str]) -> list[dict]:
    results = []
    for ext_id in ext_ids[:5]:
        composite_id = f"{KEY}:{ext_id}"
        doc = _fetch_core(ext_id)
        if not doc:
            results.append({"id": composite_id, "error": "not found"})
            continue
        pmcid = doc.get("pmcid")
        if not pmcid or doc.get("inEPMC") != "Y":
            results.append({"id": composite_id, "error": "no open-access full text available"})
            continue
        try:
            resp = requests.get(_FULLTEXT.format(pmcid=pmcid), timeout=30)
            resp.raise_for_status()
            parsed = parse_jats_xml(f"Europe PMC {ext_id} ({pmcid})", resp.text)
            results.append({"id": composite_id, "text": parsed})
        except Exception as e:
            results.append({"id": composite_id, "error": f"failed to fetch full text — {e}"})
    return results
