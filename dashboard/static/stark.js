// Stark Panel — frontend
(() => {
  const $ = (id) => document.getElementById(id);
  const monitorsEl = $("monitors");
  const cardsEl    = $("cards");
  const logsEl     = $("logs");
  const windowsEl  = $("windows");
  const statusText = $("statusText");
  const clockEl    = $("clock");

  // ── Clock ──
  setInterval(() => {
    const d = new Date();
    clockEl.textContent = d.toLocaleTimeString();
  }, 1000);

  // ── WebSocket live ──
  function connectWS() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { statusText.textContent = "Online"; };
    ws.onclose = () => {
      statusText.textContent = "Reconectando...";
      setTimeout(connectWS, 1500);
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "snapshot") renderState(msg.state);
      else if (msg.type === "card") upsertCard(msg.card);
      else if (msg.type === "card_remove") removeCard(msg.id);
      else if (msg.type === "log") appendLog(msg.entry);
    };
  }

  // ── Render state ──
  let state = { monitors: [], cards: [], logs: [] };

  function renderState(s) {
    state = s;
    renderMonitors(s.monitors || []);
    cardsEl.innerHTML = "";
    (s.cards || []).forEach(upsertCard);
    logsEl.innerHTML = "";
    (s.logs || []).forEach(appendLog);
    fetchWindows();
  }

  function renderMonitors(mons) {
    monitorsEl.innerHTML = mons.map(m => `
      <div class="monitor">
        <div class="mname">#${m.id} ${m.name.split("\\\\").pop() || m.name}</div>
        <div class="mres">${m.width}×${m.height} @ (${m.x},${m.y})</div>
        ${m.primary ? '<div class="mpri">PRIMARY</div>' : ''}
      </div>
    `).join("");
  }

  function upsertCard(c) {
    if (!c) return;
    let el = document.querySelector(`.card[data-id="${c.id}"]`);
    const html = `
      <div class="ctitle">${escapeHtml(c.title || c.id)}</div>
      <div class="cbody">${escapeHtml(c.body || "")}</div>
      <div class="cts">${new Date(c.ts || Date.now()).toLocaleTimeString()}</div>
    `;
    if (el) { el.innerHTML = html; return; }
    el = document.createElement("div");
    el.className = "card";
    el.setAttribute("data-id", c.id);
    el.innerHTML = html;
    cardsEl.prepend(el);
  }

  function removeCard(id) {
    const el = document.querySelector(`.card[data-id="${id}"]`);
    if (el) el.remove();
  }

  function appendLog(entry) {
    if (!entry) return;
    const div = document.createElement("div");
    div.className = `log ${entry.level || ""}`;
    div.innerHTML = `
      <span class="lts">${new Date(entry.ts).toLocaleTimeString()}</span>
      <span class="llvl">[${(entry.level || "info").toUpperCase()}]</span>
      <span>${escapeHtml(entry.msg || "")}</span>
    `;
    logsEl.appendChild(div);
    logsEl.scrollTop = logsEl.scrollHeight;
    while (logsEl.children.length > 200) logsEl.firstChild.remove();
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, c => ({
      "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"
    }[c]));
  }

  // ── Windows list ──
  async function fetchWindows() {
    try {
      const r = await fetch("/api/windows");
      const j = await r.json();
      renderWindows(j.windows || []);
    } catch {}
  }

  function renderWindows(ws) {
    const monOptions = (state.monitors || []).map(m =>
      `<option value="${m.id}">Mon ${m.id}</option>`).join("");
    windowsEl.innerHTML = ws.map(w => `
      <div class="win" data-hwnd="${w.hwnd}">
        <span class="wtitle" title="${escapeHtml(w.title)}">${escapeHtml(w.title)}</span>
        <select class="mon">${monOptions}</select>
        <select class="ratio">
          <option value="1.0">Cheia</option>
          <option value="0.75">75%</option>
          <option value="0.5">50%</option>
          <option value="0.33">33%</option>
        </select>
        <button class="mv">Mover</button>
      </div>
    `).join("");
    windowsEl.querySelectorAll(".mv").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        const row = e.target.closest(".win");
        const hwnd = parseInt(row.getAttribute("data-hwnd"));
        const mon = parseInt(row.querySelector(".mon").value);
        const ratio = parseFloat(row.querySelector(".ratio").value);
        const fs = ratio >= 0.999;
        await fetch("/api/window/move", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ hwnd, monitor: mon, ratio, fullscreen: fs }),
        });
      });
    });
  }

  $("refreshBtn").addEventListener("click", async () => {
    const r = await fetch("/api/state");
    renderState(await r.json());
  });

  // ── Animated bg (HUD rings) ──
  const cvs = $("bg"), ctx = cvs.getContext("2d");
  function resize() { cvs.width = innerWidth; cvs.height = innerHeight; }
  addEventListener("resize", resize); resize();
  let t = 0;
  function frame() {
    t += 0.005;
    ctx.clearRect(0, 0, cvs.width, cvs.height);
    const cx = cvs.width * 0.85, cy = cvs.height * 0.5;
    for (let i = 0; i < 6; i++) {
      const r = 60 + i * 50 + Math.sin(t + i) * 8;
      ctx.beginPath();
      ctx.strokeStyle = `rgba(0,216,255,${0.25 - i * 0.035})`;
      ctx.lineWidth = 1;
      ctx.arc(cx, cy, r, t * (i % 2 ? 1 : -1), t * (i % 2 ? 1 : -1) + Math.PI * 1.5);
      ctx.stroke();
    }
    // grid
    ctx.strokeStyle = "rgba(0,216,255,0.04)";
    ctx.lineWidth = 1;
    for (let x = 0; x < cvs.width; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, cvs.height); ctx.stroke();
    }
    for (let y = 0; y < cvs.height; y += 40) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(cvs.width, y); ctx.stroke();
    }
    requestAnimationFrame(frame);
  }
  frame();

  // ── Init ──
  fetch("/api/state").then(r => r.json()).then(renderState).catch(()=>{});
  connectWS();
})();
