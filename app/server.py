import asyncio
import json
import os
import random
import re
import shutil
import time
import uuid
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import comfy_client, db, llm_manager

BASE = Path(__file__).resolve().parent.parent
ASSETS = BASE / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

LLAMA_BASE = os.environ.get("LLAMA_BASE", "http://127.0.0.1:8080/v1").rstrip("/")
LMSTUDIO_BASE = os.environ.get("LMSTUDIO_BASE", "http://127.0.0.1:1234/v1").rstrip("/")

THINK_START = chr(60) + "think" + chr(62)
THINK_END = chr(60) + "/think" + chr(62)

db.init_db()

app = FastAPI(title="LLM Chat GUI")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

GENERATIONS: dict = {}

SYSTEM_PROMPT = (
    "あなたは日本語で会話するアシスタントです。ユーザーは日本語で話します。日本語で返信してください。\n"
    "ユーザーが画像の生成・描画・修正を明確に依頼した場合のみ、返答の最後に必ず fenced JSON を1つ追加してください:\n"
    "```json\n"
    "{\"image_request\": {\"prompt_en\": \"<完成した画像を観察者が述べるような詳細な英語の1段落>\", \"aspect_ratio\": \"1:1 (Square)\"}}\n"
    "```\n"
    "prompt_en は必ず英語で書いてください。aspect_ratio は次のいずれかから選んでください: "
    "\"1:1 (Square)\" / \"3:2 (Photo)\" / \"2:3 (Portrait Photo)\" / \"3:4 (Portrait Standard)\" / "
    "\"4:3 (Standard)\" / \"9:16 (Portrait Widescreen)\" / \"16:9 (Widescreen)\" / \"21:9 (Ultrawide)\"。\n"
    "画像依頼以外は普通に会話してください。画像依頼の場合のみそのJSONを含めてください。\n"
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def extract_image_request(text: str) -> dict | None:
    candidates: list[str] = []
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1))
    for m2 in re.finditer(r"\{[^{}]*\"image_request\"[^{}]*\}", text):
        candidates.append(m2.group(0))
    for c in candidates:
        try:
            obj = json.loads(c)
            req = obj.get("image_request") if isinstance(obj, dict) else None
            if req is None and isinstance(obj, dict) and "prompt_en" in obj:
                req = obj
            if isinstance(req, dict) and req.get("prompt_en"):
                req.setdefault("aspect_ratio", "1:1 (Square)")
                return req
        except Exception:
            continue
    return None


@app.get("/")
def index():
    return FileResponse(str(BASE / "static" / "index.html"))


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/models")
def api_models():
    endpoints = [
        {"label": "llama.cpp", "base": LLAMA_BASE},
        {"label": "LM Studio", "base": LMSTUDIO_BASE},
    ]
    out = []
    for ep in endpoints:
        try:
            r = httpx.get(ep["base"] + "/models", timeout=5)
            r.raise_for_status()
            models = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
            out.append({"label": ep["label"], "base": ep["base"], "online": True, "models": models})
        except Exception:
            out.append({"label": ep["label"], "base": ep["base"], "online": False, "models": []})
    return out


@app.get("/api/llm/status")
def llm_status():
    return llm_manager.status()


@app.post("/api/llm/start")
def llm_start():
    return llm_manager.start()


@app.post("/api/llm/stop")
def llm_stop():
    return llm_manager.stop()


@app.get("/api/comfy/status")
def comfy_status():
    try:
        return comfy_client.status()
    except Exception as e:
        return {"online": False, "error": str(e)}


@app.get("/api/sessions")
def list_sessions():
    return db.list_sessions()


@app.post("/api/sessions")
def create_session():
    return {"id": db.create_session()}


@app.get("/api/sessions/{sid}")
def get_session(sid: int):
    s = db.get_session(sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"session": s, "messages": db.get_messages(sid), "images": db.get_images(sid)}


@app.delete("/api/sessions/{sid}")
def delete_session(sid: int):
    if not db.get_session(sid):
        return JSONResponse({"error": "not found"}, status_code=404)
    active = [
        g for g in GENERATIONS.values()
        if g.get("session_id") == sid and g.get("state") in ("starting", "running")
    ]
    if active:
        return JSONResponse({"error": "generation in progress"}, status_code=409)
    sdir = ASSETS / str(sid)
    if sdir.exists():
        shutil.rmtree(sdir, ignore_errors=True)
    db.delete_session(sid)
    return {"deleted": sid}


class ChatIn(BaseModel):
    session_id: int
    message: object
    model: str
    base: str
    thinking: bool = True
    max_tokens: int = 4096


def _content_from_db(c: str):
    try:
        parsed = json.loads(c)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    return c


@app.post("/api/chat")
async def api_chat(in_: ChatIn):
    user_content = in_.message
    user_stored = json.dumps(user_content, ensure_ascii=False) if isinstance(user_content, list) else str(user_content)
    db.add_message(in_.session_id, "user", user_stored, thinking=int(in_.thinking))
    session = db.get_session(in_.session_id)
    if session and not session.get("title"):
        first_text = ""
        if isinstance(user_content, list):
            for p in user_content:
                if isinstance(p, dict) and p.get("type") == "text":
                    first_text = p.get("text", "")
                    break
        else:
            first_text = user_stored
        db.set_session_title(in_.session_id, first_text[:40], in_.model)
    sp = db.get_setting("system_prompt") or SYSTEM_PROMPT
    msgs = [{"role": "system", "content": sp}]
    for m in db.get_messages(in_.session_id)[-30:]:
        msgs.append({"role": m["role"], "content": _content_from_db(m["content"])})

    async def stream():
        buf = ""
        emitted = 0
        phase = "content"
        first_t = None
        token_count = 0
        try:
            timeout = httpx.Timeout(connect=15.0, read=None, write=None, pool=None)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    in_.base.rstrip("/") + "/chat/completions",
                    json={
                        "model": in_.model,
                        "messages": msgs,
                        "stream": True,
                        "temperature": 0.7,
                        "max_tokens": max(16, int(in_.max_tokens)),
                        "chat_template_kwargs": {"enable_thinking": bool(in_.thinking)},
                    },
                ) as resp:
                    if resp.status_code != 200:
                        yield _sse("error", {"message": f"LLM HTTP {resp.status_code}: {resp.reason_phrase}"})
                        return
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except Exception:
                            continue
                        choices = chunk.get("choices") or []
                        delta = (choices[0].get("delta") or {}).get("content") if choices else None
                        if not delta:
                            continue
                        if first_t is None:
                            first_t = time.time()
                        token_count += 1
                        buf += delta
                        i = emitted
                        while i < len(buf):
                            if phase == "thinking":
                                j = buf.find(THINK_END, i)
                                if j == -1:
                                    yield _sse("token", {"text": buf[i:], "thinking": True})
                                    break
                                if j > i:
                                    yield _sse("token", {"text": buf[i:j], "thinking": True})
                                i = j + len(THINK_END)
                                phase = "content"
                            else:
                                j = buf.find(THINK_START, i)
                                if j == -1:
                                    yield _sse("token", {"text": buf[i:], "thinking": False})
                                    break
                                if j > i:
                                    yield _sse("token", {"text": buf[i:j], "thinking": False})
                                i = j + len(THINK_START)
                                phase = "thinking"
                        emitted = i if i == len(buf) else len(buf)
            text = buf
            if not text:
                yield _sse("error", {"message": "LLM から応答が返りませんでした"})
                return
            end_t = time.time()
            elapsed = end_t - first_t if first_t is not None else 0.0
            tps = round(token_count / elapsed, 1) if elapsed > 0.05 and token_count > 0 else None
            img_req = extract_image_request(text)
            mid = db.add_message(
                in_.session_id, "assistant", text,
                json.dumps(img_req, ensure_ascii=False) if img_req else None,
                tps=tps, tokens=token_count, seconds=round(elapsed, 1), thinking=int(in_.thinking),
            )
            if img_req:
                yield _sse("image_request", {
                    "message_id": mid,
                    "prompt_en": img_req["prompt_en"],
                    "aspect_ratio": img_req.get("aspect_ratio", "1:1 (Square)"),
                })
            yield _sse("done", {"message_id": mid, "tps": tps, "tokens": token_count, "seconds": round(elapsed, 1)})
        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(stream(), media_type="text/event-stream")


class GenIn(BaseModel):
    session_id: int
    message_id: int
    prompt_en: str
    aspect_ratio: str = "1:1 (Square)"
    seed: int | None = None


@app.post("/api/generate")
async def api_generate(in_: GenIn):
    gen_id = uuid.uuid4().hex
    seed = in_.seed if in_.seed is not None else random.randrange(1, 2 ** 63)
    GENERATIONS[gen_id] = {
        "state": "starting",
        "prompt_id": None,
        "progress": None,
        "error": None,
        "image": None,
        "session_id": in_.session_id,
        "message_id": in_.message_id,
        "prompt_en": in_.prompt_en,
        "aspect_ratio": in_.aspect_ratio,
        "seed": seed,
    }
    asyncio.get_event_loop().create_task(_run_generation(gen_id))
    return {"generation_id": gen_id, "seed": seed}


async def _ws_progress(gen_id: str, prompt_id: str, client_id: str) -> None:
    st = GENERATIONS[gen_id]
    ws_base = comfy_client.COMFY_URL.replace("http://", "ws://").replace("https://", "wss://")
    url = ws_base + "/ws?clientId=" + client_id
    try:
        async with websockets.connect(url, max_size=None, open_timeout=10) as ws:
            async for raw in ws:
                try:
                    d = json.loads(raw)
                except Exception:
                    continue
                payload = d.get("data") if isinstance(d.get("data"), dict) else {}
                if payload.get("prompt_id") != prompt_id:
                    continue
                t = d.get("type")
                if t == "progress" and isinstance(payload.get("value"), (int, float)):
                    m = payload.get("max")
                    st["progress"] = {"value": int(payload["value"]), "max": int(m) if isinstance(m, (int, float)) else st["steps"]}
    except Exception:
        pass


async def _run_generation(gen_id: str) -> None:
    st = GENERATIONS[gen_id]
    ws_task = None
    try:
        workflow = comfy_client.build_workflow(
            st["prompt_en"], st["aspect_ratio"], st["seed"],
            f"gui_s{st['session_id']}_{gen_id}",
        )
        st["steps"] = int((workflow.get("459:458", {}).get("inputs") or {}).get("steps", 20))
        client_id = uuid.uuid4().hex
        prompt_id = await asyncio.to_thread(comfy_client.submit, workflow, client_id)
        st["prompt_id"] = prompt_id
        st["state"] = "running"
        ws_task = asyncio.create_task(_ws_progress(gen_id, prompt_id, client_id))
        deadline = time.time() + 1800
        while time.time() < deadline:
            await asyncio.sleep(3)
            info = await asyncio.to_thread(comfy_client.poll, prompt_id)
            if info["state"] == "done":
                img = info["images"][0]
                data = await asyncio.to_thread(comfy_client.fetch_image, img["filename"], img.get("subfolder", ""))
                sdir = ASSETS / str(st["session_id"])
                sdir.mkdir(parents=True, exist_ok=True)
                fname = f"{gen_id}_{st['seed']}.png"
                (sdir / fname).write_bytes(data)
                image_id = db.add_image(
                    st["session_id"], st["message_id"], st["prompt_en"],
                    st["seed"], 20, 1.0, st["aspect_ratio"], f"{sdir.name}/{fname}",
                )
                st["state"] = "done"
                st["image"] = {"id": image_id, "url": f"/api/images/{image_id}", "seed": st["seed"]}
                return
            if info["state"] == "error":
                st["state"] = "error"
                st["error"] = info.get("message") or "generation failed"
                return
            if info.get("progress"):
                st["progress"] = info["progress"]
        st["state"] = "error"
        st["error"] = "timeout (30 min)"
    except Exception as e:
        st["state"] = "error"
        st["error"] = str(e)
    finally:
        if ws_task is not None:
            ws_task.cancel()


@app.get("/api/generation/{gen_id}")
def api_generation(gen_id: str):
    st = GENERATIONS.get(gen_id)
    if not st:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "state": st["state"],
        "progress": st["progress"],
        "error": st["error"],
        "image": st["image"],
        "aspect_ratio": st["aspect_ratio"],
        "prompt_en": st["prompt_en"],
        "seed": st["seed"],
    }


@app.get("/api/images/{image_id}")
def get_image(image_id: int):
    row = db.get_image(image_id)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    p = ASSETS / row["filename"]
    if not p.exists():
        return JSONResponse({"error": "file missing"}, status_code=404)
    return FileResponse(str(p), media_type="image/png")


class SettingsIn(BaseModel):
    system_prompt: str | None = None


@app.get("/api/settings")
def get_settings():
    return {"system_prompt": db.get_setting("system_prompt")}


@app.post("/api/settings")
def set_settings(in_: SettingsIn):
    if in_.system_prompt is None:
        db.delete_setting("system_prompt")
    else:
        db.set_setting("system_prompt", in_.system_prompt)
    return {"system_prompt": db.get_setting("system_prompt") or SYSTEM_PROMPT}
