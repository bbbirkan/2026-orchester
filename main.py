"""Orchester — FastAPI servisi (port 8006)"""
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from orchester import debate, AGENTS
import asyncio, json
from pathlib import Path

app = FastAPI(
    title="Orchester API",
    description="Multi-agent debate: Claude + Gemini + GLM-4.7",
    version="1.0.0",
)

_last: dict = {}


class DebateRequest(BaseModel):
    task: str
    rounds: int = 2


@app.post("/debate")
async def run_debate(req: DebateRequest, background: BackgroundTasks):
    async def run():
        global _last
        result = await debate(req.task, req.rounds)
        _last = {"task": req.task, "synthesis": result, "status": "done"}
    background.add_task(run)
    return {"status": "started", "task": req.task, "rounds": req.rounds}


@app.get("/result")
async def get_result():
    return _last or {"status": "no_result_yet"}


@app.get("/agents")
async def list_agents():
    return [{"name": a["name"], "model": a["model"]} for a in AGENTS]


@app.get("/debates")
async def list_debates():
    d = Path(__file__).parent / "debates"
    files = sorted(d.glob("*.md"), reverse=True)
    return [{"file": f.name, "size": f.stat().st_size} for f in files[:20]]


@app.get("/debates/{filename}")
async def get_debate(filename: str):
    d = Path(__file__).parent / "debates" / filename
    if not d.exists():
        return {"error": "not found"}
    return {"content": d.read_text()}


@app.get("/health")
async def health():
    return {"status": "ok", "agents": len(AGENTS)}
