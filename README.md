# Literature Review Agent

An AI-powered research assistant that searches multiple literature databases — PubMed, Semantic Scholar, OpenAlex, and Europe PMC — screens and reads the most relevant papers, and synthesizes a structured literature review using Claude.

## How it works

1. You ask a research question
2. The agent searches across literature sources in parallel, refining its query if initial results are sparse
3. It screens abstracts to identify the most relevant papers, indexing everything it reads into a knowledge base scoped to this run (no cross-session leakage)
4. For the top papers, it fetches full text where available (open-access PubMed Central / Europe PMC articles)
5. It retrieves the most relevant indexed content and grounds the final synthesis in it
6. Claude writes a structured report: key findings, common themes, implications, and research gaps, with citations linked to a References list — any citation the model never actually retrieved into context is flagged in the UI

## Evals

`backend/evals/` holds a golden set of research questions with real, relevance-ranked PubMed ids as ground truth (fetched live from NCBI, not hand-picked), plus a harness (`run_eval.py`) that checks three things:

- **Retrieval recall@k** — does `search_literature` surface the same top PubMed results PubMed's own relevance ranking would give? (No LLM cost — this is how a bug where PubMed search was silently defaulting to most-recent-first instead of most-relevant got caught.)
- **Trajectory checks** — from a live run's trace: did it stay within its search budget, call `retrieve_relevant_context` before synthesizing, avoid citing papers it never actually retrieved, stay under the word limit, and hit all required report sections?
- **LLM-judge quality** — a second Claude call scores the report against a rubric (format, citation density, coherence, conciseness).

```
python backend/evals/run_eval.py            # retrieval recall only — fast, free
python backend/evals/run_eval.py --full      # all three layers — slower, uses API credits
```

## Observability

Every run writes a structured trace to `backend/logs/runs.jsonl` — per-model-call token usage/latency, per-tool-call duration, search count, whether retrieval grounded the synthesis, and citation/groundedness counts. Backend-only; not surfaced in the UI. The eval harness reads the same trace shape.

## Setup

1. Clone the repo:
   ```
   git clone https://github.com/shwe-kandhalu/literature-review-agent.git
   cd literature-review-agent
   ```

2. Install backend dependencies:
   ```
   cd backend
   pip3 install -r requirements.txt
   ```

3. Install frontend dependencies:
   ```
   cd ../frontend
   npm install
   ```

4. Add your Anthropic API key:
   ```
   cp .env.example .env
   ```
   Then open `.env` and replace `your-key-here` with your actual key from [console.anthropic.com](https://console.anthropic.com). Optional keys (`SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_API_KEY`, `APP_PASSWORD`) are also documented there.

## Usage

Start the backend:
```
cd backend
uvicorn main:app --reload --port 8000
```

Start the frontend (separate terminal):
```
cd frontend
npm run dev
```

Open the printed local URL (typically `http://localhost:5173`) in your browser.

## Stack

- [Claude](https://anthropic.com) — LLM reasoning and report generation
- **Backend**: FastAPI + Python, streaming responses over SSE
- **Frontend**: React + Vite
- **Sources**: PubMed / PubMed Central (NCBI E-utilities), Semantic Scholar, OpenAlex, Europe PMC, Crossref
- **RAG**: ChromaDB (local vector store) + `sentence-transformers` (`all-MiniLM-L6-v2`) for embeddings
