# Literature Review Agent

An AI-powered research assistant that searches multiple literature databases — PubMed, Semantic Scholar, OpenAlex, and Europe PMC — screens and reads the most relevant papers, and synthesizes a structured literature review using Claude.

## How it works

1. You ask a research question
2. The agent searches across literature sources in parallel, refining its query if initial results are sparse
3. It screens abstracts to identify the most relevant papers, indexing everything it reads into a local vector knowledge base
4. For the top papers, it fetches full text where available (open-access PubMed Central / Europe PMC articles)
5. It retrieves the most relevant indexed content and grounds the final synthesis in it
6. Claude writes a structured report: key findings, common themes, implications, and research gaps

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
