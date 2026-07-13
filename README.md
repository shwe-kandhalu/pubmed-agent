# Literature Review Agent

**Live demo:** https://litreview-agent-five.vercel.app

An AI agent that searches multiple literature databases for a research question, screens abstracts and full text, and writes back a structured synthesis — with citations you can actually verify, not just trust.

## Problem

Doing a literature review well means running the same loop over and over: search a handful of databases, skim abstracts, chase down the full text of anything promising, and stitch the findings into a coherent summary. It's slow, and it's easy to lose track of exactly which claim came from which paper — or to cite something you only ever saw as a search-result title. That's the actual risk with LLM-assisted research: a fluent summary that cites a paper it never really read.

## Solution

Literature Review Agent runs that loop as an agent, not a single prompt. Claude iteratively searches PubMed, Semantic Scholar, OpenAlex, and Europe PMC, screens abstracts to decide what's worth reading in full, fetches full text where it's open-access, and only then writes the synthesis — grounded in a retrieval step over what it actually read. Every citation is checked after the fact against what was really pulled into that retrieval context, so a hallucinated or search-only citation gets flagged in the UI instead of slipping through.

## Tech Stack

- [Claude](https://anthropic.com) (`claude-sonnet-4-6`) — agentic tool use and report generation
- **Backend**: FastAPI (Python), streaming responses over SSE
- **Frontend**: React + Vite
- **Sources**: PubMed / PubMed Central (NCBI E-utilities), Semantic Scholar, OpenAlex, Europe PMC, Crossref
- **RAG**: ChromaDB (in-memory, per-run) + `sentence-transformers` (`all-MiniLM-L6-v2`) for embeddings

## Core User Flow

1. Ask a research question (optionally scoped to a domain, e.g. "oncology")
2. Claude searches across PubMed, Semantic Scholar, OpenAlex, and Europe PMC in parallel, refining its query for up to 3 rounds if initial results are sparse or off-topic — model-driven, not a hardcoded decomposition step
3. It screens abstracts for the most relevant papers, indexing everything it reads into a knowledge base scoped to that run only (no cross-session leakage — see [Architecture](#architecture))
4. For the top 2-3 papers, it fetches full text where available (open-access PubMed Central / Europe PMC); other sources yield an open-access link instead
5. It retrieves the most relevant indexed content and grounds the final synthesis in it
6. Claude writes a structured report — Key Findings, Common Themes, Implications, Research Gaps — citing papers inline, streamed live to the UI

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
- `rag.py`: chunks and embeds fetched text into an in-memory ChromaDB collection, scoped per-request by a `run_id` so one user's retrieval can never surface another run's chunks. Nothing is persisted to disk, since a run's data is never queried again once that request finishes.
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

## Environment Variables

```
ANTHROPIC_API_KEY=your-key-here

# Optional: "true" skips Claude/API calls and streams back canned mock data instead,
# for testing the UI without spending credits.
MOCK_MODE=

# Optional locally, required for any public deployment: gates every request behind this
# password (sent as the X-App-Password header). Unset in production means anyone who
# finds the URL can run searches on your API credits.
APP_PASSWORD=

# Required only in production: the deployed frontend's origin, for CORS.
FRONTEND_URL=

# Optional: raises Semantic Scholar's otherwise heavily-throttled unauthenticated rate limit
SEMANTIC_SCHOLAR_API_KEY=

# Optional but recommended: anonymous OpenAlex search is heavily rate-limited
OPENALEX_API_KEY=

# Optional: joins OpenAlex's "polite pool" for higher rate limits
OPENALEX_MAILTO=
```

On the frontend build only, set `VITE_API_BASE_URL` to the deployed backend's URL. Locally this is left empty and relies on Vite's dev-server proxy.

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
   Then open `.env` and replace `your-key-here` with your actual key from [console.anthropic.com](https://console.anthropic.com). See [Environment Variables](#environment-variables) for the rest.

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

## Demo / Mock Mode

Set `MOCK_MODE=true` and the backend skips Claude and every literature API entirely, streaming back a canned run (search → abstracts → full text → retrieval → a fixed report with fake `pubmed:9000000x` / `openalex:W900000003` ids) at the same pace and over the same SSE event shape as a real run. It exists to demo or test the UI end-to-end without spending API credits or depending on external services being up. A visitor who supplies their own Anthropic API key in the UI always gets the real thing, even on a deployment that otherwise defaults to mock mode.

## Deploying

The frontend is a static Vite build (fits any static host: Vercel, Netlify). The backend needs a real long-running process, not a serverless function, since requests stream over SSE for 60-150+ seconds and hold a loaded embedding model in memory; that doesn't fit a short-execution serverless model (Railway/Render/Fly.io all work).

Two things are required (not just recommended) once this is reachable outside your own machine:
- `APP_PASSWORD`: without it, `/api/research` is open to anyone who finds the URL, and every request spends real Anthropic API credits. The server prints a warning on startup if it's unset.
- `FRONTEND_URL`: the deployed frontend's origin, so CORS allows it (localhost is always allowed regardless, for local dev).

And on the frontend build, set `VITE_API_BASE_URL` to the deployed backend's URL. Locally this is left empty and relies on Vite's dev-server proxy, but a production build needs the real absolute URL.
