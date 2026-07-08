import anthropic
import asyncio
import json
from typing import AsyncGenerator
from dotenv import load_dotenv

import rag
from sources import SOURCES, DEFAULT_SEARCH_SOURCES, group_by_source, source_list

load_dotenv()

TOOLS = [
    {
        "name": "search_literature",
        "description": (
            "Search academic literature for papers matching a query, across one or more sources. "
            f"Available sources: {', '.join(m.KEY for m in SOURCES.values())}. "
            f"If omitted, searches the default set ({', '.join(DEFAULT_SEARCH_SOURCES)}) — 'crossref' is "
            "metadata/DOI-focused and best added explicitly when you need citation verification. "
            "Returns normalized paper stubs (id, title, authors, year, doi) per source. "
            "Search iteratively with different queries if initial results are sparse or off-topic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which sources to search (default: pubmed, semantic_scholar, openalex, europepmc)",
                },
                "max_results": {"type": "integer", "description": "Max papers per source (default 8, max 20)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_abstracts",
        "description": (
            "Fetch titles and abstracts for a list of paper ids (from search_literature results, "
            "formatted as 'source:native_id', e.g. 'pubmed:38211234' or 'openalex:W2741809807'). "
            "Papers are automatically indexed in the vector knowledge base. "
            "Use this to screen for relevance before fetching full text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}, "description": "List of paper ids (up to 20)"}
            },
            "required": ["ids"],
        },
    },
    {
        "name": "fetch_full_text",
        "description": (
            "Fetch full text for the most relevant papers, where available. Full article body text is only "
            "available for open-access papers on 'pubmed' (via PubMed Central) and 'europepmc'; for "
            "'semantic_scholar' and 'openalex' this returns an open-access link instead (no PDF parsing), "
            "and 'crossref' never has full text. Papers with retrieved text are indexed in the knowledge base."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}, "description": "List of paper ids (up to 5)"}
            },
            "required": ["ids"],
        },
    },
    {
        "name": "retrieve_relevant_context",
        "description": (
            "Query the vector knowledge base for the most relevant indexed content. "
            "Always call this before writing your final synthesis to ground it in specific paper content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The research question or topic to retrieve context for"},
                "n_results": {"type": "integer", "description": "Number of chunks to retrieve (default 6)"},
            },
            "required": ["query"],
        },
    },
]

SYSTEM = """You are a scientific literature review assistant. You help researchers synthesize academic papers on any topic, drawing on multiple literature databases (PubMed, Semantic Scholar, OpenAlex, Europe PMC, and optionally Crossref).

Workflow:
1. Search literature iteratively (up to 3 searches) to find relevant papers, across sources. Refine queries if initial results are sparse. Prefer combining sources for broader coverage; add 'crossref' explicitly only if you need DOI/metadata verification.
2. Fetch abstracts to screen for relevance. Papers are automatically indexed in a vector knowledge base as you fetch them.
3. Fetch full text for the 2–3 most relevant papers. Note that full article text is only retrievable for open-access PubMed/PMC and Europe PMC papers — other sources may only yield an open-access link.
4. Call retrieve_relevant_context with the original research question to pull the most pertinent indexed content.
5. Write a comprehensive literature review grounded in the retrieved content.

Report format:
## Key Findings
Cite papers inline using their id, e.g. (pubmed:38211234) or (openalex:W2741809807).

## Common Themes

## Implications

## Research Gaps

Keep the report under 700 words. Prioritize synthesis and interpretation over listing. Ground every claim in a specific paper."""


def search_literature(query: str, sources: list[str] | None = None, max_results: int = 8) -> str:
    keys = sources or DEFAULT_SEARCH_SOURCES
    output = {}
    for key in keys:
        mod = SOURCES.get(key)
        if not mod:
            output[key] = {"error": f"unknown source '{key}'. Available: {', '.join(SOURCES)}"}
            continue
        try:
            output[key] = mod.search(query, max_results)
        except Exception as e:
            output[key] = {"error": str(e)}
    return json.dumps(output)


def fetch_abstracts(ids: list[str]) -> str:
    if not ids:
        return "No paper ids provided."
    parts = []
    for source_key, native_ids in group_by_source(ids).items():
        mod = SOURCES.get(source_key)
        if not mod:
            parts.append(f"Unknown source: {source_key}")
            continue
        try:
            text, covered = mod.fetch_abstracts(native_ids)
        except Exception as e:
            parts.append(f"[{source_key}] failed to fetch abstracts — {e}")
            continue
        if text:
            rag.store_batch(covered, text)
            parts.append(text)
    return "\n\n---\n\n".join(parts) if parts else "No abstracts retrieved."


def fetch_full_text(ids: list[str]) -> str:
    ids = ids[:5]
    parts = []
    for source_key, native_ids in group_by_source(ids).items():
        mod = SOURCES.get(source_key)
        if not mod:
            parts.append(f"Unknown source: {source_key}")
            continue
        try:
            results = mod.fetch_full_text(native_ids)
        except Exception as e:
            parts.append(f"[{source_key}] failed to fetch full text — {e}")
            continue
        for r in results:
            if "text" in r:
                rag.store_paper(r["id"], r["text"])
                parts.append(r["text"])
            else:
                parts.append(f"{r['id']}: {r.get('error', 'not available')}")
    return "\n\n---\n\n".join(parts) if parts else "No full text retrieved."


def retrieve_relevant_context_fn(query: str, n_results: int = 6) -> str:
    results = rag.retrieve(query, n_results)
    if not results:
        return "No relevant content in knowledge base yet. Fetch some papers first."
    parts = []
    for r in results:
        label = r["ids"] if r["ids"] else "Unknown"
        parts.append(f"[{label}]\n{r['text']}")
    return "\n\n---\n\n".join(parts)


def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "search_literature":
        return search_literature(inputs["query"], inputs.get("sources"), inputs.get("max_results", 8))
    if name == "fetch_abstracts":
        return fetch_abstracts(inputs["ids"])
    if name == "fetch_full_text":
        return fetch_full_text(inputs["ids"])
    if name == "retrieve_relevant_context":
        return retrieve_relevant_context_fn(inputs["query"], inputs.get("n_results", 6))
    return f"Unknown tool: {name}"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def run_agent_streaming(question: str, domain: str = "") -> AsyncGenerator[str, None]:
    client = anthropic.AsyncAnthropic()
    system = SYSTEM
    if domain:
        system += f"\n\nThe user is working in the field of: {domain}."

    messages = [{"role": "user", "content": question}]
    MAX_STEPS = 12

    try:
        for _ in range(MAX_STEPS):
            async with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=system,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield _sse({"type": "text_delta", "text": text})
                final_message = await stream.get_final_message()

            messages.append({"role": "assistant", "content": final_message.content})

            if final_message.stop_reason != "tool_use":
                break

            tool_results = []
            for block in final_message.content:
                if block.type != "tool_use":
                    continue

                yield _sse({"type": "tool_call", "name": block.name, "input": block.input})

                before = rag.count()
                result = await asyncio.to_thread(dispatch_tool, block.name, block.input)
                after = rag.count()

                if after > before:
                    ids = block.input.get("ids", [])
                    yield _sse({"type": "rag_store", "chunks_added": after - before, "ids": ids})

                yield _sse({"type": "tool_result", "name": block.name, "result": result[:500]})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    yield _sse({"type": "done"})
