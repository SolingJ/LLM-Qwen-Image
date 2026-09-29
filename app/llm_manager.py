import json
import os
import subprocess
import time
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent.parent
LLAMA_SERVER = os.environ.get("LLAMA_SERVER", "")
MODEL = os.environ.get("LLM_MODEL", "")
ALIAS = os.environ.get("LLM_ALIAS", "local-model")
HOST = os.environ.get("LLM_HOST", "127.0.0.1")
PORT = int(os.environ.get("LLM_PORT", "8080"))
BASE_URL = f"http://{HOST}:{PORT}"
STATE_FILE = BASE / ".llm_state.json"
LOG_FILE = BASE / "llm.log"

ARGS = [
    "--model", MODEL,
    "--alias", ALIAS,
    "--device", "CUDA0",
    "--gpu-layers", "all",
    "--fit", "on",
    "--ctx-size", "32768",
    "--batch-size", "2048",
    "--ubatch-size", "512",
    "--flash-attn", "on",
    "--cache-type-k", "q4_0",
    "--cache-type-v", "q4_0",
    "--cpu-ram", "4096",
    "--jinja",
    "--host", HOST,
    "--port", str(PORT),
    "--spec-type", "draft-mtp",
    "--spec-draft-n-max", "3",
    "--spec-draft-p-min", "0",
    "--spec-draft-type-k", "q4_0",
    "--spec-draft-type-v", "q4_0",
    "--device-draft", "CUDA0",
    "--spec-draft-ngl", "all",
]


def _health() -> bool:
    try:
        r = httpx.get(f"{BASE_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return "Information Not Found" not in out and "ERROR" not in out.upper()
    except Exception:
        return False


def _find_pids() -> list[int]:
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\").ProcessId",
            ],
            capture_output=True, text=True, timeout=15,
        )
        return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]
    except Exception:
        return []


def start() -> dict:
    st = _read_state()
    if st and st.get("pid") and _pid_alive(st["pid"]):
        return {"started": False, "reason": "already_running", "pid": st["pid"]}
    if _health():
        pids = _find_pids()
        return {"started": False, "reason": "already_running_external", "pid": pids[0] if pids else None}
    if not LLAMA_SERVER or not MODEL:
        return {"started": False, "reason": "LLAMA_SERVER and LLM_MODEL environment variables are required"}
    if not Path(LLAMA_SERVER).exists():
        return {"started": False, "reason": "llama-server not found", "path": LLAMA_SERVER}
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = "0"
    log = open(LOG_FILE, "ab")
    proc = subprocess.Popen(
        [LLAMA_SERVER] + ARGS,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=str(BASE),
        env=env,
    )
    log.close()
    _write_state({"pid": proc.pid, "started_at": time.time()})
    return {"started": True, "pid": proc.pid}


def stop() -> dict:
    pids: list[int] = []
    st = _read_state()
    if st and st.get("pid") and _pid_alive(st["pid"]):
        pids.append(st["pid"])
    pids += [p for p in _find_pids() if p not in pids]
    killed: list[int] = []
    for p in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True, timeout=15)
            killed.append(p)
        except Exception:
            pass
    if st and st.get("pid") in killed:
        STATE_FILE.unlink(missing_ok=True)
    return {"stopped": bool(killed), "pids": killed}


def status() -> dict:
    st = _read_state()
    if st and st.get("pid") and _pid_alive(st["pid"]):
        return {
            "state": "running" if _health() else "starting",
            "managed": True,
            "pid": st["pid"],
            "model": ALIAS,
        }
    if _health():
        pids = _find_pids()
        return {"state": "running", "managed": False, "pid": pids[0] if pids else None, "model": ALIAS}
    return {"state": "stopped", "managed": False, "pid": None, "model": ALIAS}
