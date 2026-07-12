"""PubMed / PubMed Central source. E-utilities API, no key required (NCBI rate-limits by IP)."""
import requests

from .common import classify_evidence_tier, parse_jats_xml

KEY = "pubmed"
LABEL = "PubMed"

_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_ELINK = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"


def search(query: str, max_results: int = 8) -> list[dict]:
    resp = requests.get(
        _ESEARCH,
        params={
            "db": "pubmed",
            "term": query,
            "retmax": min(max_results, 20),
            "retmode": "json",
            "sort": "relevance",
        },
        timeout=10,
    )
    resp.raise_for_status()
    pmids = resp.json()["esearchresult"]["idlist"]
    if not pmids:
        return []

    resp = requests.get(
        _ESUMMARY,
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
        timeout=10,
    )
    resp.raise_for_status()
    summary = resp.json().get("result", {})

    papers = []
    for pmid in pmids:
        doc = summary.get(pmid, {})
        authors = ", ".join(a.get("name", "") for a in doc.get("authors", [])[:3])
        papers.append({
            "id": f"{KEY}:{pmid}",
            "source": KEY,
            "title": doc.get("title", ""),
            "authors": authors,
            "year": (doc.get("pubdate", "") or "")[:4],
            "doi": next((eid.get("value", "") for eid in doc.get("articleids", []) if eid.get("idtype") == "doi"), ""),
            "evidence_tier": classify_evidence_tier(doc.get("pubtype", [])),
        })
    return papers


def fetch_abstracts(pmids: list[str]) -> tuple[str, list[str]]:
    if not pmids:
        return "", []
    resp = requests.get(
        _EFETCH,
        params={"db": "pubmed", "id": ",".join(pmids[:20]), "rettype": "abstract", "retmode": "text"},
        timeout=15,
    )
    resp.raise_for_status()
    ids = [f"{KEY}:{pmid}" for pmid in pmids[:20]]
    return resp.text, ids


def _get_pmcid(pmid: str) -> str | None:
    try:
        resp = requests.get(
            _ELINK,
            params={"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        for linkset in data.get("linksets", []):
            for linksetdb in linkset.get("linksetdbs", []):
                if linksetdb.get("linkname") == "pubmed_pmc":
                    links = linksetdb.get("links", [])
                    if links:
                        return str(links[0])
    except Exception:
        pass
    return None


def fetch_full_text(pmids: list[str]) -> list[dict]:
    results = []
    for pmid in pmids[:5]:
        composite_id = f"{KEY}:{pmid}"
        pmcid = _get_pmcid(pmid)
        if not pmcid:
            results.append({"id": composite_id, "error": "not in PubMed Central (abstract only)"})
            continue
        try:
            resp = requests.get(
                _EFETCH,
                params={"db": "pmc", "id": pmcid, "rettype": "full", "retmode": "xml"},
                timeout=30,
            )
            resp.raise_for_status()
            parsed = parse_jats_xml(f"PMID {pmid} (PMC{pmcid})", resp.text)
            results.append({"id": composite_id, "text": parsed})
        except Exception as e:
            results.append({"id": composite_id, "error": f"failed to fetch full text — {e}"})
    return results
