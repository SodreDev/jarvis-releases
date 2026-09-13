/* ════════════════════════════════════════════════════════════════════════
   JARVIS BRIDGE — funções compartilhadas entre todos os temas
   Cada tema (stark, macos, minimal) carrega este arquivo e fornece os
   elementos DOM esperados (#chat-area, #log-area, #msg-input, #send-btn,
   #mic-btn, #mic-state, #mode-badge, #ptt-label, #val-cpu, #val-ram,
   #val-disk, #val-uptime). Funções não aplicáveis a um tema viram no-op
   automático (verificam se o elemento existe antes de mexer).

   Python (main.py) chama estas funções via window.evaluate_js — então
   todas precisam EXISTIR globalmente em todos os temas.
   ════════════════════════════════════════════════════════════════════════ */
'use strict';

/* Sinaliza ao Python que o bridge terminou de parsear. main.py espera
   por window.JARVIS_READY antes de chamar buildNavPills/buildSbPills/etc. */
window.JARVIS_READY = true;

/* ── INBOX WATCHER: handler global de notificações de mensagens recebidas ── */
(function(){
  const PLAT_ICONS = {whatsapp:'💬', instagram:'📷', discord:'🎮', telegram:'✈️', gmail:'📧'};
  const PLAT_COLORS = {
    whatsapp:'#25d366', instagram:'#e1306c', discord:'#5865f2',
    telegram:'#229ed9', gmail:'#ea4335'
  };
  function ensureHost() {
    let host = document.getElementById('jb-msg-toasts');
    if (host) return host;
    host = document.createElement('div');
    host.id = 'jb-msg-toasts';
    host.style.cssText = 'position:fixed;right:18px;bottom:18px;display:flex;flex-direction:column;gap:10px;z-index:999999;max-width:340px;pointer-events:none;font-family:inherit;';
    document.body.appendChild(host);
    return host;
  }
  function esc(s){return String(s||'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  window.jarvisOnIncoming = function(ev){
    try {
      ev = ev || {};
      const host = ensureHost();
      const icon = PLAT_ICONS[ev.platform] || '✉️';
      const accent = PLAT_COLORS[ev.platform] || '#5ad8ff';
      const profLbl = ev.profile === 'jarvis' ? 'Jarvis' : 'Você';
      const cnt = (ev.unread_count && ev.unread_count > 1) ? ` ×${ev.unread_count}` : '';
      const t = document.createElement('div');
      t.style.cssText = `pointer-events:auto;background:rgba(20,22,30,0.94);border:1px solid ${accent}55;border-left:3px solid ${accent};border-radius:10px;padding:10px 12px;box-shadow:0 8px 24px rgba(0,0,0,0.45);color:#ecedf2;font-size:12.5px;line-height:1.4;backdrop-filter:blur(8px);animation:jb-toast-in .25s ease-out;cursor:pointer;`;
      t.innerHTML = `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
        <span style="font-size:14px">${icon}</span>
        <strong style="color:${accent};font-size:11.5px;text-transform:uppercase;letter-spacing:0.6px">${esc(ev.platform||'msg')}</strong>
        <span style="font-size:10px;color:#8e96a8">· ${esc(profLbl)}${cnt}</span>
        <span style="margin-left:auto;font-size:14px;color:#8e96a8;line-height:1">×</span>
      </div>
      <div style="font-weight:600;color:#fff;margin-bottom:2px">${esc(ev.sender||'?')}</div>
      <div style="color:#cfd2dc;font-size:11.5px;max-height:48px;overflow:hidden">${esc(ev.preview||'(sem preview)')}</div>`;
      t.onclick = () => { try { t.remove(); } catch(_){} };
      host.appendChild(t);
      // auto-close em 9s
      setTimeout(() => { try { t.style.opacity='0'; t.style.transform='translateX(20px)'; t.style.transition='all .35s ease-in'; setTimeout(()=>t.remove(), 360);}catch(_){} }, 9000);
      // som curtinho (beep via WebAudio) — opcional, falha silenciosa
      try {
        const ac = window.__jbAudio || (window.__jbAudio = new (window.AudioContext||window.webkitAudioContext)());
        const o = ac.createOscillator(); const g = ac.createGain();
        o.frequency.value = 880; g.gain.value = 0.04;
        o.connect(g); g.connect(ac.destination);
        o.start(); o.stop(ac.currentTime + 0.08);
      } catch(_){}
    } catch (e) { console.warn('[incoming] handler erro:', e); }
  };
  // drena queue se Python já mandou eventos antes do bridge subir
  if (Array.isArray(window.__jarvisIncomingQueue)) {
    const q = window.__jarvisIncomingQueue.splice(0);
    q.forEach(e => { try { window.jarvisOnIncoming(e); } catch(_){} });
  }
  // animação CSS
  if (!document.getElementById('jb-toast-style')) {
    const st = document.createElement('style');
    st.id = 'jb-toast-style';
    st.textContent = '@keyframes jb-toast-in{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:translateX(0)}}';
    document.head.appendChild(st);
  }
})();

/* ── PYWEBVIEW BRIDGE ──────────────────────────────────────────────────── */
let _pyReady = false;
const _pyQueue = [];
window.addEventListener('pywebviewready', () => {
  _pyReady = true;
  console.log('[bridge] pywebview ready, flushing', _pyQueue.length, 'queued calls');
  while (_pyQueue.length) {
    const job = _pyQueue.shift();
    try { pyApi.apply(null, job); } catch (e) { console.warn('[bridge] queued call failed:', e); }
  }
});
function _hasApi() {
  return !!(window.pywebview && window.pywebview.api);
}
function pyApi(method) {
  const args = Array.prototype.slice.call(arguments, 1);
  if (!_hasApi()) {
    // Enfileira pra disparar quando pywebview estiver pronto
    _pyQueue.push([method].concat(args));
    return;
  }
  const fn = window.pywebview.api[method];
  if (typeof fn !== 'function') {
    console.warn('[bridge] método inexistente no JarvisApi:', method);
    return;
  }
  try { return fn.apply(null, args); }
  catch (e) { console.warn('[bridge] erro ao chamar', method, e); }
}
function pyApiAsync(method) {
  const args = Array.prototype.slice.call(arguments, 1);
  if (!_hasApi()) {
    // Aguarda evento e tenta de novo
    return new Promise((resolve) => {
      const trampoline = () => {
        const fn = window.pywebview && window.pywebview.api && window.pywebview.api[method];
        if (typeof fn !== 'function') { console.warn('[bridge] async método inexistente:', method); resolve(null); return; }
        try { Promise.resolve(fn.apply(null, args)).then(resolve, (e)=>{ console.warn(e); resolve(null); }); }
        catch (e) { console.warn(e); resolve(null); }
      };
      if (_pyReady) trampoline();
      else window.addEventListener('pywebviewready', trampoline, { once: true });
    });
  }
  const fn = window.pywebview.api[method];
  if (typeof fn !== 'function') {
    console.warn('[bridge] async método inexistente:', method);
    return Promise.resolve(null);
  }
  try { return Promise.resolve(fn.apply(null, args)); }
  catch (e) { console.warn('[bridge] erro async em', method, e); return Promise.resolve(null); }
}

/* ── HELPERS ────────────────────────────────────────────────────────────── */
function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ── ICONES SVG (substituem emojis Windows) ─────────────────────────────── */
const _SVG = (path, vb) => `<svg class="jb-ic" width="14" height="14" viewBox="${vb||'0 0 24 24'}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
const _IC = {
  key:     _SVG('<circle cx="8" cy="15" r="4"/><path d="M10.85 12.15 19 4"/><path d="M18 5l2 2"/><path d="M15 8l2 2"/>'),
  mic:     _SVG('<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="17" x2="12" y2="22"/>'),
  brain:   _SVG('<path d="M9 3a3 3 0 0 0-3 3v0a3 3 0 0 0-3 3v3a3 3 0 0 0 3 3v0a3 3 0 0 0 3 3h0a3 3 0 0 0 3-3V6a3 3 0 0 0-3-3z"/><path d="M15 3a3 3 0 0 1 3 3v0a3 3 0 0 1 3 3v3a3 3 0 0 1-3 3v0a3 3 0 0 1-3 3h0a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3z"/>'),
  palette: _SVG('<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2a10 10 0 1 0 0 20 2 2 0 0 0 2-2v-1a2 2 0 0 1 2-2h2.5a3.5 3.5 0 0 0 3.5-3.5A10 10 0 0 0 12 2z"/>'),
  bell:    _SVG('<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>'),
  chat:    _SVG('<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>'),
  bolt:    _SVG('<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'),
  cog:     _SVG('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
  trash:   _SVG('<polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>'),
  refresh: _SVG('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>'),
  check:   _SVG('<polyline points="20 6 9 17 4 12"/>'),
  x:       _SVG('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
  spinner: _SVG('<path d="M21 12a9 9 0 1 1-6.22-8.56"/>'),
  link:    _SVG('<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>'),
  sliders: _SVG('<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'),
};

function _qs(id) { return document.getElementById(id); }
function _scrollBottom(id) { const el = _qs(id); if (el) el.scrollTop = el.scrollHeight; }
function _fmtTime(d) {
  d = d || new Date();
  return String(d.getHours()).padStart(2,'0') + ':' +
         String(d.getMinutes()).padStart(2,'0');
}

/* ── ENVIO DE MENSAGEM ──────────────────────────────────────────────────── */
function sendMessage() {
  const inp = _qs('msg-input');
  if (!inp) return;
  const txt = (inp.value || '').trim();
  if (!txt) return;
  inp.value = '';
  pyApi('send_message', txt);
}
function _wireInput() {
  const inp = _qs('msg-input');
  if (inp && !inp.dataset.wired) {
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });
    inp.dataset.wired = '1';
  }
  const btn = _qs('send-btn');
  if (btn && !btn.dataset.wired) {
    btn.addEventListener('click', sendMessage);
    btn.dataset.wired = '1';
  }
  // Hot-reload de UI: F5 ou Ctrl+R re-lê HTML/CSS/JS do disco e recarrega
  // a webview sem matar o processo Python. Funciona em dev e no .exe.
  if (!window.__jarvisReloadWired) {
    window.__jarvisReloadWired = true;
    window.addEventListener('keydown', e => {
      const isF5 = e.key === 'F5';
      const isCtrlR = (e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R');
      if (isF5 || isCtrlR) {
        e.preventDefault();
        try { pyApi('reload_ui'); } catch (_) {}
      }
    }, true);
  }
}

/* ── CHAT (addMessage / appendContinue) ─────────────────────────────────── */
let _lastJarvisBody = null;
function addMessage(sender, text, tag) {
  const area = _qs('chat-area');
  if (!area) return;
  const ts = _fmtTime();
  const div = document.createElement('div');
  div.className = 'jb-msg jb-' + (tag || 'system');
  if (tag === 'user') {
    div.innerHTML = '<div class="jb-bubble jb-bub-u"><span class="jb-name">Você</span>'
                  + '<span class="jb-ts">' + ts + '</span>'
                  + '<div class="jb-body">' + escHtml(text) + '</div></div>';
    _lastJarvisBody = null;
  } else if (tag === 'jarvis') {
    div.innerHTML = '<div class="jb-bubble jb-bub-j"><span class="jb-name">JARVIS</span>'
                  + '<span class="jb-ts">' + ts + '</span>'
                  + '<div class="jb-body"></div></div>';
    _lastJarvisBody = div.querySelector('.jb-body');
    _lastJarvisBody.textContent = text;
  } else {
    div.innerHTML = '<div class="jb-sys">' + escHtml(text) + '</div>';
    _lastJarvisBody = null;
  }
  area.appendChild(div);
  _scrollBottom('chat-area');
}
function appendContinue(text) {
  if (_lastJarvisBody) {
    _lastJarvisBody.textContent = (_lastJarvisBody.textContent || '') + text;
    _scrollBottom('chat-area');
  } else {
    addMessage('JARVIS', text, 'jarvis');
  }
}

/* ── Preload do histórico no chat ───────────────────────────────────────────
   O #chat-area abre vazio a cada boot/reload de UI; aqui pré-carregamos as
   últimas trocas persistidas (data/memoria_jarvis.jsonl via list_history) pra
   dar continuidade visual. Não sobrescreve mensagens vivas já chegadas. */
function _preloadChat() {
  const area = _qs('chat-area');
  if (!area || area.dataset.preloaded) return;
  area.dataset.preloaded = '1';
  try {
    pyApiAsync('list_history', 14).then(r => {
      if (!r || !r.ok) return;
      const items = r.items || [];
      if (!items.length || area.children.length) return;
      items.forEach(it => {
        const role = String(it.role || '').toLowerCase();
        const txt = it.text || it.content || '';
        if (!txt) return;
        const isU = role === 'user' || role === 'senhor' || role === 'você' || role === 'voce';
        addMessage(isU ? 'Você' : 'JARVIS', txt, isU ? 'user' : 'jarvis');
      });
      _scrollBottom('chat-area');
    }).catch(() => {});
  } catch (_) {}
}
window._preloadChat = _preloadChat;

/* ── LOG ─────────────────────────────────────────────────────────────────── */
function addLogEntry(text) {
  const area = _qs('log-area');
  if (!area) return;
  const div = document.createElement('div');
  div.className = 'jb-log-row';
  div.innerHTML = '<span class="jb-log-t">' + _fmtTime() + '</span>'
                + '<span class="jb-log-m">' + escHtml(text) + '</span>';
  area.appendChild(div);
  // Mantém log enxuto
  while (area.children.length > 100) area.removeChild(area.firstChild);
  _scrollBottom('log-area');
}

/* ── STATUS / MIC / MODO ─────────────────────────────────────────────────── */
function _setText(id, text, color) {
  const el = _qs(id);
  if (!el) return;
  el.textContent = text;
  if (color) el.style.color = color;
}
function setStatus(text, color)     { _setText('status-text', text, color); }
function setMicState(text, color)   { _setText('mic-state',   text, color); }
function setModeBadge(text, color)  { _setText('mode-badge',  text, color); }
function setPttLabel(text, color)   { _setText('ptt-label',   text, color); }
function setTimerText(text, color)  { _setText('timer-text',  text, color); }
function setRecording(on) {
  const el = _qs('mic-btn');
  if (el) el.classList.toggle('jb-recording', !!on);
}

/* ── SYSTEM STATS ────────────────────────────────────────────────────────── */
function updateStats(cpu, ram, disk, upStr) {
  // Texto numérico (tema Stark já usa isto; macos/minimal podem ler via MutationObserver)
  _setText('val-cpu',    (typeof cpu  === 'number' ? cpu.toFixed(1)+'%'  : '--.-%'));
  _setText('val-ram',    (typeof ram  === 'number' ? ram.toFixed(1)+'%'  : '--.-%'));
  _setText('val-disk',   (typeof disk === 'number' ? disk.toFixed(1)+'%' : '--.-%'));
  _setText('val-uptime', upStr || '--:--:--');
  // Barras (Stark)
  const setBar = (id, pct) => { const b = _qs(id); if (b) b.style.width = Math.max(0, Math.min(100, pct||0)) + '%'; };
  setBar('bar-cpu',  cpu);
  setBar('bar-ram',  ram);
  setBar('bar-disk', disk);
  // Rings (macos)
  const setRing = (id, pct) => {
    const r = _qs(id);
    if (!r) return;
    const p = Math.max(0, Math.min(100, pct||0));
    r.style.background = 'conic-gradient(from -90deg,' + (r.dataset.color || '#5ad8ff')
                       + ' ' + p + '%, rgba(255,255,255,0.06) 0)';
    const v = r.querySelector('span'); if (v) v.textContent = Math.round(p) + '%';
  };
  setRing('mac-cpu-ring',  cpu);
  setRing('mac-ram-ring',  ram);
  setRing('mac-disk-ring', disk);
}

/* ── SAFE NO-OPS pra coisas exclusivas do Stark ──────────────────────────── */
if (typeof window.buildNavPills    !== 'function') window.buildNavPills    = function(){};
if (typeof window.buildSbPills     !== 'function') window.buildSbPills     = function(){};
if (typeof window.buildTabCmds     !== 'function') window.buildTabCmds     = function(){};
if (typeof window.buildTabApis     !== 'function') window.buildTabApis     = function(){};
if (typeof window.buildTabConfig   !== 'function') window.buildTabConfig   = function(){};
if (typeof window.buildTabAlarmes  !== 'function') window.buildTabAlarmes  = function(){};

/* ── REALTIME OVERLAY (opcional — só desenha se houver div #rt-overlay) ──── */
function openRealtimeOverlay() {
  const ex = _qs('rt-overlay'); if (ex) return;
  const ov = document.createElement('div');
  ov.id = 'rt-overlay';
  ov.style.cssText = 'position:fixed;top:40px;left:50%;transform:translateX(-50%);'
                  + 'width:680px;max-height:200px;background:rgba(8,12,20,0.92);'
                  + 'border:1px solid rgba(255,80,100,0.5);border-radius:12px;'
                  + 'z-index:9998;padding:12px 16px;color:#fff;font-size:13px;'
                  + 'backdrop-filter:blur(20px);overflow:auto';
  ov.innerHTML = '<div style="font-size:10px;color:#ff6b9e;letter-spacing:2px;'
              + 'margin-bottom:6px">● TRANSCRIÇÃO EM TEMPO REAL</div>'
              + '<div id="rt-body" style="line-height:1.5"></div>';
  document.body.appendChild(ov);
}
function closeRealtimeOverlay() { const ov = _qs('rt-overlay'); if (ov) ov.remove(); }
function clearRealtimeOverlay() { const b = _qs('rt-body'); if (b) b.textContent = ''; }
function appendRealtimeOverlay(t) { const b = _qs('rt-body'); if (b) b.textContent = (b.textContent || '') + t; }
function setRealtimePartial(t) {
  const b = _qs('rt-body');
  if (!b) return;
  // Substitui linha "ativa" (depois do último \n)
  const txt = b.textContent || '';
  const lf = txt.lastIndexOf('\n');
  b.textContent = (lf >= 0 ? txt.slice(0, lf+1) : '') + t;
}

/* ── NOTIF BADGE (opcional) ──────────────────────────────────────────────── */
if (typeof window.notifBadge !== 'function') {
  window.notifBadge = function(){ /* tema específico decide se desenha */ };
}

/* ── CONFIRM BANNER (compartilhado) ──────────────────────────────────────── */
function showConfirmBanner(show, msg) {
  let banner = _qs('jb-confirm-banner');
  if (!banner && show) {
    banner = document.createElement('div');
    banner.id = 'jb-confirm-banner';
    banner.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);'
                        + 'background:rgba(20,8,12,0.95);border:1px solid #ff5070;'
                        + 'border-radius:12px;padding:10px 18px;z-index:9999;'
                        + 'display:flex;align-items:center;gap:14px;color:#fff;font-size:13px;'
                        + 'backdrop-filter:blur(20px);box-shadow:0 12px 40px rgba(0,0,0,0.5)';
    banner.innerHTML = '<span id="jb-confirm-msg" style="color:#ffafc0"></span>'
                    + '<button onclick="confirmAction()" style="background:#3cff7c;color:#021;border:none;padding:6px 14px;border-radius:6px;font-weight:700;cursor:pointer">Confirmar</button>'
                    + '<button onclick="cancelAction()"  style="background:transparent;color:#ff8090;border:1px solid #ff5070;padding:6px 14px;border-radius:6px;cursor:pointer">Cancelar</button>';
    document.body.appendChild(banner);
  }
  if (!banner) return;
  if (show) {
    const lbl = _qs('jb-confirm-msg');
    if (lbl) lbl.textContent = msg ? ('⚠ Confirmar: ' + msg + '?') : '⚠ Confirmar ação?';
    banner.style.display = 'flex';
  } else {
    banner.style.display = 'none';
  }
}
function confirmAction() { showConfirmBanner(false); pyApi('confirm_action'); }
function cancelAction()  { showConfirmBanner(false); pyApi('cancel_action');  }

/* ── SETUP BANNER (primeira execução / chaves faltando) ──────────────────── */
function checkSetupStatus() {
  pyApiAsync('get_setup_status').then(st => {
    const banner = _qs('setup-banner');
    if (banner) banner.style.display = (st && st.precisa) ? 'flex' : 'none';
    // Abre guia de setup automaticamente no primeiro acesso (sem chaves configuradas)
    if (st && st.precisa && !sessionStorage.getItem('jb_guide_shown')) {
      sessionStorage.setItem('jb_guide_shown', '1');
      setTimeout(openSetupGuide, 1500);
    }
  }).catch(()=>{});
}
function openSetupTab() {
  pyApi('abrir_configuracoes');
  setTimeout(() => {
    const el = _qs('cfg-setup-container');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 400);
}

/* ── TROCA DE TEMA (recarrega janela) ────────────────────────────────────── */
function switchTheme(name) {
  if (!['stark','macos','minimal'].includes(name)) return;
  pyApiAsync('set_ui_pref', {theme: name}).then(resp => {
    // Backend recarrega a janela automaticamente — não fazemos reload aqui
    // pra evitar race com pywebview.load_url.
  });
}

/* ════════════════════════════════════════════════════════════════════════
   SETTINGS DRAWER — painel de configurações compartilhado entre temas
   Cria um overlay com abas: Setup, Modelos, Áudio, Aparência, Alarmes,
   Histórico. Funciona em macOS/Minimal (Stark usa o próprio modal).
   ════════════════════════════════════════════════════════════════════════ */
const _DRAWER_CSS = `
#jb-drawer { position: fixed; inset: 0; z-index: 950; display: none;
  background: rgba(0,0,0,0.55); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  align-items: stretch; justify-content: flex-end; }
#jb-drawer.open { display: flex; animation: jbFade .2s ease-out; }
@keyframes jbFade { from { opacity: 0; } to { opacity: 1; } }
#jb-drawer-panel { width: min(680px, 96vw); height: 100%;
  background: linear-gradient(180deg, #0a0f1a 0%, #060911 100%);
  border-left: 1px solid rgba(255,255,255,0.1);
  display: flex; flex-direction: column;
  box-shadow: -30px 0 80px rgba(0,0,0,0.7);
  animation: jbSlide .3s cubic-bezier(.4,0,.2,1); }
@keyframes jbSlide { from { transform: translateX(40px); opacity: 0; }
                     to   { transform: none; opacity: 1; } }
#jb-drawer-head { display: flex; align-items: center; padding: 18px 22px;
  border-bottom: 1px solid rgba(255,255,255,0.08); gap: 14px; }
#jb-drawer-title { font-size: 15px; font-weight: 600; color: #ecedf2; flex: 1;
  font-family: -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif; }
.jb-drawer-x { width: 34px; height: 34px; border-radius: 10px;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08);
  color: #8e96a8; cursor: pointer; font-size: 16px;
  display: flex; align-items: center; justify-content: center; transition: all .2s; }
.jb-drawer-x:hover { color: #ff6b9e; border-color: rgba(255,107,158,0.4); }
#jb-drawer-tabs { display: flex; gap: 6px; padding: 14px 18px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  overflow-x: auto; scrollbar-width: thin; scrollbar-color: rgba(90,216,255,0.35) transparent; }
#jb-drawer-tabs::-webkit-scrollbar { height: 6px; }
#jb-drawer-tabs::-webkit-scrollbar-thumb { background: rgba(90,216,255,0.30); border-radius: 3px; }
#jb-drawer-tabs::-webkit-scrollbar-track { background: transparent; }
.jb-tab { flex-shrink: 0; padding: 9px 14px; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  color: #b6bdcc; cursor: pointer; font-size: 12px; font-weight: 600;
  letter-spacing: .3px; border-radius: 10px;
  transition: all .2s cubic-bezier(.4,0,.2,1); white-space: nowrap;
  font-family: -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
  display: inline-flex; align-items: center; gap: 6px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.2); }
.jb-tab:hover { background: rgba(90,216,255,0.08);
  border-color: rgba(90,216,255,0.25); color: #ecedf2;
  transform: translateY(-1px); }
.jb-tab.active { background: linear-gradient(135deg, rgba(90,216,255,0.20), rgba(167,139,250,0.16));
  border-color: rgba(90,216,255,0.50); color: #5ad8ff;
  box-shadow: 0 4px 14px rgba(90,216,255,0.18); transform: translateY(-1px); }
.jb-tab.active::before { content: ''; width: 5px; height: 5px; border-radius: 50%;
  background: #5ad8ff; box-shadow: 0 0 8px #5ad8ff; }
.jb-ic { display: inline-block; vertical-align: -2px; flex-shrink: 0; }
.jb-tab .jb-ic { opacity: .85; }
.jb-tab.active .jb-ic { opacity: 1; }
.jb-drawer-x .jb-ic { width: 16px; height: 16px; }
.jb-saved .jb-ic, .jb-btn .jb-ic { vertical-align: -3px; margin-right: 4px; }
@keyframes jbSpin { to { transform: rotate(360deg); } }
.jb-spin { animation: jbSpin 1s linear infinite; display: inline-block; }
#jb-drawer-body { flex: 1; overflow-y: auto; padding: 22px;
  font-family: -apple-system, "SF Pro Display", "Inter", system-ui, sans-serif;
  color: #ecedf2; font-size: 13px; }
#jb-drawer-body::-webkit-scrollbar { width: 8px; }
#jb-drawer-body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 4px; }
.jb-section-title { font-size: 11px; font-weight: 700; letter-spacing: 2px;
  color: #5ad8ff; text-transform: uppercase; margin: 4px 0 12px; }
.jb-row { margin-bottom: 14px; }
.jb-row label { display: block; font-size: 11px; color: #8e96a8;
  margin-bottom: 5px; letter-spacing: .5px; }
.jb-input, .jb-select { width: 100%; padding: 10px 12px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px; color: #ecedf2; font-size: 13px; outline: none;
  font-family: inherit; transition: border-color .2s; }
.jb-input:focus, .jb-select:focus { border-color: #5ad8ff;
  box-shadow: 0 0 0 3px rgba(90,216,255,0.1); }
.jb-input.mono { font-family: "JetBrains Mono","SF Mono","Cascadia Code", monospace;
  font-size: 12px; }
.jb-btn { padding: 9px 16px; border-radius: 10px; border: none; cursor: pointer;
  font-size: 12px; font-weight: 600; font-family: inherit; transition: all .2s; }
.jb-btn-pri { background: linear-gradient(135deg, #5ad8ff, #a78bfa); color: #021; }
.jb-btn-pri:hover { transform: translateY(-1px);
  box-shadow: 0 6px 22px rgba(90,216,255,0.35); }
.jb-btn-sec { background: rgba(255,255,255,0.05); color: #ecedf2;
  border: 1px solid rgba(255,255,255,0.1); }
.jb-btn-sec:hover { border-color: #5ad8ff; color: #5ad8ff; }
.jb-btn-danger { background: rgba(255,107,158,0.12); color: #ff6b9e;
  border: 1px solid rgba(255,107,158,0.3); }
.jb-btn-danger:hover { background: rgba(255,107,158,0.2); }
.jb-key-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 12px; padding: 14px; margin-bottom: 10px; }
.jb-key-card.req { border-color: rgba(255,176,84,0.35); }
.jb-key-card .kc-head { display: flex; align-items: center;
  justify-content: space-between; margin-bottom: 4px; }
.jb-key-card .kc-name { font-size: 13px; font-weight: 600; color: #ecedf2; }
.jb-key-card .kc-name .badge { font-size: 9px; padding: 2px 6px; border-radius: 4px;
  margin-left: 6px; letter-spacing: .5px; }
.jb-badge-req { background: rgba(255,176,84,0.18); color: #ffb054; }
.jb-badge-rec { background: rgba(90,216,255,0.15); color: #5ad8ff; }
.jb-badge-opt { background: rgba(167,139,250,0.15); color: #a78bfa; }
.jb-key-card .kc-desc { font-size: 11px; color: #8e96a8; margin-bottom: 8px; line-height: 1.45; }
.jb-key-card .kc-link { font-size: 11px; color: #5ad8ff; cursor: pointer;
  text-decoration: none; }
.jb-key-card .kc-link:hover { text-decoration: underline; }
.jb-key-card .kc-row { display: flex; gap: 6px; margin-top: 8px; align-items: center; }
.jb-key-card .kc-row .jb-input { flex: 1; }
.jb-theme-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.jb-theme-opt { padding: 14px; border-radius: 12px; cursor: pointer;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
  transition: all .2s; }
.jb-theme-opt:hover { border-color: #5ad8ff; transform: translateY(-1px); }
.jb-theme-opt.active { border-color: #5ad8ff;
  box-shadow: 0 0 0 2px rgba(90,216,255,0.25); }
.jb-theme-opt h4 { font-size: 13px; margin-bottom: 3px; color: #ecedf2; }
.jb-theme-opt small { font-size: 10.5px; color: #8e96a8; }
.jb-alarme-row, .jb-hist-row { display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; margin-bottom: 6px; }
.jb-alarme-row .ar-time { font-family: "JetBrains Mono", monospace;
  color: #5ad8ff; font-size: 14px; font-weight: 700; min-width: 70px; }
.jb-alarme-row .ar-desc { flex: 1; color: #ecedf2; font-size: 12px; }
.jb-hist-row .hr-when { color: #8e96a8; font-size: 10.5px;
  font-family: "JetBrains Mono", monospace; min-width: 90px; }
.jb-hist-row .hr-role { color: #5ad8ff; font-size: 10.5px; min-width: 60px; font-weight: 600; }
.jb-hist-row.user .hr-role { color: #a78bfa; }
.jb-hist-row .hr-text { flex: 1; color: #ecedf2; font-size: 12.5px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jb-empty { text-align: center; color: #8e96a8; padding: 30px 0; font-size: 12px; }
.jb-saved { color: #3cff7c; font-size: 11px; margin-left: 8px; opacity: 0; transition: opacity .3s; }
.jb-saved.show { opacity: 1; }
/* ── Tab "Tudo": grid de configs com auto-save ── */
.jb-cfg-group { margin-bottom: 22px;
  background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 16px; padding: 14px 16px; }
.jb-cfg-group-title { font-size: 12px; font-weight: 700; color: #5ad8ff;
  letter-spacing: 1px; text-transform: uppercase; margin-bottom: 10px;
  padding-bottom: 8px; border-bottom: 1px solid rgba(90,216,255,0.15); }
.jb-cfg-field { margin-bottom: 10px; }
.jb-cfg-label { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.jb-cfg-key { font-size: 11.5px; font-weight: 600; color: #ecedf2; flex: 1;
  font-family: "JetBrains Mono","SF Mono","Cascadia Code", monospace; }
.jb-cfg-status { font-size: 10.5px; font-weight: 600; min-width: 60px; text-align: right; }
.jb-cfg-reset { width: 22px; height: 22px; border-radius: 6px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  color: #8e96a8; cursor: pointer; font-size: 12px;
  display: inline-flex; align-items: center; justify-content: center; padding: 0;
  transition: all .15s; }
.jb-cfg-reset:hover { color: #5ad8ff; border-color: rgba(90,216,255,0.4); }
.jb-cfg-control input.jb-input, .jb-cfg-control select.jb-select { padding: 7px 10px; font-size: 12px; }
.jb-cfg-switch { display: inline-flex; align-items: center; gap: 8px; cursor: pointer;
  color: #ecedf2; font-size: 12px; }
.jb-cfg-switch input[type="checkbox"] { width: 16px; height: 16px; accent-color: #5ad8ff; cursor: pointer; }
.jb-cfg-desc { color: #8e96a8; font-size: 11px; line-height: 1.45;
  margin: 2px 0 6px 0; padding-left: 2px; }
.jb-cfg-new { background: linear-gradient(90deg, rgba(255,176,84,0.06), transparent 60%);
  border-left: 2px solid #ffb054; padding-left: 8px; border-radius: 4px; }
.jb-newfeat-banner { display:flex; align-items:center; gap:12px;
  background: linear-gradient(135deg, rgba(255,176,84,0.12), rgba(255,107,158,0.08));
  border: 1px solid rgba(255,176,84,0.35); border-radius: 12px;
  padding: 12px 14px; margin-bottom: 16px; color: #ecedf2; font-size: 12px; line-height: 1.5; }
.jb-newfeat-banner button { background:#ffb054; color:#1a0a0a; border:none; border-radius:8px;
  padding:6px 12px; font-weight:700; font-size:11px; cursor:pointer; white-space:nowrap; }
.jb-newfeat-banner button:hover { background:#ffc070; }
`;

function _ensureDrawer() {
  if (_qs('jb-drawer-style')) return;
  const st = document.createElement('style');
  st.id = 'jb-drawer-style'; st.textContent = _DRAWER_CSS;
  document.head.appendChild(st);
  const wrap = document.createElement('div');
  wrap.id = 'jb-drawer';
  wrap.innerHTML = `
    <div id="jb-drawer-panel" onclick="event.stopPropagation()">
      <div id="jb-drawer-head">
        <div id="jb-drawer-title">Configurações</div>
        <button class="jb-drawer-x" onclick="closeSettings()" aria-label="Fechar">${_IC.x}</button>
      </div>
      <div id="jb-drawer-tabs">
        <button class="jb-tab active" data-tab="setup"   onclick="_switchTab('setup')">${_IC.key}Setup</button>
        <button class="jb-tab"        data-tab="audio"   onclick="_switchTab('audio')">${_IC.mic}Áudio</button>
        <button class="jb-tab"        data-tab="models"  onclick="_switchTab('models')">${_IC.brain}Modelos</button>
        <button class="jb-tab"        data-tab="cerebro" onclick="_switchTab('cerebro')">🧠 Cérebro</button>
        <button class="jb-tab"        data-tab="msg"     onclick="_switchTab('msg')">💬 Mensageria</button>
        <button class="jb-tab"        data-tab="people"  onclick="_switchTab('people')">👥 Pessoas</button>
        <button class="jb-tab"        data-tab="theme"   onclick="_switchTab('theme')">${_IC.palette}Aparência</button>
        <button class="jb-tab"        data-tab="alarmes" onclick="_switchTab('alarmes')">${_IC.bell}Alarmes</button>
        <button class="jb-tab"        data-tab="history" onclick="_switchTab('history')">${_IC.chat}Histórico</button>
        <button class="jb-tab"        data-tab="all"     onclick="_switchTab('all')">${_IC.bolt}Tudo</button>
      </div>
      <div id="jb-drawer-body"></div>
    </div>`;
  wrap.addEventListener('click', e => { if (e.target.id === 'jb-drawer') closeSettings(); });
  document.body.appendChild(wrap);
}
function openSettings(tab) {
  _ensureDrawer();
  _qs('jb-drawer').classList.add('open');
  _switchTab(tab || 'setup');
}
function closeSettings() {
  const d = _qs('jb-drawer'); if (d) d.classList.remove('open');
}
function _switchTab(name) {
  // Se a config full-screen do macOS está montada (rail, fora do modal),
  // roteia a navegação interna dos renderers pra ela em vez do drawer oculto.
  if (document.getElementById('mac-cfg-body')) { _macCfgGo(name); return; }
  document.querySelectorAll('#jb-drawer-tabs .jb-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === name));
  const body = _qs('jb-drawer-body');
  if (!body) return;
  body.innerHTML = '<div class="jb-empty">Carregando…</div>';
  ({setup:_renderSetup, audio:_renderAudio, models:_renderModels,
    cerebro:_renderCerebro,
    theme:_renderTheme, alarmes:_renderAlarmes, history:_renderHistory,
    msg:_renderMessaging,
    people:_renderPeople,
    all:_renderAllConfigs}
    [name] || _renderSetup)(body);
}

/* ── Tab: Setup (chaves de API) ──────────────────────────────────────────── */
function _renderSetup(body) {
  body.innerHTML = `
    <div class="jb-newfeat-banner">
      <div style="font-size:22px">✨</div>
      <div style="flex:1">
        <strong style="color:#ffb054">Novas configurações (Sprint 2)</strong> — Mensageria via Chromium humanizado
        (WhatsApp/Insta/Discord/Telegram/Gmail), janela off-screen e bridge LLM modular.
        Vá em <strong>Tudo</strong> e procure pelas marcadas com <span style="background:linear-gradient(90deg,#ffb054,#ff6b9e);color:#1a0a0a;font-size:9px;font-weight:800;padding:1px 5px;border-radius:3px">NOVO</span>.
      </div>
      <button onclick="_switchTab('all')">Ir para Tudo</button>
    </div>
    <div class="jb-section-title">Credenciais de API</div>
    <div id="jb-keys-list"></div>`;
  pyApiAsync('get_env_keys').then(resp => {
    const list = _qs('jb-keys-list'); if (!list) return;
    const keys = Array.isArray(resp) ? resp : (resp && resp.keys) || [];
    if (!keys.length) { list.innerHTML = '<div class="jb-empty">Nenhuma chave disponível.</div>'; return; }
    list.innerHTML = keys.map(k => {
      const tier = k.tier || k.tipo || 'opcional';
      const cls = tier === 'obrigatorio' ? 'req' : '';
      const badge = tier === 'obrigatorio' ? '<span class="badge jb-badge-req">OBRIGATÓRIA</span>'
                  : tier === 'recomendado' ? '<span class="badge jb-badge-rec">RECOMENDADA</span>'
                  : '<span class="badge jb-badge-opt">OPCIONAL</span>';
      const masked = k.masked || k.value_mask || '';
      const url = k.help_url || k.url || '';
      return `<div class="jb-key-card ${cls}" data-key="${escHtml(k.key)}">
        <div class="kc-head"><div class="kc-name">${escHtml(k.label || k.key)}${badge}</div></div>
        <div class="kc-desc">${escHtml(k.desc || '')}</div>
        ${url ? `<a class="kc-link" onclick="pyApi('open_url','${escHtml(url)}')">Obter chave</a>` : ''}
        <div class="kc-row">
          <input type="password" class="jb-input mono" placeholder="${masked ? 'Atual: '+escHtml(masked) : 'Cole sua chave aqui'}" data-input="${escHtml(k.key)}">
          <button class="jb-btn jb-btn-pri" onclick="_saveOneKey('${escHtml(k.key)}', this)">Salvar</button>
          <span class="jb-saved" data-saved="${escHtml(k.key)}">${_IC.check}Salvo</span>
        </div>
      </div>`;
    }).join('');
  });
}
function _saveOneKey(key, btn) {
  const inp = document.querySelector(`#jb-keys-list input[data-input="${key}"]`);
  if (!inp) return;
  const val = (inp.value || '').trim();
  if (!val) return;
  btn.disabled = true; btn.textContent = '…';
  const payload = {}; payload[key] = val;
  pyApiAsync('save_env_keys', payload).then(resp => {
    btn.disabled = false; btn.textContent = 'Salvar';
    if (resp && resp.ok) {
      inp.value = '';
      const saved = document.querySelector(`[data-saved="${key}"]`);
      if (saved) { saved.classList.add('show'); setTimeout(()=>saved.classList.remove('show'), 2000); }
      _switchTab('setup'); // refresh para mostrar nova máscara
      checkSetupStatus();
    } else {
      alert('Erro: ' + ((resp && resp.error) || 'desconhecido'));
    }
  });
}

/* ── Tab: Áudio (mic + modo) ─────────────────────────────────────────────── */
function _renderAudio(body) {
  body.innerHTML = '<div class="jb-section-title">Microfone e modo de ativação</div>'
                 + '<div class="jb-row"><label>Microfone</label><select class="jb-select" id="jb-mic-sel"><option>Carregando…</option></select></div>'
                 + '<div class="jb-row"><label>Modo de ativação</label><select class="jb-select" id="jb-mode-sel">'
                 + '<option value="ptt">Push-to-Talk (Shift+G)</option>'
                 + '<option value="wake">Wake-word (diga "Jarvis")</option>'
                 + '<option value="auto">Auto / Ambient</option>'
                 + '</select></div>'
                 + '<div style="margin-top:18px"><button class="jb-btn jb-btn-pri" onclick="_saveAudio(this)">Salvar configurações de áudio</button>'
                 + '<span class="jb-saved" id="jb-audio-saved">'+_IC.check+'Salvo</span></div>';
  // Carrega lista de mics + valores atuais
  Promise.all([pyApiAsync('list_mics'), pyApiAsync('get_models_pref')]).then(([mr, pref]) => {
    const ms = _qs('jb-mic-sel');
    if (ms) {
      const mics = (mr && mr.mics) || [];
      const cur = (mr && typeof mr.current === 'number') ? mr.current : -1;
      ms.innerHTML = '<option value="-1">Padrão do sistema</option>'
                   + mics.map(m => `<option value="${m.idx}" ${m.idx===cur?'selected':''}>${escHtml(m.name)}</option>`).join('');
    }
    const sel = _qs('jb-mode-sel');
    if (sel && pref && pref.activation_mode) sel.value = pref.activation_mode;
  });
}
function _saveAudio(btn) {
  const mic = _qs('jb-mic-sel'); const mode = _qs('jb-mode-sel');
  const micIdx = mic ? parseInt(mic.value, 10) : -1;
  const modeVal = mode ? mode.value : 'ptt';
  btn.disabled = true; btn.textContent = '…';
  pyApiAsync('apply_config', isNaN(micIdx)?-1:micIdx, modeVal).then(_=>{
    btn.disabled = false; btn.textContent = 'Salvar configurações de áudio';
    const s = _qs('jb-audio-saved'); if (s) { s.classList.add('show'); setTimeout(()=>s.classList.remove('show'),2000); }
  });
}

/* ── Tab: Modelos (LLM) ──────────────────────────────────────────────────── */
function _renderModels(body) {
  body.innerHTML = '<div class="jb-section-title">Modelos de IA</div>'
                 + '<div class="jb-row"><label>Provider LLM</label>'
                 + '<select class="jb-select" id="jb-prov-sel">'
                 + '<option value="groq">Groq (nuvem — recomendado)</option>'
                 + '<option value="lmstudio">LM Studio (local — sem internet)</option>'
                 + '<option value="openrouter">OpenRouter (nuvem — modelos grátis/baratos)</option>'
                 + '</select></div>'
                 + '<div class="jb-row"><label>Modelo Groq (chat)</label><select class="jb-select" id="jb-groq-sel"><option>Carregando…</option></select></div>'
                 + '<div id="jb-or-box" style="display:none">'
                 +   '<p style="margin:2px 0 6px;font-size:11px;color:#8e96a8">Padrão: <code>openrouter/auto</code> — sua conta escolhe o melhor modelo por request (com fallback automático se algum falhar).</p>'
                 +   '<div class="jb-row"><label><input type="checkbox" id="jb-or-specify" style="margin-right:8px">Especificar modelos manualmente</label></div>'
                 +   '<div id="jb-or-specbox" style="display:none">'
                 +     '<div class="jb-row"><label>OpenRouter — pensar</label><input class="jb-input" id="jb-or-thinking" placeholder="ex: deepseek/deepseek-v4-flash"></div>'
                 +     '<div class="jb-row"><label>OpenRouter — arquivos</label><input class="jb-input" id="jb-or-files" placeholder="ex: qwen/qwen3-next-80b-a3b-instruct:free"></div>'
                 +     '<p style="margin:2px 0 8px;font-size:11px;color:#8e96a8">Se o modelo específico falhar, cai automaticamente no <code>openrouter/auto</code> → Groq.</p>'
                 +   '</div>'
                 +   '<div class="jb-row"><label>Gerador de imagem</label>'
                 +   '<select class="jb-select" id="jb-img-provider">'
                 +   '<option value="auto">Auto (OpenRouter → Pollinations)</option>'
                 +   '<option value="openrouter">OpenRouter (modelo pago)</option>'
                 +   '<option value="pollinations">Pollinations (grátis)</option>'
                 +   '</select></div>'
                 +   '<div class="jb-row"><label>OpenRouter — modelo de imagem</label><input class="jb-input" id="jb-or-imgrender" placeholder="bytedance-seed/seedream-4.5 (≈US$0,04) ou x-ai/grok-imagine-image-quality:free"></div>'
                 +   '<p id="jb-or-keyhint" style="margin:2px 0 4px;font-size:11.5px"></p>'
                 +   '<p style="margin:0 0 8px;font-size:11px;color:#8e96a8">Pollinations grátis: pegue um token Seed (auth.pollinations.ai) e defina <code>POLLINATIONS_TOKEN</code> no .env para evitar 429.</p>'
                 + '</div>'
                 + '<div class="jb-section-title" style="margin-top:14px">Cérebro (tool-calling)</div>'
                 + '<div class="jb-row"><label><input type="checkbox" id="jb-agent-total" style="margin-right:8px">Cérebro total — máxima acertividade (LLM sempre raciocina sobre o contexto; todas as tools + histórico)</label></div>'
                 + '<div class="jb-row"><label>Seleção de ferramentas</label>'
                 + '<select class="jb-select" id="jb-agent-mode">'
                 + '<option value="keyword">Por palavra-chave (atual)</option>'
                 + '<option value="layered">Por camadas (recomendado)</option>'
                 + '<option value="all">Todas (máximo acerto, + tokens)</option>'
                 + '</select></div>'
                 + '<div class="jb-row"><label><input type="checkbox" id="jb-agent-hist" style="margin-right:8px">Usar histórico recente (entende "manda pra ele")</label></div>'
                 + '<div class="jb-row"><label><input type="checkbox" id="jb-agent-par" style="margin-right:8px">Chamar várias ferramentas por vez (paralelo)</label></div>'
                 + '<div class="jb-row"><label><input type="checkbox" id="jb-agent-strict" style="margin-right:8px">Schema estrito (argumentos sempre válidos)</label></div>'
                 + '<div class="jb-row"><label><input type="checkbox" id="jb-agent-deck" style="margin-right:8px">Apresentações novas (spec→render, mais bonitas)</label></div>'
                 + '<div class="jb-section-title" style="margin-top:14px">Geral</div>'
                 + '<div class="jb-row"><label>Cidade (clima)</label><input class="jb-input" id="jb-city" placeholder="ex: São Paulo"></div>'
                 + '<div class="jb-row"><label><input type="checkbox" id="jb-notif-speak" style="margin-right:8px">Falar notificações automaticamente</label></div>'
                 + '<button class="jb-btn jb-btn-pri" onclick="_saveModels(this)">Salvar</button>'
                 + '<span class="jb-saved" id="jb-models-saved">'+_IC.check+'Salvo</span>'
  Promise.all([pyApiAsync('list_groq_models'), pyApiAsync('get_models_pref')]).then(([gm, pref]) => {
    window._curModels = (pref && pref.models) || {};
    window._curAgent  = (pref && pref.agent)  || {};
    const ps = _qs('jb-prov-sel');
    if (ps) {
      ps.value = (window._curModels.llm_provider || pref?.provider_active || 'groq');
      ps.onchange = _toggleOrBox;
    }
    const sel = _qs('jb-groq-sel');
    if (sel) {
      const list = (gm && gm.ok && gm.models) || [];
      const cur = window._curModels.chat_groq || window._curModels.groq || '';
      sel.innerHTML = list.length
        ? list.map(m => `<option value="${escHtml(m.id||m)}" ${(m.id||m)===cur?'selected':''}>${escHtml(m.id||m)}</option>`).join('')
        : `<option value="${escHtml(cur)}">${escHtml(cur || 'sem chave Groq')}</option>`;
    }
    const ord = (pref && pref.openrouter_defaults) || {};
    const setv = (id, v) => { const e = _qs(id); if (e) e.value = v || ''; };
    setv('jb-or-thinking',  window._curModels.openrouter_thinking || '');
    setv('jb-or-files',     window._curModels.openrouter_files    || '');
    setv('jb-or-imgrender', window._curModels.openrouter_image_render || ord.image_render || '');
    const ipv = _qs('jb-img-provider'); if (ipv) ipv.value = window._curModels.image_provider || 'auto';
    const spc = _qs('jb-or-specify'); if (spc) { spc.checked = !!window._curModels.openrouter_specify; spc.onchange = _toggleSpecBox; }
    _toggleSpecBox();
    const kh = _qs('jb-or-keyhint');
    if (kh) {
      const ok = pref && pref.openrouter_key_set;
      kh.textContent = ok ? '✓ Chave OpenRouter configurada.' : '⚠ Defina a OpenRouter API Key na aba Setup para usar este provider.';
      kh.style.color = ok ? '#5ad88f' : '#ffb454';
    }
    const atot = _qs('jb-agent-total'); if (atot) atot.checked = (window._curAgent.brain_mode === 'total');
    const am = _qs('jb-agent-mode'); if (am) am.value = window._curAgent.tool_select_mode || 'keyword';
    const ah = _qs('jb-agent-hist'); if (ah) ah.checked = !!window._curAgent.include_history;
    const ap = _qs('jb-agent-par');  if (ap) ap.checked = !!window._curAgent.parallel_tools;
    const ast = _qs('jb-agent-strict'); if (ast) ast.checked = !!window._curAgent.strict_tools;
    const adk = _qs('jb-agent-deck'); if (adk) adk.checked = !!window._curAgent.deck_v2;
    const c = _qs('jb-city');         if (c && pref) c.value = pref.user_city || '';
    const n = _qs('jb-notif-speak');  if (n && pref) n.checked = !!pref.notif_auto_speak;
    _toggleOrBox();
  });
}
function _toggleOrBox() {
  const ps = _qs('jb-prov-sel'); const box = _qs('jb-or-box');
  if (box) box.style.display = (ps && ps.value === 'openrouter') ? 'block' : 'none';
}
function _toggleSpecBox() {
  const cb = _qs('jb-or-specify'); const box = _qs('jb-or-specbox');
  if (box) box.style.display = (cb && cb.checked) ? 'block' : 'none';
}
function _saveModels(btn) {
  const groq = _qs('jb-groq-sel')?.value || '';
  const prov = _qs('jb-prov-sel')?.value || 'groq';
  const city = _qs('jb-city')?.value || '';
  const speak = _qs('jb-notif-speak')?.checked || false;
  const orT = (_qs('jb-or-thinking')?.value || '').trim();
  const orF = (_qs('jb-or-files')?.value || '').trim();
  const orImg = (_qs('jb-or-imgrender')?.value || '').trim();
  const imgProv = _qs('jb-img-provider')?.value || 'auto';
  const orSpec = _qs('jb-or-specify')?.checked || false;
  // Preserva os outros campos do dict de modelos pra não apagar chat_lm/vision/etc
  const merged = Object.assign({}, window._curModels || {}, {chat_groq: groq, llm_provider: prov, image_provider: imgProv, openrouter_specify: orSpec});
  if (orT) merged.openrouter_thinking = orT;
  if (orF) merged.openrouter_files = orF;
  if (orImg) merged.openrouter_image_render = orImg;
  const agent = {
    brain_mode:       _qs('jb-agent-total')?.checked ? 'total' : 'fast',
    tool_select_mode: _qs('jb-agent-mode')?.value || 'keyword',
    include_history:  _qs('jb-agent-hist')?.checked || false,
    parallel_tools:   _qs('jb-agent-par')?.checked || false,
    strict_tools:     _qs('jb-agent-strict')?.checked || false,
    deck_v2:          _qs('jb-agent-deck')?.checked || false,
  };
  btn.disabled = true; btn.textContent = '…';
  pyApiAsync('apply_models', merged, city, speak, agent).then(_=>{
    btn.disabled = false; btn.textContent = 'Salvar';
    const s = _qs('jb-models-saved'); if (s) { s.classList.add('show'); setTimeout(()=>s.classList.remove('show'),2000); }
  });
}

/* ── Tab: Aparência (tema) ───────────────────────────────────────────────── */
function _renderTheme(body) {
  const cur = (document.body.dataset.theme || 'stark');
  const opts = [
    {id:'stark',   name:'Stark Classic', desc:'HUD original, dashboard completo'},
    {id:'macos',   name:'macOS Glass',   desc:'Cards glassmorphic + chat lateral'},
    {id:'minimal', name:'Minimal Pro',   desc:'Foco no chat, orb animado'},
  ];
  body.innerHTML = '<div class="jb-section-title">Escolha o tema</div>'
                 + '<p style="color:#8e96a8;font-size:12px;margin-bottom:14px">A janela recarrega ao trocar.</p>'
                 + '<div class="jb-theme-grid">'
                 + opts.map(o => `<div class="jb-theme-opt ${o.id===cur?'active':''}" onclick="switchTheme('${o.id}')">
                     <h4>${o.name}</h4><small>${o.desc}</small></div>`).join('')
                 + '</div>';
}

/* ── Tab: Alarmes ────────────────────────────────────────────────────────── */
function _renderAlarmes(body) {
  body.innerHTML = '<div class="jb-section-title">Alarmes ativos</div><div id="jb-alarmes-list"><div class="jb-empty">Carregando…</div></div>';
  pyApiAsync('list_alarmes').then(resp => {
    const list = _qs('jb-alarmes-list'); if (!list) return;
    const arr = (resp && resp.alarmes) || [];
    if (!arr.length) { list.innerHTML = '<div class="jb-empty">Nenhum alarme cadastrado.<br><small style="opacity:.7">Diga "Jarvis, me acorde às 7h" pra criar um.</small></div>'; return; }
    list.innerHTML = arr.map(a => {
      const t = a.hora || a.time || '--:--';
      const d = a.descricao || a.label || a.titulo || 'Alarme';
      const id = a.id || a.uuid || '';
      return `<div class="jb-alarme-row">
        <div class="ar-time">${escHtml(t)}</div>
        <div class="ar-desc">${escHtml(d)}</div>
        <button class="jb-btn jb-btn-danger" onclick="_delAlarme('${escHtml(id)}')" title="Remover">${_IC.trash}</button>
      </div>`;
    }).join('');
  });
}
function _delAlarme(id) {
  if (!confirm('Remover este alarme?')) return;
  pyApiAsync('delete_alarme', id).then(_=>_switchTab('alarmes'));
}

/* ── Tab: Histórico ──────────────────────────────────────────────────────── */
function _renderHistory(body) {
  body.innerHTML = '<div class="jb-section-title">Últimas 50 interações</div><div id="jb-hist-list"><div class="jb-empty">Carregando…</div></div>';
  pyApiAsync('list_history', 50).then(resp => {
    const list = _qs('jb-hist-list'); if (!list) return;
    const arr = (resp && resp.items) || [];
    if (!arr.length) { list.innerHTML = '<div class="jb-empty">Nada ainda. Converse com o JARVIS!</div>'; return; }
    list.innerHTML = arr.slice().reverse().map(it => {
      const role = (it.role || it.sender || 'sys').toLowerCase();
      const txt = it.text || it.content || it.msg || '';
      // ts pode vir como ISO string (memoria_jarvis) ou epoch (legado)
      let ts = '';
      if (it.ts) {
        try {
          const d = typeof it.ts === 'number' ? new Date(it.ts*1000) : new Date(it.ts);
          if (!isNaN(d.getTime())) ts = d.toLocaleString('pt-BR', {hour12:false});
        } catch(e) {}
      }
      const rclass = role === 'user' || role === 'senhor' ? 'user' : '';
      const rlabel = role === 'user' || role === 'senhor' ? 'VOCÊ' : 'JARVIS';
      return `<div class="jb-hist-row ${rclass}">
        <div class="hr-when">${escHtml(ts)}</div>
        <div class="hr-role">${rlabel}</div>
        <div class="hr-text" title="${escHtml(txt)}">${escHtml(txt)}</div>
      </div>`;
    }).join('');
  });
}

/* ── Tab: Tudo (configurações dinâmicas via schema) ──────────────────────── */
// Rótulos amigáveis por categoria, derivada do prefixo da KEY
const _CFG_GROUPS = [
  { id: 'TTS',       title: '🔊 Voz / TTS',           prefixes: ['TTS_', 'VOZ_', 'ELEVENLABS_', 'GEMINI_TTS_'] },
  { id: 'LLM',       title: '🧠 Modelos LLM',          prefixes: ['LLM_', 'GROQ_', 'LMSTUDIO_', 'MAX_'] },
  { id: 'BASIC',     title: '📍 Localização & básico', prefixes: ['CIDADE_', 'DITADO_'] },
  { id: 'AWAY',      title: '🌙 Modo Ausente',          prefixes: ['AWAY_', 'INSTAGRAM_', 'DISCORD_'] },
  { id: 'AMBIENT',   title: 'Audio Ambiente',            prefixes: ['AMBIENT_', 'SYSTEM_AUDIO_'] },
  { id: 'PRESENCE',  title: '📷 Câmera & Presença',     prefixes: ['CAMERA_', 'PRESENCE_'] },
  { id: 'SECURITY',  title: '🔒 Segurança (avançado)',  prefixes: ['SECURITY_', 'INJECTION_', 'EMBEDDING_'] },
  { id: 'OTHER',     title: 'Outros',                    prefixes: ['BROWSER_', 'WHATSAPP_'] },
];

function _grupoDaKey(k) {
  for (const g of _CFG_GROUPS) {
    if (g.prefixes.some(p => k.startsWith(p))) return g.id;
  }
  return 'OTHER';
}

let _cfgSchemaCache = null;
let _cfgSettingsCache = {};
const _cfgDebounceTimers = {};

function _humanizeKey(k) {
  return k.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

function _renderControl(key, def, val) {
  const t = def.type;
  const safeVal = (val === null || val === undefined) ? '' : val;
  if (t === 'bool') {
    const checked = val === true ? 'checked' : '';
    return `<label class="jb-cfg-switch">
      <input type="checkbox" data-cfg-key="${key}" data-cfg-type="bool" ${checked}>
      <span>${val === true ? 'Ativado' : 'Desativado'}</span>
    </label>`;
  }
  if (Array.isArray(def.choices) && def.choices.length) {
    const opts = def.choices.map(c =>
      `<option value="${escHtml(c)}" ${c === val ? 'selected' : ''}>${escHtml(c)}</option>`).join('');
    return `<select class="jb-select" data-cfg-key="${key}" data-cfg-type="${t}">${opts}</select>`;
  }
  if (t === 'int' || t === 'float') {
    const step = t === 'float' ? '0.01' : '1';
    const min = (def.min !== undefined) ? `min="${def.min}"` : '';
    const max = (def.max !== undefined) ? `max="${def.max}"` : '';
    return `<input type="number" step="${step}" ${min} ${max} class="jb-input" data-cfg-key="${key}" data-cfg-type="${t}" value="${escHtml(String(safeVal))}">`;
  }
  if (t === 'list_str') {
    const txt = Array.isArray(val) ? val.join(', ') : String(safeVal);
    return `<input type="text" class="jb-input" data-cfg-key="${key}" data-cfg-type="list_str" value="${escHtml(txt)}" placeholder="item1, item2, item3">`;
  }
  // default: str
  return `<input type="text" class="jb-input" data-cfg-key="${key}" data-cfg-type="str" value="${escHtml(String(safeVal))}">`;
}

/* ── Tab: Cérebro (orquestrador + modelo alternativo + memória) ──────────── */
function _renderCerebro(body) {
  body.innerHTML = `
    <div class="jb-section-title">Orquestrador & modelo alternativo</div>
    <p style="margin:2px 0 10px;font-size:11.5px;color:#8e96a8;line-height:1.5">
      Roteamento das ferramentas por <b>significado</b> e uso de um <b>modelo local alternativo (Nila)</b>
      como roteador, quando presente. OFF por padrão — cai no MiniLM/API se faltar.</p>
    <div class="jb-row"><label>Modo do cérebro <span id="jb-brain-mode-status" style="font-size:11px;color:#5ad88f"></span></label>
      <select class="jb-select" id="jb-brain-mode">
        <option value="layered">Por camadas — recomendado (filtra ~8 tools por significado, menos tokens)</option>
        <option value="keyword">Por palavra-chave (filtro simples)</option>
        <option value="all">Todas as tools (sem filtro, + tokens)</option>
        <option value="total">Total (todas as tools + histórico, máx. acerto e tokens)</option>
      </select></div>
    <div style="font-size:10.5px;color:#8e96a8;margin:-4px 0 12px 0">Salva na hora, sem botão. "Por camadas" usa o filtro semântico calibrado; "Total" manda tudo (custo alto).</div>
    <div id="jb-cer-cfg"></div>
    <div class="jb-section-title" style="margin-top:18px">Memória (cérebro)
      <span style="font-weight:400;color:#8e96a8;font-size:11px">· visão enxuta — o completo está no Painel Global</span></div>
    <div style="display:flex;gap:10px;min-height:200px">
      <div id="jb-cer-layers" style="width:48%;max-height:330px;overflow-y:auto"></div>
      <div id="jb-cer-content" style="flex:1;max-height:330px;overflow-y:auto;border-left:1px solid rgba(255,255,255,0.08);padding-left:12px;font-size:12px;line-height:1.6;color:#cfd6e4">
        <div style="opacity:.5;padding-top:30px;text-align:center">Clique numa camada para ver o conteúdo.</div>
      </div>
    </div>`;
  // ── toggles (set_setting, salvam na hora) ──
  const cfg = _qs('jb-cer-cfg');
  const TGL = [
    ['SKILL_MEMORY_ENABLED', 'bool', 'Roteamento semântico de instruções', 'Recupera só as ~8 ferramentas relevantes por significado em vez de mandar todas — reduz tokens e mata o erro 413.'],
    ['MODELO_LOCAL_ENABLED', 'bool', 'Modelo local alternativo (Nila) como roteador', 'Usa o modelo da pasta abaixo se presente; senão cai no MiniLM/API.'],
    ['MODELO_LOCAL_DIR', 'str', 'Pasta do modelo local (Nila)', 'Caminho da pasta com o binário + .safetensors. VAZIO = autodetect (env JARVIS_MODELO_DIR / pasta padrão). Ex.: B:\\GranaFacil\\testes\\nila_mind_para_amigos_10m'],
    ['MODELO_LOCAL_THREADS', 'int', 'Threads de CPU do modelo local', '6–8 recomendado (CPU intensa só no treino).'],
  ];
  cfg.innerHTML = TGL.map(([k, t, lbl, help]) => {
    const status = `<span id="jb-cfg-status-${k}" style="font-size:11px"></span>`;
    const hint = `<div style="font-size:10.5px;color:#8e96a8;margin:-4px 0 8px ${t === 'bool' ? '24px' : '0'}">${escHtml(help)}</div>`;
    if (t === 'bool')
      return `<div class="jb-row"><label><input type="checkbox" data-cfg-key="${k}" data-cfg-type="bool" style="margin-right:8px">${escHtml(lbl)}</label>${status}</div>${hint}`;
    if (t === 'int')
      return `<div class="jb-row"><label>${escHtml(lbl)}</label><input class="jb-input mono" style="max-width:90px" type="number" min="1" max="16" data-cfg-key="${k}" data-cfg-type="int">${status}</div>${hint}`;
    // str (ex.: pasta do modelo) — campo de texto largo
    return `<div style="margin:4px 0 2px"><label style="font-size:12.5px">${escHtml(lbl)}</label> ${status}</div><input class="jb-input mono" style="width:100%;margin-bottom:2px" type="text" placeholder="vazio = autodetect" data-cfg-key="${k}" data-cfg-type="str">${hint}`;
  }).join('');
  pyApiAsync('get_settings').then(rv => {
    const s = (rv && rv.ok) ? (rv.settings || {}) : (rv || {});
    cfg.querySelectorAll('[data-cfg-key]').forEach(el => {
      const k = el.dataset.cfgKey;
      if (k in s) { if (el.type === 'checkbox') el.checked = !!s[k]; else el.value = s[k]; }
      el.addEventListener(el.type === 'checkbox' ? 'change' : 'input', () => _onCfgFieldChange(el));
    });
  });
  // ── Modo do cérebro (escreve na seção 'agent' — canônica, lida no boot) ──
  const _bm = _qs('jb-brain-mode');
  if (_bm) {
    pyApiAsync('get_brain_mode').then(r => { if (r && r.mode) _bm.value = r.mode; });
    _bm.addEventListener('change', () => {
      const _st = _qs('jb-brain-mode-status');
      if (_st) _st.textContent = '…';
      pyApiAsync('set_brain_mode', _bm.value).then(r => {
        if (_st) { _st.textContent = (r && r.ok) ? '✓ salvo' : '✗ ' + ((r && r.msg) || 'erro'); setTimeout(() => { _st.textContent = ''; }, 2000); }
      });
    });
  }
  // ── visualização da memória (cérebro + conteúdo) ──
  const layersEl = _qs('jb-cer-layers');
  const contentEl = _qs('jb-cer-content');
  const showItems = (lay) => {
    const items = [];
    (lay.subs || []).forEach(sub => (sub.items || []).forEach(it => items.push(Object.assign({ _sub: sub.name }, it))));
    (lay.items || []).forEach(it => items.push(it));
    let html = `<div style="color:${lay.color};font-weight:600;margin-bottom:3px">${escHtml(lay.icon)} ${escHtml(lay.name)} · ${items.length}</div>`
      + `<div style="font-size:11px;color:#8e96a8;margin-bottom:10px">${escHtml(lay.purpose)}</div>`;
    html += items.length
      ? items.map(it => `<div style="border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:7px 9px;margin-bottom:6px">${it._sub ? `<div style="font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#8e96a8;margin-bottom:2px">${escHtml(it._sub)}</div>` : ''}<div style="white-space:pre-wrap;word-break:break-word;font-size:11.5px">${escHtml(it.text)}</div></div>`).join('')
      : '<div style="opacity:.5">(camada vazia ainda)</div>';
    contentEl.innerHTML = html;
  };
  pyApiAsync('get_brain').then(d => {
    const lays = (d && d.layers) || [];
    if (!lays.length) { layersEl.innerHTML = '<div style="opacity:.5;font-size:12px">Sem memórias ainda.</div>'; return; }
    layersEl.innerHTML = '';
    lays.forEach(lay => {
      const card = document.createElement('div');
      card.style.cssText = `border:1px solid rgba(255,255,255,0.08);border-left:3px solid ${lay.color};border-radius:7px;padding:8px 10px;margin-bottom:6px;cursor:pointer`;
      card.onmouseenter = () => card.style.background = 'rgba(90,216,255,0.05)';
      card.onmouseleave = () => card.style.background = 'transparent';
      card.innerHTML = `<div style="display:flex;align-items:center;gap:6px"><span>${escHtml(lay.icon)}</span><span style="font-weight:600;font-size:12px">${escHtml(lay.name)}</span><span style="margin-left:auto;font-size:10px;color:#8e96a8">${lay.count}</span></div><div style="font-size:10px;color:#8e96a8;margin-top:3px;line-height:1.3">${escHtml(lay.desc)}</div>`;
      card.onclick = () => showItems(lay);
      layersEl.appendChild(card);
    });
  }).catch(err => { if (layersEl) layersEl.innerHTML = '<div style="opacity:.5">erro: ' + escHtml(String(err)) + '</div>'; });
}

function _renderAllConfigs(body) {
  body.innerHTML = `
    <div class="jb-section-title">Todas as configurações (mudam em tempo real)</div>
    <div style="color:#8e96a8; font-size:11.5px; margin-bottom:14px; line-height:1.55;">
      Edições são salvas automaticamente em ~0.5s e aplicam imediatamente em todos os temas.
      Use <strong style="color:#ecedf2">Restaurar</strong> ao lado de um campo para voltar ao padrão de fábrica.
    </div>
    <div id="jb-cfg-all-body"><div class="jb-empty">Carregando schema…</div></div>`;

  // Carrega schema + valores em paralelo
  Promise.all([
    pyApiAsync('get_config_schema'),
    pyApiAsync('get_settings'),
  ]).then(([rs, rv]) => {
    const host = _qs('jb-cfg-all-body'); if (!host) return;
    if (!rs || !rs.ok) { host.innerHTML = '<div class="jb-empty">Falha ao carregar schema.</div>'; return; }
    _cfgSchemaCache = rs.schema || {};
    _cfgSettingsCache = (rv && rv.ok) ? (rv.settings || {}) : {};

    // Agrupa por categoria
    const groups = {};
    for (const g of _CFG_GROUPS) groups[g.id] = [];
    Object.keys(_cfgSchemaCache).sort().forEach(k => {
      groups[_grupoDaKey(k)].push(k);
    });

    let html = '';
    for (const g of _CFG_GROUPS) {
      const keys = groups[g.id];
      if (!keys.length) continue;
      html += `<div class="jb-cfg-group">
        <div class="jb-cfg-group-title">${g.title}</div>`;
      keys.forEach(k => {
        const def = _cfgSchemaCache[k];
        const val = _cfgSettingsCache[k];
        const isNew = def && def.new === true;
        const desc  = def && def.desc ? def.desc : '';
        const badge = isNew
          ? '<span style="background:linear-gradient(90deg,#ffb054,#ff6b9e);color:#1a0a0a;font-size:9px;font-weight:800;padding:2px 6px;border-radius:4px;letter-spacing:0.5px;margin-left:6px">NOVO</span>'
          : '';
        html += `<div class="jb-cfg-field ${isNew ? 'jb-cfg-new' : ''}" data-key="${k}">
          <div class="jb-cfg-label">
            <span class="jb-cfg-key" title="${escHtml(k)}">${escHtml(_humanizeKey(k))}${badge}</span>
            <span class="jb-cfg-status" id="jb-cfg-status-${k}"></span>
            <button class="jb-cfg-reset" title="Restaurar padrão" data-reset-key="${k}">↺</button>
          </div>
          ${desc ? `<div class="jb-cfg-desc">${escHtml(desc)}</div>` : ''}
          <div class="jb-cfg-control">${_renderControl(k, def, val)}</div>
        </div>`;
      });
      html += `</div>`;
    }
    host.innerHTML = html;

    // Bind
    host.querySelectorAll('[data-cfg-key]').forEach(el => {
      const ev = el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input';
      el.addEventListener(ev, () => _onCfgFieldChange(el));
    });
    host.querySelectorAll('[data-reset-key]').forEach(btn => {
      btn.addEventListener('click', () => _onCfgReset(btn.dataset.resetKey));
    });
  }).catch(err => {
    const host = _qs('jb-cfg-all-body');
    if (host) host.innerHTML = `<div class="jb-empty">Erro: ${escHtml(String(err))}</div>`;
  });
}

function _onCfgFieldChange(el) {
  const key = el.dataset.cfgKey;
  const type = el.dataset.cfgType;
  let val;
  if (type === 'bool') val = !!el.checked;
  else if (type === 'int') val = el.value === '' ? null : parseInt(el.value, 10);
  else if (type === 'float') val = el.value === '' ? null : parseFloat(el.value);
  else if (type === 'list_str') val = el.value.split(',').map(s => s.trim()).filter(Boolean);
  else val = el.value;

  if (_cfgDebounceTimers[key]) clearTimeout(_cfgDebounceTimers[key]);
  const status = _qs(`jb-cfg-status-${key}`);
  if (status) { status.innerHTML = '<span class="jb-spin">'+_IC.spinner+'</span>'; status.style.color = '#ffb054'; }

  _cfgDebounceTimers[key] = setTimeout(() => {
    pyApiAsync('set_setting', key, val).then(r => {
      if (!status) return;
      if (r && r.ok) {
        status.innerHTML = _IC.check + ' aplicado';
        status.style.color = '#3cff7c';
        _cfgSettingsCache[key] = val;
        setTimeout(() => { if (status) status.textContent = ''; }, 1800);
      } else {
        status.textContent = '⚠ ' + ((r && r.msg) || 'erro');
        status.style.color = '#ff6b9e';
      }
    }).catch(e => {
      if (status) { status.textContent = '⚠ ' + String(e); status.style.color = '#ff6b9e'; }
    });
  }, 500);
}

function _onCfgReset(key) {
  pyApiAsync('reset_setting', key).then(r => {
    if (r && r.ok) {
      // Re-renderiza para refletir valor default
      const body = _qs('jb-drawer-body'); if (body) _renderAllConfigs(body);
    }
  });
}

/* ── Tab: Mensageria (logins por plataforma × perfil) ───────────────────── */
const _MSG_PLAT_LABELS = {
  whatsapp:  {icon:'💬', name:'WhatsApp Web'},
  instagram: {icon:'📷', name:'Instagram'},
  discord:   {icon:'🎮', name:'Discord'},
  telegram:  {icon:'✈️', name:'Telegram'},
  gmail:     {icon:'📧', name:'Gmail'},
};
const _MSG_STATUS = {
  connected:    {dot:'🟢', text:'conectado',     color:'#3cff7c'},
  needs_login:  {dot:'🔴', text:'sem login',     color:'#ff6b9e'},
  never_logged: {dot:'⚪', text:'nunca logado',  color:'#8e96a8'},
  logging_in:   {dot:'🟡', text:'conectando…',   color:'#ffb054'},
  login_failed: {dot:'🟠', text:'falhou',        color:'#ff9040'},
  expired:      {dot:'🟠', text:'expirado',      color:'#ff9040'},
  unknown:      {dot:'❔', text:'desconhecido',  color:'#888'},
};
let _msgPollTimer = null;

function _renderMessaging(body) {
  body.innerHTML = `
    <div class="jb-section-title">Mensageria — Logins por plataforma</div>
    <div style="color:#8e96a8;font-size:11.5px;margin-bottom:14px;line-height:1.55;">
      Cada plataforma tem 2 perfis isolados: <strong style="color:#5ad8ff">jarvis</strong>
      (a conta dele) e <strong style="color:#ffb054">user</strong> (a sua). Conectar abre o
      Chromium humanizado para QR/senha. Logout apaga o profile do disco.
    </div>
    <div id="jb-msg-method-row" style="display:flex;align-items:center;gap:10px;margin-bottom:18px;padding:10px 12px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:10px">
      <span style="font-size:12px;color:#ecedf2">Método de envio:</span>
      <select id="jb-msg-method" class="jb-select" style="flex:0 0 180px">
        <option value="browser">Browser (Chromium)</option>
        <option value="pyautogui">PyAutoGUI (desktop)</option>
        <option value="auto">Auto (browser → pyautogui)</option>
      </select>
      <span id="jb-msg-method-status" style="font-size:11px;color:#8e96a8"></span>
    </div>
    <div id="jb-msg-grid"><div class="jb-empty">Carregando…</div></div>`;

  // Carrega método de envio atual
  pyApiAsync('get_setting', 'MESSAGING_SEND_METHOD').then(rv => {
    const sel = _qs('jb-msg-method');
    const cur = (rv && (rv.value || rv.MESSAGING_SEND_METHOD)) || 'browser';
    if (sel) sel.value = cur;
    if (sel) sel.onchange = () => {
      const st = _qs('jb-msg-method-status');
      if (st) { st.textContent = 'salvando…'; st.style.color = '#ffb054'; }
      pyApiAsync('set_setting', 'MESSAGING_SEND_METHOD', sel.value).then(r => {
        if (!st) return;
        st.textContent = (r && r.ok) ? '✓ aplicado' : ('⚠ ' + ((r&&r.msg)||'erro'));
        st.style.color = (r && r.ok) ? '#3cff7c' : '#ff6b9e';
        setTimeout(()=>{ if(st) st.textContent=''; }, 1800);
      });
    };
  });

  _msgRefreshGrid();
}

function _msgRenderCell(plat, prof, st) {
  const badge = _MSG_STATUS[st.status] || _MSG_STATUS.unknown;
  const busy = st.in_progress;
  const isConnected = st.status === 'connected' || st.status === 'expired';
  const profLbl = prof === 'jarvis' ? '🤖 conta do Jarvis' : '👤 sua conta';
  const profColor = prof === 'jarvis' ? '#5ad8ff' : '#ffb054';
  return `<div style="border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:10px;background:rgba(255,255,255,0.03)">
    <div style="font-size:10px;color:${profColor};font-weight:700;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">${profLbl}</div>
    <div style="font-size:12px;margin-bottom:4px;color:${badge.color}">${badge.dot} ${badge.text}</div>
    <div style="font-size:10px;color:#8e96a8;font-style:italic;min-height:13px;margin-bottom:8px">${escHtml(st.message||'')}</div>
    <div style="display:flex;gap:6px">
      <button class="jb-btn jb-btn-pri" style="flex:1;font-size:11px;padding:6px 4px" ${busy?'disabled':''} onclick="_msgStartLogin('${plat}','${prof}')">${isConnected?'Reconectar':'Conectar'}</button>
      <button class="jb-btn jb-btn-danger" style="flex:1;font-size:11px;padding:6px 4px" ${(busy||st.status==='never_logged')?'disabled':''} onclick="_msgLogout('${plat}','${prof}')">Logout</button>
    </div>
  </div>`;
}

function _msgRefreshGrid() {
  pyApiAsync('messaging_login_status').then(rv => {
    const host = _qs('jb-msg-grid'); if (!host) return;
    if (!rv || !rv.ok) { host.innerHTML = '<div class="jb-empty">Erro: '+escHtml(JSON.stringify(rv))+'</div>'; return; }
    const status = rv.status || {};
    let html = '';
    let anyBusy = false;
    Object.keys(_MSG_PLAT_LABELS).forEach(plat => {
      const lbl = _MSG_PLAT_LABELS[plat];
      const profs = status[plat] || {};
      html += `<div style="margin-bottom:14px;border:1px solid rgba(255,255,255,0.06);border-radius:12px;padding:12px;background:rgba(255,255,255,0.02)">
        <div style="font-size:13px;font-weight:600;color:#ecedf2;margin-bottom:10px">${lbl.icon} ${lbl.name}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">`;
      ['jarvis','user'].forEach(prof => {
        const st = profs[prof] || {status:'unknown', in_progress:false, message:''};
        if (st.in_progress) anyBusy = true;
        html += _msgRenderCell(plat, prof, st);
      });
      html += `</div></div>`;
    });
    host.innerHTML = html;
    // Polling adaptativo
    if (anyBusy && !_msgPollTimer) {
      _msgPollTimer = setInterval(_msgRefreshGrid, 2000);
    } else if (!anyBusy && _msgPollTimer) {
      clearInterval(_msgPollTimer); _msgPollTimer = null;
    }
  });
}

function _msgStartLogin(plat, prof) {
  pyApiAsync('messaging_login_start', plat, prof).then(rv => {
    console.log('[MSG] login start', plat, prof, rv);
    _msgRefreshGrid();
  });
}

function _msgLogout(plat, prof) {
  if (!confirm('Apagar a sessão de ' + plat + ' (' + prof + ')? Isso remove o profile do disco.')) return;
  pyApiAsync('messaging_logout', plat, prof, true).then(rv => {
    console.log('[MSG] logout', plat, prof, rv);
    _msgRefreshGrid();
  });
}

// Para o polling quando o drawer fecha
const _origCloseSettings_msg = (typeof closeSettings === 'function') ? closeSettings : null;
window.closeSettings = function() {
  if (_msgPollTimer) { clearInterval(_msgPollTimer); _msgPollTimer = null; }
  if (_origCloseSettings_msg) _origCloseSettings_msg();
  else { const d = _qs('jb-drawer'); if (d) d.classList.remove('open'); }
};

/* ── Tab: Pessoas (Fase 4) ───────────────────────────────────────────── */
const _PEOPLE_PLAT_ICONS = {whatsapp:'💬', instagram:'📷', discord:'🎮', telegram:'✈️', gmail:'📧'};

function _renderPeople(body) {
  body.innerHTML = `
    <div class="jb-section-title">Pessoas — Identidade cross-platform</div>
    <div style="color:#8e96a8;font-size:11.5px;margin-bottom:14px;line-height:1.55;">
      Mapeie cada contato a múltiplas plataformas (ex.: João = WhatsApp 5511…
      + Telegram @joao + Instagram joao_silva). O Jarvis usa isso para juntar
      mensagens e memória da mesma pessoa.
    </div>
    <div style="display:flex;gap:8px;margin-bottom:14px">
      <button class="jb-btn jb-btn-pri" onclick="_peopleNew()">➕ Nova pessoa</button>
      <button class="jb-btn" onclick="_peopleRefresh()">🔄 Recarregar</button>
    </div>
    <div id="jb-people-list"><div class="jb-empty">Carregando…</div></div>`;
  _peopleRefresh();
}

function _peopleRefresh() {
  pyApiAsync('people_list').then(rv => {
    const host = _qs('jb-people-list'); if (!host) return;
    if (!rv || !rv.ok) { host.innerHTML = '<div class="jb-empty">Erro: '+escHtml(JSON.stringify(rv))+'</div>'; return; }
    const people = rv.people || [];
    if (!people.length) {
      host.innerHTML = '<div class="jb-empty">Nenhuma pessoa cadastrada. Clique em "Nova pessoa" para começar.</div>';
      return;
    }
    let html = '';
    people.forEach(p => {
      const idents = (p.identities || []).map(i => {
        const ic = _PEOPLE_PLAT_ICONS[i.platform] || '📱';
        const lb = i.label ? ` <em style="color:#8e96a8">(${escHtml(i.label)})</em>` : '';
        const pr = i.profile ? ` <span style="font-size:9px;color:#5ad8ff">[${escHtml(i.profile)}]</span>` : '';
        return `<span style="display:inline-block;background:rgba(255,255,255,0.05);padding:3px 7px;border-radius:6px;margin:2px 4px 2px 0;font-size:11px">${ic} ${escHtml(i.handle)}${pr}${lb} <a href="#" onclick="event.preventDefault();_peopleRemoveIdent('${p.id}','${escHtml(i.platform)}','${escHtml(i.handle).replace(/'/g,"\\'")}')" style="color:#ff6b9e;text-decoration:none;margin-left:4px" title="remover">×</a></span>`;
      }).join('');
      const tags = (p.tags||[]).map(t => `<span style="background:rgba(90,216,255,0.12);color:#5ad8ff;padding:1px 6px;border-radius:4px;font-size:10px;margin-right:3px">${escHtml(t)}</span>`).join('');
      html += `<div style="border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:12px;margin-bottom:10px;background:rgba(255,255,255,0.02)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <strong style="color:#ecedf2;font-size:13px">${escHtml(p.name)}</strong>
          <span style="font-size:10px;color:#5d6478">${escHtml(p.id)}</span>
          ${tags}
          <span style="margin-left:auto;display:flex;gap:6px">
            <button class="jb-btn" style="font-size:10px;padding:3px 8px" onclick="_peopleAddIdent('${p.id}')">+ Identidade</button>
            <button class="jb-btn" style="font-size:10px;padding:3px 8px" onclick="_peopleMemory('${p.id}','${escHtml(p.name).replace(/'/g,"\\'")}')">📜 Memória</button>
            <button class="jb-btn" style="font-size:10px;padding:3px 8px" onclick="_peopleEdit('${p.id}')">Editar</button>
            <button class="jb-btn jb-btn-danger" style="font-size:10px;padding:3px 8px" onclick="_peopleDelete('${p.id}')">×</button>
          </span>
        </div>
        ${p.notes ? `<div style="color:#cfd2dc;font-size:11px;font-style:italic;margin-bottom:6px">${escHtml(p.notes)}</div>` : ''}
        <div>${idents || '<em style="color:#8e96a8;font-size:11px">sem identidades — adicione abaixo</em>'}</div>
      </div>`;
    });
    host.innerHTML = html;
  });
}

function _peopleNew() {
  const name = prompt('Nome da pessoa:');
  if (!name) return;
  pyApiAsync('people_upsert', name).then(rv => {
    if (rv && rv.ok) _peopleRefresh();
    else alert('Erro: '+JSON.stringify(rv));
  });
}

function _peopleEdit(id) {
  pyApiAsync('people_list').then(rv => {
    const p = (rv && rv.people || []).find(x => x.id === id);
    if (!p) return;
    const name = prompt('Nome:', p.name);
    if (name == null) return;
    const notes = prompt('Notas (opcional):', p.notes || '');
    const tags = prompt('Tags (separadas por vírgula):', (p.tags||[]).join(','));
    pyApiAsync('people_upsert', name, id,
      (tags||'').split(',').map(s=>s.trim()).filter(Boolean),
      notes||''
    ).then(() => _peopleRefresh());
  });
}

function _peopleDelete(id) {
  if (!confirm('Apagar esta pessoa? As identidades serão perdidas (mas as conversas continuam nas plataformas).')) return;
  pyApiAsync('people_delete', id).then(() => _peopleRefresh());
}

function _peopleAddIdent(id) {
  const platform = prompt('Plataforma (whatsapp / instagram / discord / telegram / gmail):');
  if (!platform) return;
  const handle = prompt('Handle (número WhatsApp / @user Telegram / username IG / email Gmail):');
  if (!handle) return;
  const profile = prompt('Em qual perfil este contato existe? (jarvis / user / vazio):', 'user');
  const label = prompt('Rótulo opcional (ex.: "celular", "trabalho"):', '');
  pyApiAsync('people_add_identity', id, platform.trim().toLowerCase(), handle.trim(),
             (profile||'').trim().toLowerCase() || null, label||null
  ).then(() => _peopleRefresh());
}

function _peopleRemoveIdent(id, platform, handle) {
  if (!confirm('Remover identidade '+platform+':'+handle+'?')) return;
  pyApiAsync('people_remove_identity', id, platform, handle).then(() => _peopleRefresh());
}

/* ═══════════════════════════════════════════════════════════════════════
   Memória pessoal (Fase 5) — modal com facts + threads
   ═══════════════════════════════════════════════════════════════════════ */
function _peopleMemory(id, name) {
  // monta overlay modal
  let host = document.getElementById('jb-memory-modal');
  if (host) host.remove();
  host = document.createElement('div');
  host.id = 'jb-memory-modal';
  host.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:99999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(6px)';
  host.innerHTML = `
    <div style="background:#101319;border:1px solid rgba(255,255,255,0.1);border-radius:14px;width:780px;max-width:92vw;max-height:88vh;display:flex;flex-direction:column;overflow:hidden">
      <div style="display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid rgba(255,255,255,0.08)">
        <strong style="color:#ecedf2;font-size:14px">📜 Memória — ${escHtml(name||id)}</strong>
        <span style="font-size:10px;color:#5d6478">${escHtml(id)}</span>
        <button class="jb-btn" style="margin-left:auto;font-size:11px" onclick="document.getElementById('jb-memory-modal').remove()">Fechar</button>
      </div>
      <div style="display:flex;gap:0;flex:1;min-height:0">
        <div style="width:40%;border-right:1px solid rgba(255,255,255,0.06);padding:14px;overflow-y:auto">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <strong style="color:#ecedf2;font-size:12px">📌 Fatos</strong>
            <button class="jb-btn" style="margin-left:auto;font-size:10px;padding:3px 7px" onclick="_pmAddFact('${id}')">+ Fato</button>
          </div>
          <div id="jb-pm-facts"><em style="color:#8e96a8;font-size:11px">carregando…</em></div>
        </div>
        <div style="flex:1;display:flex;flex-direction:column;min-width:0;padding:14px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <strong style="color:#ecedf2;font-size:12px">💬 Conversas</strong>
            <select id="jb-pm-thread-sel" class="jb-input" style="font-size:11px;padding:3px 8px;margin-left:auto"></select>
          </div>
          <div id="jb-pm-thread" style="flex:1;overflow-y:auto;background:rgba(0,0,0,0.25);border-radius:8px;padding:10px;font-size:12px;color:#cfd2dc"><em style="color:#8e96a8">selecione uma thread…</em></div>
        </div>
      </div>
    </div>`;
  document.body.appendChild(host);
  host.dataset.personId = id;
  _pmLoadFacts(id);
  _pmLoadThreads(id);
}

function _pmLoadFacts(id) {
  pyApiAsync('person_memory_facts', id).then(rv => {
    const host = document.getElementById('jb-pm-facts'); if (!host) return;
    if (!rv || !rv.ok) { host.innerHTML = '<em style="color:#ff6b9e">erro</em>'; return; }
    const facts = rv.facts || [];
    if (!facts.length) { host.innerHTML = '<em style="color:#8e96a8;font-size:11px">nenhum fato registrado</em>'; return; }
    host.innerHTML = facts.map(f => `
      <div style="background:rgba(255,255,255,0.04);border-radius:7px;padding:7px 9px;margin-bottom:6px;font-size:11px;color:#cfd2dc;display:flex;align-items:start;gap:6px">
        <div style="flex:1">${escHtml(f.text||'')}<div style="font-size:9px;color:#5d6478;margin-top:2px">${escHtml(f.source||'')} · ${escHtml((f.ts||'').slice(0,16))}</div></div>
        <a href="#" onclick="event.preventDefault();_pmRemoveFact('${id}','${f.id}')" style="color:#ff6b9e;text-decoration:none" title="remover">×</a>
      </div>`).join('');
  });
}

function _pmAddFact(id) {
  const text = prompt('Novo fato sobre esta pessoa:');
  if (!text) return;
  pyApiAsync('person_memory_add_fact', id, text.trim(), 'manual').then(() => _pmLoadFacts(id));
}

function _pmRemoveFact(id, factId) {
  if (!confirm('Remover este fato?')) return;
  pyApiAsync('person_memory_remove_fact', id, factId).then(() => _pmLoadFacts(id));
}

function _pmLoadThreads(id) {
  pyApiAsync('person_memory_threads', id).then(rv => {
    const sel = document.getElementById('jb-pm-thread-sel'); if (!sel) return;
    const threads = (rv && rv.ok && rv.threads) ? rv.threads : [];
    if (!threads.length) {
      sel.innerHTML = '<option value="">— sem histórico —</option>';
      const tbody = document.getElementById('jb-pm-thread');
      if (tbody) tbody.innerHTML = '<em style="color:#8e96a8">nenhuma conversa registrada</em>';
      return;
    }
    sel.innerHTML = threads.map(t => `<option value="${escHtml(t.platform)}|${escHtml(t.profile)}">${escHtml(t.platform)} / ${escHtml(t.profile)} (${t.count})</option>`).join('');
    sel.onchange = () => {
      const [pl, pr] = (sel.value||'').split('|');
      if (pl && pr) _pmLoadThread(id, pl, pr);
    };
    const [pl, pr] = (sel.value||'').split('|');
    if (pl && pr) _pmLoadThread(id, pl, pr);
  });
}

function _pmLoadThread(id, platform, profile) {
  pyApiAsync('person_memory_thread', id, platform, profile, 100).then(rv => {
    const host = document.getElementById('jb-pm-thread'); if (!host) return;
    if (!rv || !rv.ok) { host.innerHTML = '<em style="color:#ff6b9e">erro</em>'; return; }
    const msgs = rv.messages || [];
    if (!msgs.length) { host.innerHTML = '<em style="color:#8e96a8">vazia</em>'; return; }
    host.innerHTML = msgs.map(m => {
      const r = m.role || '?';
      const bg = r === 'incoming' ? 'rgba(90,216,255,0.08)' : (r === 'outgoing' ? 'rgba(120,255,170,0.08)' : 'rgba(255,255,255,0.04)');
      const who = r === 'incoming' ? '⬅ ' + (m.sender||'?') : (r === 'outgoing' ? '➡ EU' : (m.sender||'sys'));
      return `<div style="background:${bg};border-radius:7px;padding:6px 9px;margin-bottom:5px">
        <div style="font-size:10px;color:#8e96a8;margin-bottom:2px">${escHtml(who)} · ${escHtml((m.ts||'').slice(0,16))}</div>
        <div>${escHtml(m.content||'')}</div></div>`;
    }).join('');
    host.scrollTop = host.scrollHeight;
  });
}

/* ═══════════════════════════════════════════════════════════════════════
   macOS THEME — Navegação in-place (páginas dedicadas por rail-btn)
   ═══════════════════════════════════════════════════════════════════════ */
let _macDashHTML = null;     // backup do dashboard original
let _macCurrentPage = 'dashboard';
const _MAC_CSS = `
.mac-page { animation: macPageIn .35s cubic-bezier(.4,0,.2,1); grid-column: 1 / -1; }
@keyframes macPageIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.mac-page-head { display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 18px; padding: 0 4px; }
.mac-page-title { font-size: 22px; font-weight: 700; letter-spacing: -.02em; color: var(--txt); }
.mac-page-sub { font-size: 12px; color: var(--txt-mute); margin-top: 4px; }
.mac-page .card { padding: 22px; }
.mac-cfg-nav { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 4px 16px; }
.mac-cfg-pill { padding: 8px 16px; background: var(--glass-2); border: 1px solid var(--stroke);
  border-radius: 10px; color: var(--txt-mute); font-size: 12.5px; font-weight: 600;
  font-family: inherit; cursor: pointer; transition: all .18s; white-space: nowrap; }
.mac-cfg-pill:hover { border-color: var(--cyan); color: var(--txt); transform: translateY(-1px); }
.mac-cfg-pill.active { background: linear-gradient(135deg, rgba(90,216,255,0.18), rgba(167,139,250,0.14));
  border-color: var(--cyan); color: var(--txt); box-shadow: 0 0 0 3px rgba(90,216,255,0.08); }
.mac-list { display: flex; flex-direction: column; gap: 10px; }
.mac-row { display: flex; align-items: center; gap: 14px; padding: 14px 16px;
  background: var(--glass-2); border: 1px solid var(--stroke); border-radius: 14px;
  transition: all .2s; }
.mac-row:hover { border-color: var(--stroke-hi); transform: translateY(-1px); }
.mac-row .role-badge { font-size: 9px; letter-spacing: 1.5px; font-weight: 800;
  padding: 4px 8px; border-radius: 6px; flex-shrink: 0; }
.mac-row .role-u { background: rgba(167,139,250,0.18); color: var(--purple);
  border: 1px solid rgba(167,139,250,0.3); }
.mac-row .role-j { background: rgba(90,216,255,0.16); color: var(--cyan);
  border: 1px solid rgba(90,216,255,0.3); }
.mac-row .row-body { flex: 1; font-size: 13px; line-height: 1.55; color: var(--txt);
  white-space: pre-wrap; word-break: break-word; }
.mac-row .row-ts { font-size: 10px; color: var(--txt-mute); flex-shrink: 0;
  font-family: "SF Mono","JetBrains Mono",monospace; }
.mac-empty { padding: 38px 20px; text-align: center; color: var(--txt-mute);
  font-size: 13px; }
.mac-field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 16px; }
.mac-field label { font-size: 11px; letter-spacing: 1.5px; color: var(--txt-mute);
  text-transform: uppercase; font-weight: 600; }
.mac-field input, .mac-field select, .mac-field textarea {
  padding: 11px 14px; background: var(--glass-2); border: 1px solid var(--stroke);
  border-radius: 10px; color: var(--txt); font-size: 13px; font-family: inherit;
  outline: none; transition: border-color .2s, box-shadow .2s; }
.mac-field input:focus, .mac-field select:focus, .mac-field textarea:focus {
  border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(90,216,255,0.12); }
.mac-field .hint { font-size: 11px; color: var(--txt-mute); }
.mac-btn { padding: 10px 18px; background: linear-gradient(135deg, var(--cyan), var(--purple));
  color: #021; border: none; border-radius: 10px; font-weight: 700; font-size: 12px;
  letter-spacing: .5px; cursor: pointer; transition: all .2s;
  display: inline-flex; align-items: center; gap: 8px; }
.mac-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(90,216,255,0.3); }
.mac-btn.ghost { background: var(--glass-2); color: var(--txt); border: 1px solid var(--stroke); }
.mac-btn.ghost:hover { border-color: var(--cyan); color: var(--cyan); }
.mac-key-card { padding: 16px; background: var(--glass-2); border: 1px solid var(--stroke);
  border-radius: 14px; margin-bottom: 10px; }
.mac-key-card.req { border-color: rgba(255,107,158,0.35); }
.mac-key-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.mac-key-name { font-size: 14px; font-weight: 700; color: var(--txt); }
.mac-key-badge { font-size: 9px; padding: 2px 8px; border-radius: 6px;
  letter-spacing: 1px; font-weight: 700; }
.mac-key-badge.req { background: rgba(255,107,158,0.18); color: var(--pink);
  border: 1px solid rgba(255,107,158,0.35); }
.mac-key-badge.rec { background: rgba(255,176,84,0.18); color: var(--orange);
  border: 1px solid rgba(255,176,84,0.35); }
.mac-key-badge.opt { background: var(--glass); color: var(--txt-mute);
  border: 1px solid var(--stroke); }
.mac-key-desc { font-size: 12px; color: var(--txt-mute); margin-bottom: 10px; line-height: 1.55; }
.mac-key-row { display: flex; gap: 8px; align-items: center; }
.mac-key-row input { flex: 1; padding: 10px 12px; background: var(--bg-mid);
  border: 1px solid var(--stroke); border-radius: 8px; color: var(--txt);
  font-family: "SF Mono","JetBrains Mono",monospace; font-size: 12px; outline: none; }
.mac-key-row input:focus { border-color: var(--cyan); }
.mac-key-link { font-size: 11px; color: var(--cyan); cursor: pointer; margin-bottom: 10px;
  display: inline-block; }
.mac-key-link:hover { text-decoration: underline; }
.mac-theme-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.mac-theme-opt { padding: 18px; border-radius: 16px; cursor: pointer;
  background: var(--glass-2); border: 1px solid var(--stroke); transition: all .2s; }
.mac-theme-opt:hover { border-color: var(--cyan); transform: translateY(-2px); }
.mac-theme-opt.active { border-color: var(--cyan);
  box-shadow: 0 0 0 2px rgba(90,216,255,0.25); }
.mac-theme-opt h4 { font-size: 14px; font-weight: 700; margin-bottom: 4px; }
.mac-theme-opt p { font-size: 11px; color: var(--txt-mute); }
.mac-alarm-row { display: grid; grid-template-columns: 80px 1fr auto; gap: 14px;
  align-items: center; padding: 14px 16px; background: var(--glass-2);
  border: 1px solid var(--stroke); border-radius: 14px; margin-bottom: 8px; }
.mac-alarm-time { font-size: 22px; font-weight: 700; font-family: "SF Mono",monospace;
  color: var(--cyan); font-variant-numeric: tabular-nums; }
.mac-alarm-label { font-size: 13px; color: var(--txt); }
.mac-alarm-meta { font-size: 11px; color: var(--txt-mute); margin-top: 2px; }
`;

function _isMacOS() {
  return !!document.getElementById('rail') && !!document.getElementById('main');
}

function _ensureMacCSS() {
  if (document.getElementById('mac-page-css')) return;
  const st = document.createElement('style'); st.id = 'mac-page-css';
  st.textContent = _MAC_CSS;
  document.head.appendChild(st);
}

function macosNav(page, sub) {
  if (!_isMacOS()) { openSettings(page === 'cerebro' ? 'cerebro' : (sub || page)); return; }
  _ensureMacCSS();
  const main = document.getElementById('main');
  if (!main) return;
  if (_macDashHTML === null) _macDashHTML = main.innerHTML;

  // Marca rail-btn ativo (ordem real do rail: 1 Dashboard · 2 Histórico ·
  // 3 Alarmes · 4 Áudio · 5 Setup · 6 Cérebro · 7 Tema · 8 Config)
  document.querySelectorAll('#rail .rail-btn').forEach(b => b.classList.remove('active'));
  const idx = {dashboard:1, history:2, alarmes:3, audio:4, setup:5,
               cerebro:6, theme:7, config:8}[page];
  if (idx) {
    const btns = document.querySelectorAll('#rail .rail-btn');
    if (btns[idx-1]) btns[idx-1].classList.add('active');
  }

  _macCurrentPage = page;
  if (page === 'dashboard') {
    main.innerHTML = _macDashHTML;
    return;
  }
  main.innerHTML = `<div class="mac-page" id="mac-page-root"><div class="mac-page-head"><div><div class="mac-page-title">Carregando…</div></div></div></div>`;
  const root = document.getElementById('mac-page-root');
  if (page === 'config' || page === 'cerebro') {
    _macPageConfig(root, page === 'cerebro' ? 'cerebro' : sub);
    return;
  }
  ({history:_macPageHistory, alarmes:_macPageAlarmes, audio:_macPageAudio,
    setup:_macPageSetup, theme:_macPageTheme}[page] || _macPageHistory)(root);
}
window.macosNav = macosNav;

function _macPageHistory(root) {
  root.innerHTML = `
    <div class="mac-page-head">
      <div>
        <div class="mac-page-title">Histórico de Conversas</div>
        <div class="mac-page-sub">Últimas trocas entre você e o J.A.R.V.I.S.</div>
      </div>
      <button class="mac-btn ghost" onclick="macosNav('history')">${_IC.refresh}Recarregar</button>
    </div>
    <div class="card"><div id="mac-hist-list" class="mac-list"><div class="mac-empty">Carregando histórico…</div></div></div>`;
  pyApiAsync('list_history', 80).then(r => {
    const list = document.getElementById('mac-hist-list'); if (!list) return;
    if (!r || !r.ok) { list.innerHTML = '<div class="mac-empty">Não foi possível carregar.</div>'; return; }
    const items = (r.items || []).slice().reverse();
    if (!items.length) { list.innerHTML = '<div class="mac-empty">Nenhuma conversa registrada ainda.</div>'; return; }
    list.innerHTML = items.map(it => {
      const role = (it.role || 'sys').toLowerCase();
      const txt = it.text || it.content || '';
      let ts = '';
      if (it.ts) {
        try {
          const d = typeof it.ts === 'number' ? new Date(it.ts*1000) : new Date(it.ts);
          if (!isNaN(d.getTime())) ts = d.toLocaleString('pt-BR', {hour12:false});
        } catch(e) {}
      }
      const isU = role === 'user' || role === 'senhor';
      return `<div class="mac-row"><span class="role-badge ${isU?'role-u':'role-j'}">${isU?'VOCÊ':'JARVIS'}</span><div class="row-body">${escHtml(txt)}</div><div class="row-ts">${escHtml(ts)}</div></div>`;
    }).join('');
  });
}

function _macPageAlarmes(root) {
  root.innerHTML = `
    <div class="mac-page-head">
      <div>
        <div class="mac-page-title">Alarmes</div>
        <div class="mac-page-sub">Gerencie seus alarmes ativos.</div>
      </div>
      <button class="mac-btn ghost" onclick="macosNav('alarmes')">${_IC.refresh}Recarregar</button>
    </div>
    <div class="card"><div id="mac-al-list"><div class="mac-empty">Carregando…</div></div></div>`;
  pyApiAsync('list_alarmes').then(r => {
    const list = document.getElementById('mac-al-list'); if (!list) return;
    const items = (r && r.alarmes) || [];
    if (!items.length) { list.innerHTML = '<div class="mac-empty">Nenhum alarme cadastrado.<br><span style="font-size:11px;opacity:.7">Diga &quot;Jarvis, me acorde às 7h&quot; para criar.</span></div>'; return; }
    list.innerHTML = items.map(a => {
      const tm = a.hora || a.time || '--:--';
      const lbl = a.descricao || a.label || a.titulo || 'Alarme';
      const id = a.id || a.uuid || '';
      const ativo = a.ativo !== false;
      return `<div class="mac-alarm-row" style="${ativo?'':'opacity:.5'}">
        <div class="mac-alarm-time">${escHtml(tm)}</div>
        <div><div class="mac-alarm-label">${escHtml(lbl)}</div>
          <div class="mac-alarm-meta">${ativo?'Ativo':'Pausado'}</div></div>
        <button class="mac-btn ghost" onclick="_macDelAlarme('${escHtml(id)}')">Remover</button>
      </div>`;
    }).join('');
  });
}
function _macDelAlarme(id) {
  if (!confirm('Remover este alarme?')) return;
  pyApiAsync('delete_alarme', id).then(() => macosNav('alarmes'));
}
window._macDelAlarme = _macDelAlarme;

function _macPageAudio(root) {
  root.innerHTML = `
    <div class="mac-page-head">
      <div>
        <div class="mac-page-title">Áudio & Voz</div>
        <div class="mac-page-sub">Microfone, voz do assistente e ElevenLabs.</div>
      </div>
    </div>
    <div class="card" id="mac-audio-card"><div class="mac-empty">Carregando…</div></div>`;
  const card = document.getElementById('mac-audio-card');
  // Reaproveita o renderer existente do drawer dentro do card macOS
  card.innerHTML = '<div id="mac-audio-inner"></div>';
  const body = document.getElementById('mac-audio-inner');
  try { _renderAudio(body); } catch(e) { card.innerHTML = '<div class="mac-empty">Erro: '+escHtml(String(e))+'</div>'; }
}

/* ── Página: Configurações (full-screen no rail, FORA do modal) ─────────────
   Reaproveita os renderers do drawer (_renderModels/_renderCerebro/…) dentro
   de uma .mac-page com sub-nav. `_ensureDrawer()` injeta só o CSS `.jb-*`
   (global) — o drawer em si fica oculto, nunca é aberto. */
const _MAC_CFG_SECTIONS = [
  {key:'all',     label:'Geral'},
  {key:'models',  label:'Modelos'},
  {key:'cerebro', label:'Cérebro'},
  {key:'msg',     label:'Mensageria'},
  {key:'people',  label:'Pessoas'},
  {key:'audio',   label:'Áudio'},
  {key:'setup',   label:'Chaves API'},
  {key:'theme',   label:'Aparência'},
];
let _macCfgSection = 'all';
function _macPageConfig(root, section) {
  _ensureDrawer(); // garante CSS .jb-* (drawer permanece oculto)
  section = section || _macCfgSection || 'all';
  if (!_MAC_CFG_SECTIONS.some(s => s.key === section)) section = 'all';
  _macCfgSection = section;
  const pills = _MAC_CFG_SECTIONS.map(s =>
    `<button class="mac-cfg-pill${s.key===section?' active':''}" data-cfg="${s.key}" onclick="_macCfgGo('${s.key}')">${escHtml(s.label)}</button>`
  ).join('');
  root.innerHTML = `
    <div class="mac-page-head">
      <div>
        <div class="mac-page-title">Configurações</div>
        <div class="mac-page-sub">Cérebro, modelos, mensageria e ajustes — em tela cheia, fora do modal.</div>
      </div>
    </div>
    <div class="mac-cfg-nav">${pills}</div>
    <div class="card"><div id="mac-cfg-body"><div class="mac-empty">Carregando…</div></div></div>`;
  _macCfgRender(section);
}
function _macCfgGo(key) {
  if (!_MAC_CFG_SECTIONS.some(s => s.key === key)) key = 'all';
  _macCfgSection = key;
  document.querySelectorAll('#mac-page-root .mac-cfg-pill').forEach(b =>
    b.classList.toggle('active', b.dataset.cfg === key));
  _macCfgRender(key);
}
window._macCfgGo = _macCfgGo;
function _macCfgRender(key) {
  const body = _qs('mac-cfg-body'); if (!body) return;
  body.innerHTML = '<div class="mac-empty">Carregando…</div>';
  const map = {all:_renderAllConfigs, models:_renderModels, cerebro:_renderCerebro,
    msg:_renderMessaging, people:_renderPeople, audio:_renderAudio,
    setup:_renderSetup, theme:_renderTheme};
  try { (map[key] || _renderAllConfigs)(body); }
  catch (e) { body.innerHTML = '<div class="mac-empty">Erro ao renderizar: '+escHtml(String(e))+'</div>'; }
}

function _macPageSetup(root) {
  root.innerHTML = `
    <div class="mac-page-head">
      <div>
        <div class="mac-page-title">Credenciais de API</div>
        <div class="mac-page-sub">Configure suas chaves para Groq, ElevenLabs, OpenAI e outros serviços.</div>
      </div>
    </div>
    <div id="mac-keys-wrap"><div class="mac-empty">Carregando chaves…</div></div>`;
  pyApiAsync('get_env_keys').then(resp => {
    const wrap = document.getElementById('mac-keys-wrap'); if (!wrap) return;
    const keys = Array.isArray(resp) ? resp : (resp && resp.keys) || [];
    if (!keys.length) { wrap.innerHTML = '<div class="mac-empty">Nenhuma chave registrada.</div>'; return; }
    wrap.innerHTML = '<div class="card">' + keys.map(k => {
      const tier = k.tier || k.tipo || 'opcional';
      const cls = tier === 'obrigatorio' ? 'req' : '';
      const badge = tier === 'obrigatorio' ? '<span class="mac-key-badge req">OBRIGATÓRIA</span>'
                  : tier === 'recomendado' ? '<span class="mac-key-badge rec">RECOMENDADA</span>'
                  : '<span class="mac-key-badge opt">OPCIONAL</span>';
      const masked = k.masked || k.value_mask || '';
      const url = k.help_url || k.url || '';
      return `<div class="mac-key-card ${cls}">
        <div class="mac-key-head"><div class="mac-key-name">${escHtml(k.label || k.key)}</div>${badge}</div>
        <div class="mac-key-desc">${escHtml(k.desc || '')}</div>
        ${url ? `<a class="mac-key-link" onclick="pyApi('open_url','${escHtml(url)}')">Obter chave</a>` : ''}
        <div class="mac-key-row">
          <input type="password" placeholder="${masked ? 'Atual: '+escHtml(masked) : 'Cole sua chave aqui'}" data-mackey="${escHtml(k.key)}">
          <button class="mac-btn" onclick="_macSaveKey('${escHtml(k.key)}', this)">Salvar</button>
        </div>
      </div>`;
    }).join('') + '</div>';
  });
}
function _macSaveKey(key, btn) {
  const row = btn.closest('.mac-key-card');
  const inp = row && row.querySelector('input[data-mackey]');
  if (!inp || !inp.value.trim()) { return; }
  btn.textContent = 'Salvando…'; btn.disabled = true;
  pyApiAsync('save_env_keys', {[key]: inp.value.trim()}).then(r => {
    btn.disabled = false;
    if (r && r.ok) { btn.innerHTML = _IC.check + ' Salvo'; inp.value = '';
      setTimeout(() => macosNav('setup'), 800); }
    else { btn.textContent = 'Erro'; setTimeout(() => btn.textContent = 'Salvar', 1400); }
  }).catch(() => { btn.disabled = false; btn.textContent = 'Salvar'; });
}
window._macSaveKey = _macSaveKey;

function _macPageTheme(root) {
  const cur = (document.body.dataset.theme || 'macos');
  const opts = [
    {id:'stark',   name:'Stark Classic', desc:'HUD original, dashboard completo'},
    {id:'macos',   name:'macOS Glass',   desc:'Cards glassmorphic + chat lateral'},
    {id:'minimal', name:'Minimal Pro',   desc:'Foco no chat, orb animado'},
  ];
  root.innerHTML = `
    <div class="mac-page-head">
      <div>
        <div class="mac-page-title">Tema da Interface</div>
        <div class="mac-page-sub">A janela recarrega ao trocar de tema.</div>
      </div>
    </div>
    <div class="card"><div class="mac-theme-grid">${
      opts.map(o => `<div class="mac-theme-opt ${o.id===cur?'active':''}" onclick="switchTheme('${o.id}')">
        <h4>${escHtml(o.name)}</h4><p>${escHtml(o.desc)}</p></div>`).join('')
    }</div></div>`;
}

/* ═══════════════════════════════════════════════════════════════════════
   SETUP GUIDE — modal flutuante com tutorial de chaves e avisos de ban
   ═══════════════════════════════════════════════════════════════════════ */
function openSetupGuide() {
  if (_qs('jb-guide-overlay')) return; // já aberto
  const ov = document.createElement('div');
  ov.id = 'jb-guide-overlay';
  ov.style.cssText = 'position:fixed;inset:0;z-index:99999;background:rgba(5,12,24,.92);'
    + 'display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';
  ov.innerHTML = `
    <div style="background:#0b1629;border:1px solid rgba(0,212,255,.25);border-radius:16px;max-width:620px;width:92%;max-height:90vh;overflow-y:auto;padding:28px 32px;position:relative">
      <button onclick="document.getElementById('jb-guide-overlay').remove()"
              style="position:absolute;top:14px;right:18px;background:none;border:none;color:#8e96a8;font-size:20px;cursor:pointer;line-height:1" aria-label="Fechar">&times;</button>
      <h2 style="margin:0 0 6px;color:#5ad8ff;font-size:18px;letter-spacing:-.01em">&#x1F680; Guia de Setup &mdash; J.A.R.V.I.S.</h2>
      <p style="margin:0 0 20px;color:#8e96a8;font-size:12px">Configure as chaves de API para ativar os recursos do JARVIS.</p>

      <!-- GROQ -->
      <div style="border:1px solid rgba(0,212,255,.15);border-radius:10px;padding:14px;margin-bottom:12px">
        <h4 style="margin:0 0 4px;color:#ecedf2;font-size:13px">&#x1F511; Groq API Key <span style="background:#ff6b4a;color:#fff;font-size:9px;padding:1px 6px;border-radius:4px;margin-left:6px">OBRIGAT&Oacute;RIO</span></h4>
        <p style="margin:0 0 8px;color:#8e96a8;font-size:11.5px">Prov&ecirc; o c&eacute;rebro principal do JARVIS (classifica&ccedil;&atilde;o + chat + STT Whisper). Plano gratuito &eacute; suficiente.</p>
        <a href="#" onclick="event.preventDefault();pyApi('open_url','https://console.groq.com/keys')"
           style="color:#5ad8ff;font-size:11px;text-decoration:none">&rarr; Obter chave em console.groq.com/keys</a>
      </div>

      <!-- LM Studio -->
      <div style="border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:14px;margin-bottom:12px">
        <h4 style="margin:0 0 4px;color:#ecedf2;font-size:13px">&#x1F5A5;&#xFE0F; LM Studio <span style="background:rgba(90,216,255,.13);color:#5ad8ff;font-size:9px;padding:1px 6px;border-radius:4px;margin-left:6px">OPCIONAL</span></h4>
        <p style="margin:0 0 4px;color:#8e96a8;font-size:11.5px">Para rodar IA 100% local (sem internet, sem custo por token). Instale LM Studio, carregue um modelo e inicie o servidor em <code style="color:#5ad8ff">http://127.0.0.1:1234</code>.</p>
        <a href="#" onclick="event.preventDefault();pyApi('open_url','https://lmstudio.ai')"
           style="color:#5ad8ff;font-size:11px;text-decoration:none">&rarr; Download em lmstudio.ai</a>
      </div>

      <!-- ElevenLabs -->
      <div style="border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:14px;margin-bottom:12px">
        <h4 style="margin:0 0 4px;color:#ecedf2;font-size:13px">&#x1F50A; ElevenLabs TTS <span style="background:rgba(90,216,255,.13);color:#5ad8ff;font-size:9px;padding:1px 6px;border-radius:4px;margin-left:6px">OPCIONAL</span></h4>
        <p style="margin:0 0 8px;color:#8e96a8;font-size:11.5px">Voz real&iacute;stica para o JARVIS. Sem isso, usa Microsoft Edge TTS (gratuito, qualidade menor).</p>
        <a href="#" onclick="event.preventDefault();pyApi('open_url','https://elevenlabs.io/app/api-key')"
           style="color:#5ad8ff;font-size:11px;text-decoration:none">&rarr; Obter chave em elevenlabs.io</a>
      </div>

      <!-- Spotify -->
      <div style="border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:14px;margin-bottom:12px">
        <h4 style="margin:0 0 4px;color:#ecedf2;font-size:13px">&#x1F3B5; Spotify <span style="background:rgba(90,216,255,.13);color:#5ad8ff;font-size:9px;padding:1px 6px;border-radius:4px;margin-left:6px">OPCIONAL</span></h4>
        <p style="margin:0 0 8px;color:#8e96a8;font-size:11.5px">Controle do Spotify por voz. Crie um app em developer.spotify.com, use <code style="color:#5ad8ff">http://127.0.0.1:8888/callback</code> como Redirect URI.</p>
        <a href="#" onclick="event.preventDefault();pyApi('open_url','https://developer.spotify.com/dashboard')"
           style="color:#5ad8ff;font-size:11px;text-decoration:none">&rarr; Dashboard em developer.spotify.com</a>
      </div>

      <!-- Instagram WARNING -->
      <div style="border:1px solid rgba(255,107,78,.4);border-radius:10px;padding:14px;margin-bottom:12px;background:rgba(255,107,78,.05)">
        <h4 style="margin:0 0 6px;color:#ff6b4a;font-size:13px">&#x26A0;&#xFE0F; Aten&ccedil;&atilde;o &mdash; Instagram</h4>
        <p style="margin:0;color:#cfd2dc;font-size:11.5px;line-height:1.6">
          A integra&ccedil;&atilde;o de mensagens do Instagram usa automa&ccedil;&atilde;o que <strong style="color:#ff6b4a">viola os Termos de Servi&ccedil;o do Instagram</strong>.
          O uso pode resultar em <strong>suspens&atilde;o ou banimento permanente da conta</strong>.
          Use apenas com contas descart&aacute;veis ou sob total responsabilidade pr&oacute;pria.
          O autor do JARVIS n&atilde;o se responsabiliza por banimentos.
        </p>
      </div>

      <!-- Discord WARNING -->
      <div style="border:1px solid rgba(255,107,78,.4);border-radius:10px;padding:14px;margin-bottom:20px;background:rgba(255,107,78,.05)">
        <h4 style="margin:0 0 6px;color:#ff6b4a;font-size:13px">&#x26A0;&#xFE0F; Aten&ccedil;&atilde;o &mdash; Discord</h4>
        <p style="margin:0;color:#cfd2dc;font-size:11.5px;line-height:1.6">
          Usar <em>User Tokens</em> do Discord para automa&ccedil;&atilde;o <strong style="color:#ff6b4a">viola os Termos de Servi&ccedil;o do Discord</strong>
          e pode resultar em <strong>banimento permanente da conta</strong>.
          Para uso seguro, configure um <strong>Bot Token oficial</strong> pelo Discord Developer Portal.
        </p>
        <a href="#" onclick="event.preventDefault();pyApi('open_url','https://discord.com/developers/applications')"
           style="color:#5ad8ff;font-size:11px;text-decoration:none;display:block;margin-top:8px">&rarr; Criar Bot em discord.com/developers</a>
      </div>

      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button onclick="document.getElementById('jb-guide-overlay').remove()"
                class="jb-btn" style="min-width:80px">Fechar</button>
        <button onclick="document.getElementById('jb-guide-overlay').remove();openSettings('setup')"
                class="jb-btn jb-btn-pri" style="min-width:160px">Ir para Configura&ccedil;&otilde;es &rarr;</button>
      </div>
    </div>`;
  document.body.appendChild(ov);
  ov.addEventListener('click', e => { if (e.target === ov) ov.remove(); });
}
window.openSetupGuide = openSetupGuide;

/* ── UPDATE TOAST ───────────────────────────────────────────────────────── */
function applyUpdateFromToast(btn, fallbackUrl) {
  if (btn && btn.disabled) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Atualizando...';
  }
  Promise.resolve(pyApi('apply_update_now')).then((rv) => {
    const ok = rv && rv.ok;
    if (ok) {
      const msg = String((rv && rv.msg) || 'Atualização iniciada.');
      try { addMessage('SISTEMA', msg, 'system'); } catch (_) {}
      if (btn) btn.textContent = 'Atualizando';
      return;
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Atualizar';
    }
    const err = String((rv && (rv.error || rv.msg)) || 'Falha ao atualizar automaticamente.');
    try { addMessage('SISTEMA', err, 'erro'); } catch (_) {}
    if (fallbackUrl) pyApi('open_url', fallbackUrl);
  }).catch((e) => {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Atualizar';
    }
    try { addMessage('SISTEMA', `Falha ao atualizar automaticamente: ${e && e.message ? e.message : e}`, 'erro'); } catch (_) {}
    if (fallbackUrl) pyApi('open_url', fallbackUrl);
  });
}

function showUpdateToast(version, url) {
  if (document.getElementById('jb-update-toast')) return;
  const t = document.createElement('div');
  t.id = 'jb-update-toast';
  t.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:88888;'
    + 'background:#0b1629;border:1px solid rgba(90,216,255,.35);border-radius:12px;'
    + 'padding:14px 18px;display:flex;align-items:center;gap:14px;'
    + 'box-shadow:0 4px 24px rgba(0,0,0,.5);max-width:340px;animation:jb-slidein .35s ease;';
  t.innerHTML = `
    <style>@keyframes jb-slidein{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}</style>
    <div style="flex:1;min-width:0">
      <div style="color:#5ad8ff;font-size:12px;font-weight:700;margin-bottom:3px">&#x1F680; Nova vers&atilde;o disponível</div>
      <div style="color:#cfd2dc;font-size:11px">JARVIS v${version} est&aacute; dispon&iacute;vel.</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:6px;flex-shrink:0">
          <button onclick="applyUpdateFromToast(this,'${url}')" class="jb-btn jb-btn-pri"
            style="font-size:10px;padding:5px 10px;min-width:80px">Atualizar</button>
      <button onclick="document.getElementById('jb-update-toast').remove()"
              class="jb-btn" style="font-size:10px;padding:4px 10px">Ignorar</button>
    </div>`;
  document.body.appendChild(t);
}
window.showUpdateToast = showUpdateToast;

/* ── BOOTSTRAP ──────────────────────────────────────────────────────────── */
window.addEventListener('DOMContentLoaded', () => {
  _wireInput();
  let tries = 0;
  function _waitAndCheck() {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_setup_status) {
      checkSetupStatus();
      _preloadChat();
    } else if (tries++ < 40) {
      setTimeout(_waitAndCheck, 100);
    }
  }
  _waitAndCheck();
});
