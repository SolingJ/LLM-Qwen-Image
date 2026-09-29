import json
import os
from pathlib import Path

import httpx

COMFY_URL = os.environ.get("COMFY_URL", "http://localhost:8000").rstrip("/")
TEMPLATE_PATH = Path(__file__).resolve().parent / "workflow_template.json"
TEMPLATE = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))

ASPECTS = [
    "1:1 (Square)",
    "2:3 (Portrait Photo)",
    "3:2 (Photo)",
    "3:4 (Portrait Standard)",
    "4:3 (Standard)",
    "9:16 (Portrait Widescreen)",
    "16:9 (Widescreen)",
    "21:9 (Ultrawide)",
]


def status() -> dict:
    r = httpx.get(f"{COMFY_URL}/system_stats", timeout=5)
    r.raise_for_status()
    data = r.json()
    devices = data.get("devices") or []
    dev = devices[0] if devices else {}
    return {
        "online": True,
        "version": (data.get("system") or {}).get("comfyui_version"),
        "vram_free_mb": round(dev.get("vram_free", 0) / 1e6, 1),
    }


def build_workflow(prompt_en: str, aspect_ratio: str, seed: int, prefix: str) -> dict:
    wf = json.loads(json.dumps(TEMPLATE))
    wf["13"]["inputs"]["aspect_ratio"] = aspect_ratio if aspect_ratio in ASPECTS else "1:1 (Square)"
    wf["459:452"]["inputs"]["prompt"] = prompt_en
    wf["459:458"]["inputs"]["seed"] = seed
    wf["461"]["inputs"]["filename_prefix"] = prefix
    return wf


def submit(workflow: dict, client_id: str = "") -> str:
    payload: dict = {"prompt": workflow}
    if client_id:
        payload["client_id"] = client_id
    r = httpx.post(f"{COMFY_URL}/prompt", json=payload, timeout=30)
    r.raise_for_status()
    return r.json().get("prompt_id", "")


def poll(prompt_id: str) -> dict:
    try:
        r = httpx.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10)
        if r.status_code == 200:
            entry = r.json().get(prompt_id)
            if entry:
                images = []
                for node_out in (entry.get("outputs") or {}).values():
                    for img in node_out.get("images", []):
                        images.append({"filename": img["filename"], "subfolder": img.get("subfolder", "")})
                if images:
                    return {"state": "done", "images": images, "progress": entry.get("progress")}
                status_obj = entry.get("status") or {}
                if status_obj.get("status") == "error":
                    detail = json.dumps(status_obj.get("messages") or [], ensure_ascii=False)[:500]
                    return {"state": "error", "message": detail or "prompt failed"}
                return {"state": "running", "progress": entry.get("progress")}
    except Exception:
        pass
    try:
        r = httpx.get(f"{COMFY_URL}/queue", timeout=10)
        if r.status_code == 200:
            q = r.json()
            for group in ("queue_running", "queue_pending"):
                for item in q.get(group, []):
                    if item.get("prompt_id") == prompt_id:
                        return {"state": "running", "progress": None}
    except Exception:
        pass
    return {"state": "unknown", "progress": None}


def fetch_image(filename: str, subfolder: str = "") -> bytes:
    r = httpx.get(
        f"{COMFY_URL}/view",
        params={"filename": filename, "subfolder": subfolder, "type": "output"},
        timeout=60,
    )
    r.raise_for_status()
    return r.content
