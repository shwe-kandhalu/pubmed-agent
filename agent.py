import anthropic
import json
import requests
import sys
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic()

TOOLS = [
    {
        "name": "search_pubmed",
        "description": (
            "Search PubMed for scientific papers matching a query. "
            "Returns PubMed IDs (PMIDs). Call this first to find relevant papers."
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
            "Call this after search_pubmed to read the actual paper content."
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
            "id": ",".join(pmids[:10]),
            "rettype": "abstract",
            "retmode": "text",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.text


def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "search_pubmed":
        return json.dumps(search_pubmed(inputs["query"], inputs.get("max_results", 8)))
    if name == "fetch_abstracts":
        return fetch_abstracts(inputs["pmids"])
    return f"Unknown tool: {name}"


SYSTEM = """
You are a genomics research assistant specializing in clinical genetics.

Workflow:
1. Call search_pubmed exactly once.
2. Choose at most 10 relevant PMIDs.
3. Call fetch_abstracts exactly once.
4. Produce a concise report with:
   - Key Findings
   - Common Themes
   - Clinical Implications
   - Research Gaps

Do not perform multiple searches unless the first search returns zero papers.
Keep the response under 500 words.
Include PMIDs when referencing findings.
"""

EXAMPLE_QUERIES = [
    "expanded carrier screening panel clinical utility outcomes",
    "cell-free DNA prenatal screening NIPT performance",
    "BRCA1 BRCA2 pathogenic variant population frequency",
    "liquid biopsy ctDNA early detection sensitivity specificity",
]


def run(question: str) -> None:
    messages = [{"role": "user", "content": question}]

    MAX_STEPS = 5

    for step in range(MAX_STEPS):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

        # Debugging
        print("stop_reason:", response.stop_reason)
        for block in response.content:
            print("block type:", block.type)

        # Save assistant response
        messages.append({
            "role": "assistant",
            "content": response.content
        })

        tool_results = []

        # Execute tools
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

        # No tool calls → print text and exit
        if not tool_results:
            return

        # Send tool results back to Claude
        messages.append({
            "role": "user",
            "content": tool_results
        })

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
