/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S Gesture Interface  —  Main Controller
   ═══════════════════════════════════════════════════════════════════════ */

const GestureApp = {
    pollInterval: null,
    statusInterval: null,
    currentMode: 'full',
    gestureLog: [],
    maxLogEntries: 50,

    async init() {
        this.bindNav();
        this.bindModeButtons();
        this.bindControls();
        await this.refreshStatus();
        await this.refreshMode();
        this.startPolling();
        this.initHandCanvas();
    },

    /* ── Navigation ──────────────────────────────────────────────────── */
    bindNav() {
        document.querySelectorAll('.nav-link[data-page]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = link.dataset.page;
                if (page) window.location.href = page;
            });
        });
    },

    /* ── Mode switching ──────────────────────────────────────────────── */
    bindModeButtons() {
        document.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const mode = btn.dataset.mode;
                if (!mode) return;
                const result = JSON.parse(await pywebview.api.set_mode(mode));
                if (!result.error) {
                    this.currentMode = mode;
                    this.updateModeUI(mode);
                    this.addLog(`Mode: ${mode}`, 'mode');
                }
            });
        });
    },

    updateModeUI(mode) {
        document.querySelectorAll('.mode-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.mode === mode);
        });
        const moduleStatus = document.getElementById('module-status');
        if (moduleStatus) {
            const modes = { full: 'D+2D+3D', desktop: 'Desktop', desktop_2d: 'D+2D', design3d: '3D' };
            moduleStatus.textContent = modes[mode] || mode;
        }
    },

    /* ── Controls ────────────────────────────────────────────────────── */
    bindControls() {
        const startBtn = document.getElementById('btn-start');
        const stopBtn = document.getElementById('btn-stop');

        if (startBtn) startBtn.addEventListener('click', async () => {
            await pywebview.api.start_tracker();
            this.addLog('Tracker started', 'system');
            await this.refreshStatus();
        });

        if (stopBtn) stopBtn.addEventListener('click', async () => {
            await pywebview.api.stop_tracker();
            this.addLog('Tracker stopped', 'system');
            await this.refreshStatus();
        });
    },

    /* ── Status polling ──────────────────────────────────────────────── */
    startPolling() {
        this.statusInterval = setInterval(() => this.refreshStatus(), 1000);
        this.pollInterval = setInterval(() => this.pollHandData(), 33); // ~30fps
    },

    async refreshStatus() {
        try {
            const status = JSON.parse(await pywebview.api.get_tracker_status());
            const dot = document.getElementById('tracker-dot');
            if (dot) dot.classList.toggle('active', status.running);

            this.setStatValue('stat-fps', status.fps);
            this.setStatValue('stat-hands', status.hands);
            this.setStatValue('stat-frames', status.frames);
        } catch (_) {} // pywebview may not be ready
    },

    async refreshMode() {
        try {
            const mode = await pywebview.api.get_mode();
            this.currentMode = mode;
            this.updateModeUI(mode);
        } catch (_) {}
    },

    /* ── Hand data polling ───────────────────────────────────────────── */
    async pollHandData() {
        try {
            const data = JSON.parse(await pywebview.api.get_hand_data());
            this.drawHands(data);
        } catch (_) {}
    },

    /* ── Hand canvas visualization ───────────────────────────────────── */
    initHandCanvas() {
        this.handCanvas = document.getElementById('hand-canvas');
        if (!this.handCanvas) return;
        this.handCtx = this.handCanvas.getContext('2d');
        this.resizeHandCanvas();
        window.addEventListener('resize', () => this.resizeHandCanvas());
    },

    resizeHandCanvas() {
        if (!this.handCanvas) return;
        const rect = this.handCanvas.parentElement.getBoundingClientRect();
        this.handCanvas.width = rect.width;
        this.handCanvas.height = rect.height;
    },

    drawHands(handsData) {
        if (!this.handCtx) return;
        const ctx = this.handCtx;
        const w = this.handCanvas.width;
        const h = this.handCanvas.height;

        ctx.clearRect(0, 0, w, h);

        // Grid background
        ctx.strokeStyle = 'rgba(0, 230, 255, 0.05)';
        ctx.lineWidth = 1;
        for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
        for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

        if (!handsData || handsData.length === 0) return;

        const connections = [
            [0,1],[1,2],[2,3],[3,4],       // thumb
            [0,5],[5,6],[6,7],[7,8],       // index
            [0,9],[9,10],[10,11],[11,12],   // middle
            [0,13],[13,14],[14,15],[15,16], // ring
            [0,17],[17,18],[18,19],[19,20], // pinky
            [5,9],[9,13],[13,17],           // palm
        ];

        handsData.forEach(hand => {
            const lm = hand.landmarks;
            const color = hand.handedness === 'Right' ? '#00e6ff' : '#ff8c00';

            // Draw connections
            ctx.strokeStyle = color + '60';
            ctx.lineWidth = 2;
            connections.forEach(([a, b]) => {
                const ax = (1 - lm[a][0]) * w, ay = lm[a][1] * h;
                const bx = (1 - lm[b][0]) * w, by = lm[b][1] * h;
                ctx.beginPath();
                ctx.moveTo(ax, ay);
                ctx.lineTo(bx, by);
                ctx.stroke();
            });

            // Draw landmarks
            lm.forEach((pt, i) => {
                const x = (1 - pt[0]) * w;
                const y = pt[1] * h;
                const r = [0, 4, 8, 12, 16, 20].includes(i) ? 6 : 3;

                ctx.beginPath();
                ctx.arc(x, y, r, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();

                // Glow
                ctx.beginPath();
                ctx.arc(x, y, r + 4, 0, Math.PI * 2);
                ctx.fillStyle = color + '30';
                ctx.fill();
            });
        });
    },

    /* ── Log ─────────────────────────────────────────────────────────── */
    addLog(message, type = 'gesture') {
        const time = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        this.gestureLog.unshift({ time, message, type });
        if (this.gestureLog.length > this.maxLogEntries) this.gestureLog.pop();
        this.renderLog();
    },

    renderLog() {
        const container = document.getElementById('gesture-log');
        if (!container) return;
        container.innerHTML = this.gestureLog.map((entry, i) =>
            `<div class="gesture-log-entry ${i === 0 ? 'active' : ''}">[${entry.time}] ${entry.message}</div>`
        ).join('');
    },

    /* ── Helpers ──────────────────────────────────────────────────────── */
    setStatValue(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value ?? '-';
    },
};

// Boot
window.addEventListener('pywebviewready', () => GestureApp.init());
document.addEventListener('DOMContentLoaded', () => {
    // Fallback if pywebview is slow
    setTimeout(() => { if (!window.pywebview) GestureApp.init(); }, 2000);
});
