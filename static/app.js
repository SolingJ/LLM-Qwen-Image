const state = {
  sessions: [],
  current: null,
  model: null,
  base: null,
  thinking: true,
  maxTokens: 4096,
  busy: false,
};

let attachments = [];

const ASPECT_OPTIONS = [
  "1:1 (Square)",
  "3:2 (Photo)",
  "2:3 (Portrait Photo)",
  "3:4 (Portrait Standard)",
  "4:3 (Standard)",
  "9:16 (Portrait Widescreen)",
  "16:9 (Widescreen)",
  "21:9 (Ultrawide)",
];

function createAspectSelect(value) {
  const sel = document.createElement("select");
  sel.title = "アスペクト比";
  for (const o of ASPECT_OPTIONS) {
    const opt = document.createElement("option");
    opt.value = o;
    opt.textContent = o;
    sel.appendChild(opt);
  }
  if (ASPECT_OPTIONS.includes(value)) sel.value = value;
  return sel;
}

function renderImageRequestAction(req, parentEl) {
  const row = document.createElement("div");
  row.className = "img-req-row";
  const chip = document.createElement("span");
  chip.className = "chip";
  const prompt = req.prompt_en || "";
  chip.textContent = "画像生成: " + (prompt.length > 60 ? prompt.slice(0, 60) + "…" : prompt);
  const sel = createAspectSelect(req.aspect_ratio || "1:1 (Square)");
  const btn = document.createElement("button");
  btn.className = "primary";
  btn.textContent = "画像を生成する";
  btn.onclick = () => startGeneration(req, parentEl, sel);
  row.append(chip, sel, btn);
  parentEl.appendChild(row);
}

const $ = (id) => document.getElementById(id);

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${path}`);
  return r.json();
}

function scroll() {
  const c = $("chat");
  c.scrollTop = c.scrollHeight;
}

function stripImageJson(text) {
  return text.replace(/```json[\s\S]*?```/g, "").replace(/```[\s\S]*?```/g, "").replace(/\s+$/, "");
}

const TS = String.fromCharCode(60) + "think" + String.fromCharCode(62);
const TE = String.fromCharCode(60) + "/think" + String.fromCharCode(62);

function stripThinking(text) {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const s = text.indexOf(TS, i);
    if (s === -1) { out += text.slice(i); break; }
    out += text.slice(i, s);
    const e = text.indexOf(TE, s);
    if (e === -1) break;
    i = e + TE.length;
  }
  return out;
}

// ---------- sessions ----------
async function loadSessions() {
  let list;
  try { list = await api("/api/sessions"); } catch { return; }
  state.sessions = list;
  const el = $("session-list");
  el.innerHTML = "";
  for (const s of list) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === state.current ? " active" : "");
    const t = document.createElement("div");
    t.textContent = s.title || `セッション ${s.id}`;
    const meta = document.createElement("div");
    meta.className = "meta";
    const d = s.created_at ? new Date(s.created_at) : null;
    meta.textContent = `${d ? d.toLocaleString() : ""} · 画像${s.image_count}`;
    const del = document.createElement("button");
    del.className = "session-delete";
    del.textContent = "削除";
    del.title = "このセッションを削除";
    del.onclick = (e) => { e.stopPropagation(); deleteSession(s.id); };
    item.append(t, meta, del);
    item.onclick = () => openSession(s.id);
    el.appendChild(item);
  }
}

async function deleteSession(id) {
  if (state.busy && state.current === id) {
    alert("チャット中のセッションは削除できません");
    return;
  }
  if (!confirm(`セッション ${id} を削除しますか？`)) return;
  try {
    await api(`/api/sessions/${id}`, { method: "DELETE" });
    if (state.current === id) {
      state.current = null;
      $("chat").innerHTML = "";
    }
    loadSessions();
  } catch (e) {
    alert("削除失敗: " + e);
  }
}

function renderUserContent(wrap, m) {
  let parts = null;
  if (typeof m.content === "string" && m.content.startsWith("[")) {
    try {
      const v = JSON.parse(m.content);
      if (Array.isArray(v)) parts = v;
    } catch { /* ignore */ }
  }
  if (parts) {
    for (const p of parts) {
      if (p.type === "text") {
        const b = document.createElement("div");
        b.className = "bubble";
        b.textContent = p.text || "";
        wrap.appendChild(b);
      } else if (p.type === "image_url" && p.image_url) {
        const im = document.createElement("img");
        im.className = "msg-attach";
        im.src = p.image_url.url;
        wrap.appendChild(im);
      }
    }
    return;
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = m.content || "";
  wrap.appendChild(bubble);
}

function addMetaFooter(wrap, m) {
  if (m.tps) {
    const f = document.createElement("div");
    f.className = "msg-meta";
    const think = m.thinking != null ? (m.thinking ? " · thinking on" : " · thinking off") : "";
    f.textContent = `${m.tps} tok/s · ${m.tokens} tok · ${m.seconds}s${think}`;
    wrap.appendChild(f);
  }
}

async function openSession(id) {
  state.current = id;
  let data;
  try { data = await api(`/api/sessions/${id}`); } catch { return; }
  const chat = $("chat");
  chat.innerHTML = "";
  const imagesByMsg = {};
  for (const im of data.images) (imagesByMsg[im.message_id] ||= []).push(im);
  for (const m of data.messages) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + m.role;
    if (m.role === "user") {
      renderUserContent(wrap, m);
    } else {
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = stripImageJson(stripThinking(m.content || ""));
      wrap.appendChild(bubble);
      let req = null;
      if (m.image_request) {
        try { req = JSON.parse(m.image_request); } catch { req = null; }
      }
      addMetaFooter(wrap, m);
      const imgs = imagesByMsg[m.id] || [];
      if (req && imgs.length === 0) {
        renderImageRequestAction(
          { message_id: m.id, prompt_en: req.prompt_en, aspect_ratio: req.aspect_ratio || "1:1 (Square)" },
          wrap,
        );
      }
      for (const im of imgs) addImageBox(wrap, im);
    }
    chat.appendChild(wrap);
  }
  scroll();
  loadSessions();
}

function addImageBox(wrap, im) {
  const box = document.createElement("div");
  box.className = "msg-img";
  const img = document.createElement("img");
  img.src = `/api/images/${im.id}`;
  img.loading = "lazy";
  const cap = document.createElement("div");
  cap.className = "img-cap";
  const sp = document.createElement("span");
  sp.textContent = `seed ${im.seed} · ${im.aspect || ""}`;
  const b = document.createElement("button");
  b.textContent = "再生成";
  b.onclick = () => startGeneration(
    { message_id: im.message_id, prompt_en: im.prompt_en, aspect_ratio: im.aspect || "1:1 (Square)" },
    wrap,
  );
  cap.append(sp, b);
  box.append(img, cap);
  wrap.appendChild(box);
}

// ---------- attachments ----------
function readAsDataURL(f) {
  return new Promise((res) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.readAsDataURL(f);
  });
}

function renderAttach() {
  const box = $("attach-preview");
  box.innerHTML = "";
  attachments.forEach((a, i) => {
    const wrap = document.createElement("div");
    wrap.className = "attach-chip";
    const im = document.createElement("img");
    im.src = a.dataUrl;
    const x = document.createElement("button");
    x.textContent = "x";
    x.onclick = () => { attachments.splice(i, 1); renderAttach(); };
    wrap.append(im, x);
    box.appendChild(wrap);
  });
}

// ---------- chat ----------
async function send() {
  if (state.busy) return;
  const text = $("input").value.trim();
  if (!text && attachments.length === 0) return;
  $("input").value = "";

  if (!state.current) {
    const s = await api("/api/sessions", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } });
    state.current = s.id;
  }

  const chat = $("chat");
  const userMsg = document.createElement("div");
  userMsg.className = "msg user";
  if (attachments.length === 0) {
    const ub = document.createElement("div");
    ub.className = "bubble";
    ub.textContent = text;
    userMsg.appendChild(ub);
  } else {
    for (const a of attachments) {
      const im = document.createElement("img");
      im.className = "msg-attach";
      im.src = a.dataUrl;
      userMsg.appendChild(im);
    }
    if (text) {
      const ub = document.createElement("div");
      ub.className = "bubble";
      ub.textContent = text;
      userMsg.appendChild(ub);
    }
  }
  chat.appendChild(userMsg);

  const asstMsg = document.createElement("div");
  asstMsg.className = "msg assistant";
  const ab = document.createElement("div");
  ab.className = "bubble";
  ab.innerHTML = '<span class="spinner"></span> 考え中…';
  asstMsg.appendChild(ab);
  chat.appendChild(asstMsg);
  scroll();

  const payload = attachments.length === 0
    ? text
    : [
        { type: "text", text },
        ...attachments.map((a) => ({ type: "image_url", image_url: { url: a.dataUrl } })),
      ];
  attachments = [];
  renderAttach();

  state.busy = true;
  $("send").disabled = true;
  const cs = { acc: "", started: false, imgReq: null, thinkEl: null, thinkText: "" };

  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.current,
        message: payload,
        model: state.model,
        base: state.base,
        thinking: state.thinking,
        max_tokens: state.maxTokens,
      }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, i);
        buf = buf.slice(i + 2);
        handleFrame(frame, asstMsg, ab, cs);
      }
    }
  } catch (e) {
    showError(asstMsg, String(e));
  }

  state.busy = false;
  $("send").disabled = false;
  loadSessions();
}

function handleFrame(frame, asstMsg, ab, cs) {
  let event = "message";
  let data = "{}";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  let d;
  try { d = JSON.parse(data); } catch { return; }

  if (event === "token") {
    if (!cs.started) { ab.textContent = ""; cs.started = true; }
    cs.acc += d.text;
    if (d.thinking) {
      if (!cs.thinkEl) {
        const det = document.createElement("details");
        det.className = "think-box";
        const sum = document.createElement("summary");
        sum.textContent = "thinking";
        const pre = document.createElement("pre");
        det.append(sum, pre);
        cs.thinkEl = pre;
        asstMsg.insertBefore(det, ab);
      }
      cs.thinkText += d.text;
      cs.thinkEl.textContent = cs.thinkText;
    } else {
      ab.textContent += d.text;
    }
    scroll();
    } else if (event === "image_request") {
      cs.imgReq = d;
    } else if (event === "error") {
    showError(asstMsg, d.message || "unknown error");
  } else if (event === "done") {
    if (!cs.started) {
      ab.textContent = "(応答なし)";
    } else {
      ab.textContent = stripImageJson(stripThinking(cs.acc));
      if (cs.thinkEl) {
        const sum = cs.thinkEl.parentElement.querySelector("summary");
        sum.textContent = "thinking (" + cs.thinkText.trim().length + " chars)";
      }
      if (cs.imgReq) {
        renderImageRequestAction(cs.imgReq, asstMsg);
      }
    }
    if (d.tps) {
      const f = document.createElement("div");
      f.className = "msg-meta";
      const think = state.thinking ? " · thinking on" : " · thinking off";
      f.textContent = `${d.tps} tok/s · ${d.tokens} tok · ${d.seconds}s${think}`;
      asstMsg.appendChild(f);
    }
  }
}

function showError(parentEl, msg) {
  const box = document.createElement("div");
  box.className = "error-box";
  box.textContent = "エラー: " + msg;
  parentEl.appendChild(box);
}

// ---------- generation ----------
function startGeneration(req, parentEl, aspectSel) {
  const box = document.createElement("div");
  box.className = "gen-box";
  box.innerHTML = '<span class="spinner"></span> 画像生成中… (準備)';
  parentEl.appendChild(box);
  scroll();

  const aspect = aspectSel ? aspectSel.value : (req.aspect_ratio || "1:1 (Square)");

  api("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: state.current,
      message_id: req.message_id,
      prompt_en: req.prompt_en,
      aspect_ratio: aspect,
    }),
  }).then(({ generation_id }) => {
    const t = setInterval(async () => {
      let st;
      try { st = await api(`/api/generation/${generation_id}`); } catch { return; }
      if (st.state === "running") {
        const p = st.progress;
        const pct = p && p.max ? Math.min(100, Math.round((p.value / p.max) * 100)) : null;
        box.innerHTML = pct != null
          ? `<div class="gen-prog"><div class="gen-prog-bar" style="width:${pct}%"></div></div>画像生成中… ${pct}%`
          : '<span class="spinner"></span> 画像生成中… (キュー)';
      } else if (st.state === "done" && st.image) {
        clearInterval(t);
        box.remove();
        addImageBox(parentEl, {
          id: st.image.id,
          seed: st.seed,
          aspect: st.aspect_ratio,
          message_id: req.message_id,
          prompt_en: st.prompt_en,
        });
        scroll();
        loadSessions();
      } else if (st.state === "error") {
        clearInterval(t);
        box.className = "error-box";
        box.textContent = "生成エラー: " + (st.error || "unknown");
      }
    }, 1500);
  }).catch((e) => {
    box.className = "error-box";
    box.textContent = "生成エラー: " + e;
  });
}

// ---------- model picker ----------
async function loadModels() {
  let eps;
  try { eps = await api("/api/models"); } catch { return; }
  const sel = $("model-select");
  const prev = state.model;
  sel.innerHTML = "";
  for (const ep of eps) {
    if (!ep.online) continue;
    const g = document.createElement("optgroup");
    g.label = ep.label;
    for (const m of ep.models) {
      const o = document.createElement("option");
      o.value = m;
      o.textContent = m;
      o.dataset.base = ep.base;
      if (/qwen3\.8-27b/i.test(m) && ep.base.includes(":8080")) o.dataset.pref = "1";
      g.appendChild(o);
    }
    sel.appendChild(g);
  }
  let chosen = prev ? [...sel.options].find((o) => o.value === prev) : null;
  if (!chosen) chosen = [...sel.options].find((o) => o.dataset.pref === "1");
  if (chosen) sel.value = chosen.value;
  applyModelChoice();
}

function applyModelChoice() {
  const sel = $("model-select");
  const opt = sel.options[sel.selectedIndex];
  if (!opt) return;
  state.model = opt.value;
  state.base = opt.dataset.base;
  $("model-hint").textContent = state.base.includes(":1234")
    ? "(LM Studio: GPU1でComfyUIと共有、生成が重くなる可能性。画像入力はモデルによる)"
    : "(llama.cpp: GPU0専用。現在のビルドはテキスト専用で画像入力は非対応)";
}

// ---------- status ----------
async function pollLlm() {
  let st;
  try { st = await api("/api/llm/status"); } catch { return; }
  const dot = $("llm-dot");
  const txt = $("llm-text");
  const btn = $("llm-toggle");
  if (st.state === "running") {
    dot.className = "dot running";
    txt.textContent = "LLM 稼働中 " + (st.managed ? "(GUI管理)" : "(外部)");
    btn.textContent = "Stop LLM";
    btn.disabled = false;
    btn.onclick = async () => {
      if (!confirm("llama-server を停止しますか？")) return;
      await api("/api/llm/stop", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } });
    };
  } else if (st.state === "starting") {
    dot.className = "dot starting";
    txt.textContent = "LLM 起動中 (モデル読込中)…";
    btn.textContent = "…";
    btn.disabled = true;
  } else {
    dot.className = "dot stopped";
    txt.textContent = "LLM 停止中";
    btn.textContent = "Start LLM";
    btn.disabled = false;
    btn.onclick = async () => {
      await api("/api/llm/start", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } });
    };
  }
  if (st.state === "running" && !state.model) loadModels();
}

async function pollComfy() {
  let st;
  try { st = await api("/api/comfy/status"); } catch { st = { online: false }; }
  $("comfy-text").textContent = st.online
    ? `ComfyUI 稼働中 (VRAM空き ${st.vram_free_mb} MB)`
    : "ComfyUI 接続不可";
}

// ---------- init ----------
window.addEventListener("DOMContentLoaded", () => {
  $("send").onclick = send;
  $("new-session").onclick = async () => {
    const s = await api("/api/sessions", { method: "POST", body: "{}", headers: { "Content-Type": "application/json" } });
    state.current = s.id;
    $("chat").innerHTML = "";
    loadSessions();
  };
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("model-select").onchange = applyModelChoice;
  $("thinking-toggle").onchange = (e) => { state.thinking = e.target.checked; };
  const mt = $("max-tokens");
  const savedMt = Number(localStorage.getItem("max.tokens"));
  if (savedMt >= 16) { state.maxTokens = savedMt; mt.value = String(savedMt); }
  mt.onchange = (e) => {
    const v = Math.max(16, Math.floor(Number(e.target.value) || 4096));
    state.maxTokens = v;
    mt.value = String(v);
    localStorage.setItem("max.tokens", String(v));
  };
  $("attach-btn").onclick = () => $("file-input").click();
  $("file-input").onchange = async (e) => {
    for (const f of e.target.files) {
      if (attachments.length >= 4) break;
      attachments.push({ dataUrl: await readAsDataURL(f), name: f.name });
    }
    e.target.value = "";
    renderAttach();
  };

  $("settings-toggle").onclick = () => {
    const p = $("settings-panel");
    p.hidden = !p.hidden;
  };
  $("sp-save").onclick = async () => {
    const v = $("system-prompt").value;
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ system_prompt: v || null }),
      headers: { "Content-Type": "application/json" },
    });
    $("settings-panel").hidden = true;
  };
  $("sp-reset").onclick = async () => {
    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({ system_prompt: null }),
      headers: { "Content-Type": "application/json" },
    });
    $("system-prompt").value = "";
    $("settings-panel").hidden = true;
  };

  loadModels();
  loadSessions();
  pollLlm();
  setInterval(pollLlm, 5000);
  pollComfy();
  setInterval(pollComfy, 10000);
  (async () => {
    try {
      const st = await api("/api/settings");
      if (st.system_prompt) $("system-prompt").value = st.system_prompt;
    } catch { /* ignore */ }
  })();
});
