"""Orchester — FastAPI servisi (port 8006)

İki mod:
  1. /debate, /orchestrate  — direkt API endpointleri
  2. /v1/chat/completions   — OpenAI-compatible proxy
     Hermes config'de model.base_url=http://localhost:8006/v1 ayarlayınca
     Telegram mesajları buraya gelir → terminal_orchester.py → Claude+Gemini+OpenCode
"""
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, AsyncGenerator
from orchester import debate, AGENTS
from terminal_orchester import orchestrate
import asyncio, time, uuid, json
from pathlib import Path

app = FastAPI(
    title="Orchester API",
    description="3 CLI terminal orkestrasyonu — API key yok, sadece subscription",
    version="2.0.0",
)

_last: dict = {}


# ─── Mevcut endpointler ─────────────────────────────────────────────────────

class DebateRequest(BaseModel):
    task: str
    rounds: int = 2

class OrchestrateRequest(BaseModel):
    task: str
    mode: str = "smart"   # smart | parallel | chain | sequential

@app.post("/debate")
async def run_debate(req: DebateRequest, background: BackgroundTasks):
    async def run():
        global _last
        result = await debate(req.task, req.rounds)
        _last = {"task": req.task, "synthesis": result, "status": "done"}
    background.add_task(run)
    return {"status": "started", "task": req.task, "rounds": req.rounds}

@app.post("/orchestrate")
async def run_orchestrate(req: OrchestrateRequest):
    """Senkron terminal orkestrasyon — Claude + OpenCode + Gemini"""
    result = await orchestrate(req.task, req.mode, wiki=True)
    return {
        "status": "done",
        "mode": req.mode,
        "synthesis": result["synthesis"],
        "agents": result["agents"],
    }

@app.get("/result")
async def get_result():
    return _last or {"status": "no_result_yet"}

@app.get("/agents")
async def list_agents():
    return [{"name": a["name"], "model": a["id"]} for a in AGENTS]

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
    return {"status": "ok", "version": "2.0.0", "mode": "subscription-only"}


# ─── OpenAI-compatible proxy ─────────────────────────────────────────────────
# Hermes config: model.base_url = http://localhost:8006/v1
# Bu endpoint aktif olunca Telegram → Hermes → burada → Claude+Gemini+OpenCode

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = "terminal-orchester"
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048
    stream: Optional[bool] = False

@app.get("/v1/models")
async def list_models():
    """Hermes model listesi için."""
    return {
        "object": "list",
        "data": [{
            "id": "terminal-orchester",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "birkan",
            "description": "Claude + OpenCode + Gemini — subscription only, zero API cost",
        }]
    }

async def _progress_chunk(cid: str, text: str) -> str:
    """Hermes'in 'chunk' saydığı gerçek SSE data eventi."""
    chunk = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "terminal-orchester",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


async def _stream_response(task: str, cid: str, loop_answer: str = None) -> AsyncGenerator[str, None]:
    """OpenAI SSE akışı — orchestration yaparken progress chunk gönderir."""
    if loop_answer is not None:
        answer = loop_answer
    else:
        result_holder: dict = {}
        async def run_orch():
            result_holder["result"] = await orchestrate(task, mode="smart", wiki=True)

        orch_task = asyncio.create_task(run_orch())
        tick = 0
        while not orch_task.done():
            if tick == 0:
                yield await _progress_chunk(cid, "⏳ ")
            else:
                yield await _progress_chunk(cid, ".")
            tick += 1
            await asyncio.sleep(5)
        res = result_holder.get("result", {})
        answer = res.get("synthesis", "[Yanıt alınamadı]") + res.get("footer", "")
        yield await _progress_chunk(cid, "\n\n")

    chunk = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "terminal-orchester",
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": answer},
                     "finish_reason": None}],
    }
    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
    done_chunk = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "terminal-orchester",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done_chunk)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    """
    OpenAI-compatible endpoint (streaming + non-streaming).
    Hermes buraya mesaj gönderince terminal_orchester.py devreye girer.
    """
    cid = f"chatcmpl-{uuid.uuid4().hex[:8]}"

    # Son user mesajını çıkar
    user_messages = [m for m in req.messages if m.role == "user"]
    task = user_messages[-1].content if user_messages else "Merhaba"

    # Sistem mesajı bağlamı ekle
    system_messages = [m for m in req.messages if m.role == "system"]
    if system_messages:
        context = system_messages[-1].content[:200]
        task = f"{task}\n\n[Bağlam: {context}...]"

    if req.stream:
        return StreamingResponse(
            _stream_response(task, cid),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming
    result = await orchestrate(task, mode="smart", wiki=True)
    answer = result["synthesis"] + result.get("footer", "")
    return {
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "terminal-orchester",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                     "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": len(task.split()),
            "completion_tokens": len(answer.split()),
            "total_tokens": len(task.split()) + len(answer.split()),
        },
    }
