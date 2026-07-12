# Literature Review Agent

An AI agent that searches multiple literature databases for a research question, screens abstracts and full text, and summarizes key findings, themes, and research gaps. It verifies that every citation was actually retrieved (not just found in search) and grades each paper's evidence strength (systematic review, RCT, observational study, etc.).

## How it works

1. You ask a research question (optionally with a domain, e.g. "oncology")
2. Claude searches across PubMed, Semantic Scholar, OpenAlex, and Europe PMC in parallel, refining its query (up to 3 rounds) if initial results are sparse or off-topic. This is model-driven, not a hardcoded decomposition step: the model decides how to phrase each search based on what the previous one returned.
3. It screens abstracts to identify the most relevant papers, indexing everything it reads into a knowledge base scoped to this run only (no cross-session leakage; see [Architecture](#architecture))
4. For the top 2-3 papers, it fetches full text where available (open-access PubMed Central / Europe PMC articles); other sources yield an open-access link instead
5. It retrieves the most relevant indexed content and grounds the final synthesis in it
6. Claude writes a structured report (Key Findings, Common Themes, Implications, Research Gaps), citing papers inline

## Trust & verification

Built to make the output auditable, not just readable:

- **Real references, not raw ids**: every citation renders as a clickable link with title/authors/year, resolved from the actual source database
- **Citation groundedness**: the app tracks which papers were actually pulled into retrieval context before being cited, versus papers only ever seen as a search result stub. Citations to the latter are flagged `⚠ not retrieved into context` in the UI, since that's a real hallucination-risk signal.
- **Abstract-only disclosure**: retrieval prefers full-text chunks over abstract chunks for the same paper when both exist. Any citation still grounded only in an abstract is labeled `abstract only`, since abstracts routinely omit the methodology and effect-size detail that matters for a real claim.
- **Evidence-strength tiers**: each cited paper is tagged systematic review/meta-analysis, RCT, observational study, case report, or narrative review, using real publication-type metadata from PubMed and Europe PMC (not model guesswork). Papers from sources without that signal (OpenAlex, Semantic Scholar, Crossref) are honestly labeled "not classified" rather than guessed at.

## Architecture

**Backend** (`backend/`)
- `main.py`: FastAPI app. The one `/api/research` endpoint streams the whole run over SSE.
- `agent_core.py`: the agent loop. Gives Claude four tools (`search_literature`, `fetch_abstracts`, `fetch_full_text`, `retrieve_relevant_context`), runs up to 12 tool-use steps, and streams every step back to the client as it happens (search calls, results, citations found, groundedness checks).
- `sources/`: one module per literature database (`pubmed.py`, `semantic_scholar.py`, `openalex.py`, `europepmc.py`, `crossref.py`), each exposing the same `search()` / `fetch_abstracts()` / `fetch_full_text()` shape so the agent loop doesn't need to know which source it's talking to. `common.py` holds shared JATS XML parsing and the evidence-tier classifier.
- `rag.py`: chunks and embeds (`sentence-transformers`, `all-MiniLM-L6-v2`) fetched text into an in-memory ChromaDB collection, scoped per-request by a `run_id` so one user's retrieval can never surface another run's chunks. Nothing is persisted to disk, since a run's data is never queried again once that request finishes.
- `observability.py`: writes one structured JSON line per run to `backend/logs/runs.jsonl` (token usage/latency per model call, duration per tool call, search count, groundedness counts). Backend-only, not surfaced in the UI.
- `auth.py`: single shared-password gate (`APP_PASSWORD`) via a request header.

**Frontend** (`frontend/`)
- `App.jsx`: single-page React app. Submits the question over `fetch`, reads the SSE stream by hand with `ReadableStream` (not the browser's `EventSource`, since that only supports GET requests and this needs to POST), and renders tool calls, citations, and the References list live as they arrive.

## Evals

`backend/evals/` holds a golden set of research questions with real, relevance-ranked PubMed ids as ground truth (fetched live from NCBI, not hand-picked), plus a harness (`run_eval.py`) that checks three things:

- **Retrieval recall@k**: does `search_literature` surface the same top PubMed results PubMed's own relevance ranking would give? (No LLM cost. This is how a bug where PubMed search was silently defaulting to most-recent-first instead of most-relevant got caught.)
- **Trajectory checks**: from a live run's trace, did it stay within its search budget, call `retrieve_relevant_context` before synthesizing, avoid citing papers it never actually retrieved, stay under the word limit, and hit all required report sections?
- **LLM-judge quality**: a second Claude call scores the report against a rubric (format, citation density, coherence, conciseness).

```
python backend/evals/run_eval.py            # retrieval recall only, fast and free
python backend/evals/run_eval.py --full      # all three layers, slower, uses API credits
```

## Observability

Every run writes a structured trace to `backend/logs/runs.jsonl`: per-model-call token usage/latency, per-tool-call duration, search count, whether retrieval grounded the synthesis, and citation/groundedness counts. Backend-only; not surfaced in the UI. The eval harness reads the same trace shape.

## Setup

1. Clone the repo:
   ```
   git clone https://github.com/shwe-kandhalu/litreview_agent.git
   cd litreview_agent
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

## Deploying

The frontend is a static Vite build (fits any static host: Vercel, Netlify). The backend needs a real long-running process, not a serverless function, since requests stream over SSE for 60-150+ seconds and hold a loaded embedding model in memory; that doesn't fit a short-execution serverless model (Railway/Render/Fly.io all work).

Two things are required (not just recommended) once this is reachable outside your own machine:
- `APP_PASSWORD`: without it, `/api/research` is open to anyone who finds the URL, and every request spends real Anthropic API credits. The server prints a warning on startup if it's unset.
- `FRONTEND_URL`: the deployed frontend's origin, so CORS allows it (localhost is always allowed regardless, for local dev).

And on the frontend build, set `VITE_API_BASE_URL` to the deployed backend's URL. Locally this is left empty and relies on Vite's dev-server proxy, but a production build needs the real absolute URL.

## Stack

- [Claude](https://anthropic.com): LLM reasoning, tool use, and report generation
- **Backend**: FastAPI + Python, streaming responses over SSE
- **Frontend**: React + Vite
- **Sources**: PubMed / PubMed Central (NCBI E-utilities), Semantic Scholar, OpenAlex, Europe PMC, Crossref
- **RAG**: ChromaDB (in-memory, per-run) + `sentence-transformers` (`all-MiniLM-L6-v2`) for embeddings
