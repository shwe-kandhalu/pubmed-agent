"""Eval harness for the literature review agent.

Three layers:
  A. Trajectory checks   — deterministic assertions on agent behavior (search budget, retrieval
                            before synthesis, groundedness, format compliance). From a live run's trace.
  B. Retrieval recall@k  — does search_literature's PubMed results surface the same papers PubMed's
                            own relevance ranking returns for that query? No LLM cost, no agent run.
  C. LLM-judge quality    — a second Claude call scores the final report against a rubric.

Usage:
  python evals/run_eval.py               # layer B only (fast, free)
  python evals/run_eval.py --full        # all three layers (slow, costs API credits)
  python evals/run_eval.py --full -n 2   # limit to first N golden questions
"""
import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from dotenv import load_dotenv

load_dotenv()

import agent_core
from sources import pubmed

GOLDEN_SET_PATH = os.path.join(os.path.dirname(__file__), "golden_set.jsonl")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

REQUIRED_SECTIONS = ["## Key Findings", "## Common Themes", "## Implications", "## Research Gaps"]
RECALL_THRESHOLD = 0.5

JUDGE_PROMPT = """You are grading a scientific literature review report for quality. Score each dimension 1-5 (5 = excellent).

Report:
---
{report}
---

Respond with JSON only, no other text:
{{
  "format_compliance": <1-5, follows Key Findings / Common Themes / Implications / Research Gaps structure>,
  "citation_density": <1-5, claims are backed by inline citations rather than asserted bare>,
  "coherence": <1-5, synthesis reads as connected analysis, not a list of paper summaries>,
  "conciseness": <1-5, stays focused, avoids padding>,
  "notes": "<one sentence on the biggest quality issue, or 'none'>"
}}"""


def load_golden_set() -> list[dict]:
    with open(GOLDEN_SET_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def eval_retrieval(entry: dict, k: int = 10) -> dict:
    """Layer B: no agent, no LLM — just checks the PubMed source adapter's own recall."""
    results = pubmed.search(entry["question"], max_results=k)
    returned_ids = {p["id"].split(":", 1)[1] for p in results}
    expected = set(entry["expected_pubmed_ids"])
    hit = expected & returned_ids
    return {
        "id": entry["id"],
        "recall_at_k": len(hit) / len(expected) if expected else None,
        "hits": sorted(hit),
        "misses": sorted(expected - hit),
    }


async def run_agent_and_collect(question: str, domain: str) -> dict:
    events, report_text = [], ""
    async for chunk in agent_core.run_agent_streaming(question, domain):
        for line in chunk.split("\n\n"):
            if not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            events.append(data)
            if data["type"] == "text_delta":
                report_text += data["text"]
    return {"events": events, "report_text": report_text}


def eval_trajectory(run: dict) -> dict:
    """Layer A: deterministic checks on how the agent behaved, from one live run's event trace."""
    events, report = run["events"], run["report_text"]
    search_count = sum(1 for e in events if e["type"] == "tool_call" and e["name"] == "search_literature")
    retrieved = any(e["type"] == "tool_call" and e["name"] == "retrieve_relevant_context" for e in events)
    grounding = next((e for e in events if e["type"] == "grounding"), None)
    errored = any(e["type"] == "error" for e in events)
    word_count = len(report.split())
    missing_sections = [s for s in REQUIRED_SECTIONS if s not in report]

    checks = {
        "search_count_in_budget": search_count <= 3,
        "retrieved_context_before_synthesis": retrieved,
        "no_errors": not errored,
        "under_700_words": word_count <= 750,
        "has_required_sections": not missing_sections,
        "no_ungrounded_citations": bool(grounding) and len(grounding["ungrounded_ids"]) == 0,
    }
    return {
        "search_count": search_count,
        "word_count": word_count,
        "cited_count": len(grounding["cited_ids"]) if grounding else 0,
        "ungrounded_count": len(grounding["ungrounded_ids"]) if grounding else 0,
        # Informational, not a failing check — abstract-only citations are expected for paywalled papers.
        "abstract_only_count": len(grounding["abstract_only_ids"]) if grounding else 0,
        "missing_sections": missing_sections,
        "checks": checks,
        "passed": all(checks.values()),
    }


async def eval_judge(report_text: str) -> dict:
    """Layer C: a second Claude call scores the report against a rubric."""
    client = anthropic.AsyncAnthropic()
    resp = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(report=report_text)}],
    )
    text = resp.content[0].text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0)) if match else {"error": "unparseable judge output", "raw": text}


async def eval_full(entry: dict) -> dict:
    run = await run_agent_and_collect(entry["question"], entry["domain"])
    trajectory = eval_trajectory(run)
    judge = await eval_judge(run["report_text"]) if run["report_text"] else {"error": "empty report"}
    return {"id": entry["id"], "trajectory": trajectory, "judge": judge}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also run layers A+C (live agent runs, costs API credits)")
    parser.add_argument("-n", type=int, default=None, help="limit to first N golden questions")
    args = parser.parse_args()

    golden_set = load_golden_set()
    if args.n:
        golden_set = golden_set[: args.n]

    print(f"Running eval on {len(golden_set)} golden questions...\n")

    retrieval_results = [eval_retrieval(e) for e in golden_set]
    avg_recall = sum(r["recall_at_k"] for r in retrieval_results) / len(retrieval_results)
    print("=== Layer B: Retrieval recall@10 (PubMed) ===")
    for r in retrieval_results:
        print(f"  {r['id']:<24} recall={r['recall_at_k']:.2f}  misses={r['misses']}")
    print(f"  avg recall@10: {avg_recall:.2f}\n")

    full_results = []
    if args.full:
        print("=== Layers A+C: live agent trajectory + LLM-judge quality ===")
        for entry in golden_set:
            print(f"  running {entry['id']}...")
            result = asyncio.run(eval_full(entry))
            full_results.append(result)
            t, j = result["trajectory"], result["judge"]
            status = "PASS" if t["passed"] else "FAIL"
            print(f"    trajectory: {status}  (searches={t['search_count']}, words={t['word_count']}, "
                  f"cited={t['cited_count']}, ungrounded={t['ungrounded_count']}, "
                  f"abstract_only={t['abstract_only_count']})")
            if not t["passed"]:
                print(f"      failed checks: {[k for k, v in t['checks'].items() if not v]}")
            print(f"    judge: {j}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    with open(out_path, "w") as f:
        json.dump({"retrieval": retrieval_results, "full": full_results}, f, indent=2)
    print(f"\nResults written to {out_path}")

    if avg_recall < RECALL_THRESHOLD:
        print(f"\nFAIL: avg recall@10 {avg_recall:.2f} is below the {RECALL_THRESHOLD:.2f} threshold")
        sys.exit(1)
    if args.full and not all(r["trajectory"]["passed"] for r in full_results):
        print("\nFAIL: one or more trajectory checks failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
