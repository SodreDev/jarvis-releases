// IDE frontend — Monaco + xterm.js + multi-terminal + runner + file manager
(() => {
  const $ = (id) => document.getElementById(id);
  let currentProject = null;
  let currentFile = null;
  let editor = null;

  // ──────────────────────────────────────────────────────────────────────
  // Monaco editor
  // ──────────────────────────────────────────────────────────────────────
  require.config({ paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs" } });
  require(["vs/editor/editor.main"], () => {
    editor = monaco.editor.create($("editor"), {
      value: "// Selecione ou crie um arquivo",
      language: "javascript",
      theme: "vs-dark",
      automaticLayout: true,
      fontSize: 13,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
    });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveCurrent(); }
    });
  });

  function languageFor(filename) {
    const ext = (filename.split(".").pop() || "").toLowerCase();
    return { py:"python", js:"javascript", ts:"typescript", html:"html", css:"css",
             json:"json", md:"markdown", yml:"yaml", yaml:"yaml", sh:"shell",
             ps1:"powershell", c:"c", cpp:"cpp", java:"java", rs:"rust",
             go:"go", rb:"ruby", php:"php", cs:"csharp", sql:"sql" }[ext] || "plaintext";
  }

  // ──────────────────────────────────────────────────────────────────────
  // Multi-terminal
  // ──────────────────────────────────────────────────────────────────────
  const terms = {};          // id → {term, fit, ws, div}
  let activeTermId = null;
  let termCounter = 0;

  function createTerminalInstance(termId) {
    const t = new Terminal({
      fontFamily: "Consolas, monospace", fontSize: 13,
      theme: { background: "#000", foreground: "#d9e7ff", cursor: "#00d8ff" },
      convertEol: true,
    });
    const fit = new FitAddon.FitAddon();
    t.loadAddon(fit);
    const div = document.createElement("div");
    div.style.cssText = "width:100%;height:100%;display:none;position:absolute;top:0;left:0";
    div.id = `term-${termId}`;
    $("term-container").appendChild(div);
    t.open(div);
    setTimeout(() => fit.fit(), 60);
    terms[termId] = { term: t, fit, ws: null, div };
    return terms[termId];
  }

  function switchTerm(termId) {
    activeTermId = termId;
    Object.entries(terms).forEach(([id, t]) => { t.div.style.display = id === String(termId) ? "block" : "none"; });
    document.querySelectorAll(".term-tab").forEach(el =>
      el.classList.toggle("active", el.dataset.tid === String(termId)));
    const t = terms[termId];
    if (t) { try { t.fit.fit(); } catch {} }
  }

  function addTermTab(label, termId) {
    const tabs = $("term-tabs");
    const tab = document.createElement("div");
    tab.className = "term-tab";
    tab.dataset.tid = String(termId);
    tab.innerHTML = `<span>${label}</span> <span class="close-tab" data-tid="${termId}">✕</span>`;
    tab.querySelector("span:first-child").addEventListener("click", () => switchTerm(termId));
    tab.querySelector(".close-tab").addEventListener("click", (e) => {
      e.stopPropagation();
      closeTerm(termId);
    });
    tabs.appendChild(tab);
    return tab;
  }

  function closeTerm(termId) {
    const t = terms[termId];
    if (!t) return;
    if (t.ws) { try { t.ws.close(); } catch {} }
    t.div.remove();
    delete terms[termId];
    document.querySelector(`.term-tab[data-tid="${termId}"]`)?.remove();
    // Activate another tab
    const ids = Object.keys(terms);
    if (ids.length) switchTerm(ids[ids.length - 1]);
    else activeTermId = null;
  }

  function openTerminal(slug, label) {
    termCounter++;
    const termId = String(termCounter);
    const info = createTerminalInstance(termId);
    addTermTab(label || `term ${termCounter}`, termId);
    connectTermWS(termId, slug);
    switchTerm(termId);
    return termId;
  }

  function connectTermWS(termId, slug) {
    const info = terms[termId];
    if (!info) return;
    if (info.ws) { try { info.ws.close(); } catch {} }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ide/ws/terminal/${encodeURIComponent(slug)}/${encodeURIComponent(termId)}`);
    ws.onmessage = (ev) => info.term.write(ev.data);
    ws.onclose = () => info.term.write("\r\n[terminal desconectado]\r\n");
    info.ws = ws;
    info.term.onData((data) => { if (ws.readyState === 1) ws.send(data); });
  }

  $("addTermBtn").addEventListener("click", () => {
    if (!currentProject) { alert("Selecione um projeto primeiro."); return; }
    openTerminal(currentProject, `shell ${termCounter + 1}`);
  });
  window.addEventListener("resize", () => {
    Object.values(terms).forEach(t => { try { t.fit.fit(); } catch {} });
  });

  // ──────────────────────────────────────────────────────────────────────
  // Projects
  // ──────────────────────────────────────────────────────────────────────
  async function loadProjects() {
    const r = await fetch("/ide/api/projects");
    const j = await r.json();
    const el = $("projects");
    el.innerHTML = (j.projects || []).map(p =>
      `<div class="proj ${p.slug === currentProject ? "active" : ""}" data-slug="${p.slug}">
         📁 ${p.slug} <span style="color:var(--text-dim);font-size:10px">(${p.files})</span>
       </div>`
    ).join("") || "<em style='color:var(--text-dim);font-size:11px'>Nenhum projeto</em>";
    el.querySelectorAll(".proj").forEach(d =>
      d.addEventListener("click", () => openProject(d.getAttribute("data-slug")))
    );
  }

  async function openProject(slug) {
    currentProject = slug;
    if ($("ws-sub")) $("ws-sub").textContent = slug;
    document.querySelectorAll(".proj").forEach(d =>
      d.classList.toggle("active", d.getAttribute("data-slug") === slug));
    await loadTree();
    openTerminal(slug, slug);
    pollRunStatus();
  }

  // ──────────────────────────────────────────────────────────────────────
  // File tree
  // ──────────────────────────────────────────────────────────────────────
  async function loadTree() {
    if (!currentProject) return;
    const r = await fetch(`/ide/api/tree/${encodeURIComponent(currentProject)}`);
    const j = await r.json();
    const el = $("tree");
    el.innerHTML = (j.tree || []).map(n => {
      const indent = (n.path.match(/\//g) || []).length;
      return `<div class="tree-item ${n.type}" data-path="${n.path}" data-type="${n.type}"
                   style="padding-left:${6 + indent * 12}px">
               ${n.type === "dir" ? "📂" : "📄"} ${n.path.split("/").pop()}
             </div>`;
    }).join("");
    el.querySelectorAll(".tree-item.file").forEach(d =>
      d.addEventListener("click", () => {
        el.querySelectorAll(".tree-item").forEach(x => x.classList.remove("selected"));
        d.classList.add("selected");
        openFile(d.getAttribute("data-path"));
      })
    );
    el.querySelectorAll(".tree-item").forEach(d =>
      d.addEventListener("contextmenu", (e) => { e.preventDefault(); showContextMenu(e, d); })
    );
  }

  async function openFile(path) {
    if (!currentProject || !editor) return;
    const r = await fetch(`/ide/api/file/${encodeURIComponent(currentProject)}?path=${encodeURIComponent(path)}`);
    const j = await r.json();
    if (j.error) { alert(j.error); return; }
    currentFile = path;
    $("curFile").textContent = `${currentProject} / ${path}`;
    monaco.editor.setModelLanguage(editor.getModel(), languageFor(path));
    editor.setValue(j.content || "");
  }

  async function saveCurrent() {
    if (!currentProject || !currentFile || !editor) return;
    const r = await fetch(`/ide/api/file/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentFile, content: editor.getValue() })
    });
    const j = await r.json();
    if (!j.ok) alert(j.error || "Falha ao salvar");
  }

  // ──────────────────────────────────────────────────────────────────────
  // Context menu (rename / move / explorer / delete)
  // ──────────────────────────────────────────────────────────────────────
  let ctxTarget = null;
  const ctxMenu = $("ctx-menu");

  function showContextMenu(e, el) {
    ctxTarget = el;
    ctxMenu.style.cssText = `display:block;left:${e.clientX}px;top:${e.clientY}px`;
  }
  document.addEventListener("click", () => { ctxMenu.style.display = "none"; });

  $("ctx-rename").addEventListener("click", async () => {
    if (!ctxTarget || !currentProject) return;
    const oldPath = ctxTarget.getAttribute("data-path");
    const newName = prompt("Novo nome:", oldPath.split("/").pop());
    if (!newName || newName === oldPath.split("/").pop()) return;
    const dir = oldPath.includes("/") ? oldPath.rsplit("/", 1)[0] + "/" : "";
    const dst = dir + newName;
    const r = await fetch(`/ide/api/move/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src: oldPath, dst })
    });
    const j = await r.json();
    if (j.ok) { if (currentFile === oldPath) currentFile = j.path; await loadTree(); }
    else alert(j.error);
  });

  $("ctx-move").addEventListener("click", async () => {
    if (!ctxTarget || !currentProject) return;
    const src = ctxTarget.getAttribute("data-path");
    const dst = prompt("Mover para (caminho relativo):", src);
    if (!dst || dst === src) return;
    const r = await fetch(`/ide/api/move/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ src, dst })
    });
    const j = await r.json();
    if (j.ok) { await loadTree(); } else alert(j.error);
  });

  $("ctx-explorer").addEventListener("click", async () => {
    if (!currentProject) return;
    const path = ctxTarget?.getAttribute("data-path") || "";
    await fetch(`/ide/api/explorer/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path })
    });
  });

  $("ctx-delete").addEventListener("click", async () => {
    if (!ctxTarget || !currentProject) return;
    const path = ctxTarget.getAttribute("data-path");
    if (!confirm(`Excluir '${path}'? Esta ação não pode ser desfeita.`)) return;
    const r = await fetch(`/ide/api/file/${encodeURIComponent(currentProject)}?path=${encodeURIComponent(path)}`, { method: "DELETE" });
    const j = await r.json();
    if (j.ok) { if (currentFile === path) { currentFile = null; $("curFile").textContent = "Nenhum arquivo"; } await loadTree(); }
    else alert(j.error);
  });

  // ──────────────────────────────────────────────────────────────────────
  // Toolbar buttons
  // ──────────────────────────────────────────────────────────────────────
  $("saveBtn").addEventListener("click", saveCurrent);

  $("explorerBtn").addEventListener("click", async () => {
    if (!currentProject) return;
    await fetch(`/ide/api/explorer/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentFile || "" })
    });
  });

  $("deleteBtn").addEventListener("click", async () => {
    if (!currentProject || !currentFile) { alert("Nenhum arquivo selecionado."); return; }
    if (!confirm(`Excluir '${currentFile}'?`)) return;
    const r = await fetch(`/ide/api/file/${encodeURIComponent(currentProject)}?path=${encodeURIComponent(currentFile)}`, { method: "DELETE" });
    const j = await r.json();
    if (j.ok) { currentFile = null; $("curFile").textContent = "Nenhum arquivo"; editor && editor.setValue(""); await loadTree(); }
    else alert(j.error);
  });

  $("createProj").addEventListener("click", async () => {
    const name = $("newProj").value.trim();
    if (!name) return;
    await fetch("/ide/api/projects", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    $("newProj").value = "";
    await loadProjects();
  });

  $("createFile").addEventListener("click", async () => {
    if (!currentProject) { alert("Selecione um projeto"); return; }
    const path = $("newFile").value.trim();
    if (!path) return;
    await fetch(`/ide/api/file/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content: "" })
    });
    $("newFile").value = "";
    await loadTree();
    await openFile(path);
  });

  $("mkdirBtn").addEventListener("click", async () => {
    if (!currentProject) { alert("Selecione um projeto"); return; }
    const path = $("newFile").value.trim() || prompt("Nome da pasta:");
    if (!path) return;
    await fetch(`/ide/api/mkdir/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path })
    });
    $("newFile").value = "";
    await loadTree();
  });

  // ──────────────────────────────────────────────────────────────────────
  // Project runner
  // ──────────────────────────────────────────────────────────────────────
  let runPoll = null;

  $("runBtn").addEventListener("click", async () => {
    if (!currentProject) { alert("Selecione um projeto"); return; }
    $("run-status").textContent = "▶ Iniciando…";
    const r = await fetch(`/ide/api/run/${encodeURIComponent(currentProject)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const j = await r.json();
    if (!j.ok) { alert(j.error || "Falha ao iniciar"); $("run-status").textContent = ""; return; }
    $("runBtn").style.display = "none";
    $("stopBtn").style.display = "";
    openTerminal(currentProject, "▶ run");
    pollRunStatus(true);
  });

  $("stopBtn").addEventListener("click", async () => {
    if (!currentProject) return;
    await fetch(`/ide/api/run/${encodeURIComponent(currentProject)}/stop`, { method: "POST" });
    $("stopBtn").style.display = "none";
    $("runBtn").style.display = "";
    $("run-status").textContent = "";
    $("run-url").innerHTML = "";
    if (runPoll) { clearInterval(runPoll); runPoll = null; }
  });

  function pollRunStatus(start) {
    if (runPoll) clearInterval(runPoll);
    runPoll = setInterval(async () => {
      if (!currentProject) return;
      const r = await fetch(`/ide/api/run/${encodeURIComponent(currentProject)}/status`);
      const j = await r.json();
      if (!j.running) {
        $("run-status").textContent = "⏹ Parado";
        $("stopBtn").style.display = "none";
        $("runBtn").style.display = "";
        clearInterval(runPoll); runPoll = null;
        return;
      }
      $("run-status").textContent = `● Rodando${j.port ? ` (:${j.port})` : ""}`;
      if (j.url) {
        $("run-url").innerHTML =
          `<a href="${j.url}" target="_blank">${j.url}</a>
           <button class="ghost" onclick="window.open('${j.url}')" style="font-size:10px;margin-left:4px">🔗</button>`;
      }
    }, 2000);
  }

  // ──────────────────────────────────────────────────────────────────────
  // String helper (rsplit polyfill)
  // ──────────────────────────────────────────────────────────────────────
  String.prototype.rsplit = function(sep, n) {
    const parts = this.split(sep);
    return n ? [parts.slice(0, -n).join(sep), ...parts.slice(-n)] : parts;
  };

  // ──────────────────────────────────────────────────────────────────────
  // Deep-link boot
  // ──────────────────────────────────────────────────────────────────────
  function waitForEditor(cb, tries = 40) {
    if (editor) return cb();
    if (tries <= 0) return;
    setTimeout(() => waitForEditor(cb, tries - 1), 100);
  }

  async function bootDeepLink() {
    await loadProjects();
    const params = new URLSearchParams(location.search);
    const wantProj = params.get("project");
    const wantFile = params.get("open");
    if (wantProj) {
      await openProject(wantProj);
      if (wantFile) waitForEditor(() => openFile(wantFile));
    }
  }

  bootDeepLink();
})();
