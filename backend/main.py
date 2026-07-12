import os
import sys

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent_core import run_agent_streaming
from auth import require_auth
import rag
from sources import source_list

if not os.environ.get("APP_PASSWORD"):
    print(
        "WARNING: APP_PASSWORD is not set — /api/research is open to anyone who can reach this "
        "server, and every request spends real Anthropic API credits. Set APP_PASSWORD before "
        "deploying anywhere publicly reachable.",
        file=sys.stderr,
    )

app = FastAPI(dependencies=[Depends(require_auth)])

# FRONTEND_URL: the deployed frontend's origin (e.g. https://your-app.vercel.app), for CORS in
# production. localhost is always allowed for local dev regardless of this setting.
_frontend_url = os.environ.get("FRONTEND_URL")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_origins=[_frontend_url] if _frontend_url else [],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    question: str
    domain: str = ""


@app.post("/api/research")
async def research(body: ResearchRequest):
    return StreamingResponse(
        run_agent_streaming(body.question, body.domain),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/kb/count")
async def kb_count():
    return {"count": rag.count()}


@app.get("/api/sources")
async def sources():
    return {"sources": source_list()}
