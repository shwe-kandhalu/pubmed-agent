"""Structured run tracing. Writes one JSON line per research run to logs/runs.jsonl —
backend-only, not surfaced in the frontend. Doubles as input for the eval harness's
deterministic trajectory checks (search count, whether retrieval grounded the report, etc)."""
import json
import os
import time

_LOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "runs.jsonl")


class RunTrace:
    def __init__(self, run_id: str, question: str, domain: str = ""):
        self.run_id = run_id
        self.question = question
        self.domain = domain
        self._started = time.monotonic()
        self.wall_started_at = time.time()
        self.model_calls: list[dict] = []
        self.tool_calls: list[dict] = []

    def record_model_call(self, duration_s: float, input_tokens: int, output_tokens: int, stop_reason: str) -> None:
        self.model_calls.append({
            "duration_s": round(duration_s, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "stop_reason": stop_reason,
        })

    def record_tool_call(self, name: str, duration_s: float, result_chars: int) -> None:
        self.tool_calls.append({
            "name": name,
            "duration_s": round(duration_s, 3),
            "result_chars": result_chars,
        })

    def finish(
        self,
        stop_reason: str | None,
        error: str | None = None,
        cited_count: int | None = None,
        ungrounded_count: int | None = None,
        abstract_only_count: int | None = None,
    ) -> None:
        record = {
            "run_id": self.run_id,
            "question": self.question,
            "domain": self.domain,
            "started_at": self.wall_started_at,
            "duration_s": round(time.monotonic() - self._started, 3),
            "stop_reason": stop_reason,
            "error": error,
            "search_count": sum(1 for t in self.tool_calls if t["name"] == "search_literature"),
            "retrieved_context": any(t["name"] == "retrieve_relevant_context" for t in self.tool_calls),
            "cited_count": cited_count,
            "ungrounded_count": ungrounded_count,
            "abstract_only_count": abstract_only_count,
            "total_input_tokens": sum(c["input_tokens"] for c in self.model_calls),
            "total_output_tokens": sum(c["output_tokens"] for c in self.model_calls),
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
        }
        try:
            os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
            with open(_LOG_PATH, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
