from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from agent_core import run_agent_streaming
from auth import require_auth
import rag
from sources import source_list

app = FastAPI(dependencies=[Depends(require_auth)])

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
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
