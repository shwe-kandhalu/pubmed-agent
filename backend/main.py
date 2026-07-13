import os
import sys

from fastapi import Depends, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent_core import run_agent_streaming, MOCK_MODE
from auth import require_auth
from rate_limit import enforce_rate_limit
import rag
from sources import source_list

# In mock-by-default deployments (MOCK_MODE=true, no server-side spend unless a visitor brings
# their own key), an open APP_PASSWORD is the intended design, not a footgun — only warn otherwise.
if not os.environ.get("APP_PASSWORD") and not MOCK_MODE:
    print(
        "WARNING: APP_PASSWORD is not set: /api/research is open to anyone who can reach this "
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
    session_id: str | None = None


@app.post("/api/research", dependencies=[Depends(enforce_rate_limit)])
async def research(body: ResearchRequest, x_user_api_key: str | None = Header(default=None)):
    return StreamingResponse(
        run_agent_streaming(body.question, session_id=body.session_id, user_api_key=x_user_api_key or None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/kb/count")
async def kb_count():
    return {"count": rag.count()}


@app.get("/api/sources")
async def sources():
    return {"sources": source_list()}


@app.get("/api/mode")
async def mode():
    return {"mock_mode": MOCK_MODE}
