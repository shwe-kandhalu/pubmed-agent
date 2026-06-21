import anthropic
import json
import requests
import sys
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

TOOLS = [
    {
        "name": "search_pubmed",
        "description": (
            "Search PubMed for scientific papers matching a query. "
            "Returns PubMed IDs (PMIDs). You may search multiple times with "
            "different queries to improve coverage or when initial results are sparse."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'bilingual cognitive reserve ADRD')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max papers to return (default 8, max 20)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_abstracts",
        "description": (
            "Fetch titles and abstracts for a list of PubMed IDs. "
            "Use this to screen papers for relevance before deciding which to read in full."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pmids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of PubMed IDs to fetch (up to 20)",
                }
            },
            "required": ["pmids"],
        },
    },
    {
        "name": "fetch_full_text",
        "description": (
            "Fetch full text (methods, results, discussion) for papers available in "
            "PubMed Central. Use this on the 2–3 most relevant papers after screening "
            "abstracts. Not all papers are in PMC — the tool reports which are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pmids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of PubMed IDs to fetch full text for (up to 5)",
                }
            },
            "required": ["pmids"],
        },
    },
]


def search_pubmed(query: str, max_results: int = 8) -> dict:
    resp = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        params={
            "db": "pubmed",
            "term": query,
            "retmax": min(max_results, 20),
            "retmode": "json",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "pmids": data["esearchresult"]["idlist"],
        "total_found": int(data["esearchresult"]["count"]),
    }


def fetch_abstracts(pmids: list[str]) -> str:
    if not pmids:
        return "No PMIDs provided."
    resp = requests.get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        params={
            "db": "pubmed",
            "id": ",".join(pmids[:20]),
            "rettype": "abstract",
            "retmode": "text",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text


def _get_text(el) -> str:
    return " ".join(el.itertext()).strip()


def _truncate(text: str, max_chars: int = 1500) -> str:
    return text[:max_chars] + "..." if len(text) > max_chars else text


def _get_pmcid(pmid: str) -> str | None:
    try:
        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
            params={
                "dbfrom": "pubmed",
                "db": "pmc",
                "id": pmid,
                "retmode": "json",
            },
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


def _parse_pmc_xml(pmid: str, pmcid: str, xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        return f"PMID {pmid}: XML parse error — {e}"

    parts = [f"=== PMID {pmid} (PMC{pmcid}) ==="]

    title_el = root.find(".//article-title")
    if title_el is not None:
        parts.append(f"Title: {_get_text(title_el)}")

    abstract_el = root.find(".//abstract")
    if abstract_el is not None:
        parts.append(f"Abstract: {_truncate(_get_text(abstract_el), 800)}")

    body = root.find(".//body")
    if body is not None:
        TARGET = {"RESULT", "DISCUSSION", "CONCLUSION", "METHOD", "FINDING"}
        for sec in body.findall(".//sec"):
            sec_title_el = sec.find("title")
            if sec_title_el is None:
                continue
            sec_title = _get_text(sec_title_el)
            if not any(kw in sec_title.upper() for kw in TARGET):
                continue
            paras = sec.findall("p")
            sec_text = " ".join(_get_text(p) for p in paras)
            if sec_text:
                parts.append(f"\n{sec_title}:\n{_truncate(sec_text, 1500)}")

    return "\n".join(parts)


def fetch_full_text(pmids: list[str]) -> str:
    pmids = pmids[:5]
    pmid_to_pmcid: dict[str, str] = {}
    for pmid in pmids:
        pmcid = _get_pmcid(pmid)
        if pmcid:
            pmid_to_pmcid[pmid] = pmcid

    unavailable = [p for p in pmids if p not in pmid_to_pmcid]
    results = []

    if unavailable:
        results.append(f"Note: not in PMC (abstract only): {', '.join(unavailable)}")

    if not pmid_to_pmcid:
        return results[0] if results else "None of the requested papers are in PubMed Central."

    for pmid, pmcid in pmid_to_pmcid.items():
        try:
            resp = requests.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                params={
                    "db": "pmc",
                    "id": pmcid,
                    "rettype": "full",
                    "retmode": "xml",
                },
                timeout=30,
            )
            resp.raise_for_status()
            results.append(_parse_pmc_xml(pmid, pmcid, resp.text))
        except Exception as e:
            results.append(f"PMID {pmid}: failed to fetch full text — {e}")

    return "\n\n---\n\n".join(results)


def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "search_pubmed":
        return json.dumps(search_pubmed(inputs["query"], inputs.get("max_results", 8)))
    if name == "fetch_abstracts":
        return fetch_abstracts(inputs["pmids"])
    if name == "fetch_full_text":
        return fetch_full_text(inputs["pmids"])
    return f"Unknown tool: {name}"


SYSTEM = """
You are a genomics research assistant specializing in clinical genetics.

Strategy:
- Search iteratively: if initial results are sparse or off-topic, refine the query and search again with different terms (up to 3 searches total).
- After searching, fetch abstracts to screen for relevance.
- For the 2–3 most relevant papers, call fetch_full_text to retrieve methods, results, and discussion from PubMed Central. Not all papers are in PMC; the tool reports which are available.

Report format (under 600 words):
- Key Findings (cite PMIDs)
- Common Themes
- Clinical Implications
- Research Gaps

Prioritize depth over breadth: synthesize a few papers well rather than listing many superficially.
""".strip()

EXAMPLE_QUERIES = [
    "expanded carrier screening panel clinical utility outcomes",
    "cell-free DNA prenatal screening NIPT performance",
    "BRCA1 BRCA2 pathogenic variant population frequency",
    "liquid biopsy ctDNA early detection sensitivity specificity",
]


def run(question: str) -> None:
    messages = [{"role": "user", "content": question}]
    MAX_STEPS = 10

    for _ in range(MAX_STEPS):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

        print("stop_reason:", response.stop_reason)
        for block in response.content:
            print("block type:", block.type)

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []

        for block in response.content:
            if block.type == "tool_use":
                print(f"[{block.name}] {json.dumps(block.input)[:120]}")
                result = dispatch_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            elif block.type == "text":
                print(block.text)

        if not tool_results:
            return

        messages.append({"role": "user", "content": tool_results})

    print("Reached maximum tool iterations.")


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print("Example queries:")
        for q in EXAMPLE_QUERIES:
            print(f"  - {q}")
        print()
        question = input("Research question: ").strip()
    if not question:
        sys.exit("Please provide a research question.")
    print()
    run(question)
