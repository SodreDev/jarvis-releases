/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S — Canvas 2D Controller
   ═══════════════════════════════════════════════════════════════════════ */

const Canvas2D = {
    canvas: null,
    ctx: null,
    strokes: [],        // completed strokes
    currentStroke: [],   // in-progress points
    isDrawing: false,
    color: '#00e6ff',
    lineWidth: 3,
    pollInterval: null,

    init() {
        this.canvas = document.getElementById('draw-canvas');
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.resize();
        window.addEventListener('resize', () => this.resize());

        // Polling para receber dados da API (comandos vêm do gesture engine)
        this.pollInterval = setInterval(() => this.pollState(), 500);

        // Also allow mouse drawing for testing
        this.canvas.addEventListener('pointerdown', (e) => this.onPointerDown(e));
        this.canvas.addEventListener('pointermove', (e) => this.onPointerMove(e));
        this.canvas.addEventListener('pointerup', () => this.onPointerUp());

        this.render();
    },

    resize() {
        if (!this.canvas) return;
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.render();
    },

    /* ── Pointer events (mouse/touch fallback) ───────────────────────── */
    onPointerDown(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        this.isDrawing = true;
        this.currentStroke = [{ x, y }];
    },

    onPointerMove(e) {
        if (!this.isDrawing) return;
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        this.currentStroke.push({ x, y });
        this.render();
    },

    onPointerUp() {
        if (!this.isDrawing) return;
        this.isDrawing = false;
        if (this.currentStroke.length > 1) {
            this.strokes.push({
                points: [...this.currentStroke],
                color: this.color,
                width: this.lineWidth,
            });
        }
        this.currentStroke = [];
        this.render();
    },

    /* ── Gesture commands (from Python) ──────────────────────────────── */
    executeCommand(cmd) {
        const w = this.canvas.width;
        const h = this.canvas.height;

        switch (cmd.action) {
            case 'start_stroke':
                this.isDrawing = true;
                this.color = cmd.color || this.color;
                this.lineWidth = cmd.width || this.lineWidth;
                this.currentStroke = [{ x: (1 - cmd.x) * w, y: cmd.y * h }];
                break;

            case 'continue_stroke':
                if (this.isDrawing) {
                    this.currentStroke.push({ x: (1 - cmd.x) * w, y: cmd.y * h });
                    this.render();
                }
                break;

            case 'end_stroke':
                if (this.currentStroke.length > 1) {
                    this.strokes.push({
                        points: [...this.currentStroke],
                        color: this.color,
                        width: this.lineWidth,
                    });
                }
                this.currentStroke = [];
                this.isDrawing = false;
                this.render();
                break;

            case 'erase':
                this.eraseAt((1 - cmd.x) * w, cmd.y * h, cmd.radius || 30);
                this.render();
                break;

            case 'clear':
                this.strokes = [];
                this.currentStroke = [];
                this.render();
                break;

            case 'undo':
                this.strokes.pop();
                this.render();
                break;
        }
    },

    eraseAt(ex, ey, radius) {
        this.strokes = this.strokes.filter(stroke => {
            return !stroke.points.some(p => {
                const dx = p.x - ex;
                const dy = p.y - ey;
                return Math.sqrt(dx * dx + dy * dy) < radius;
            });
        });
    },

    /* ── Rendering ───────────────────────────────────────────────────── */
    render() {
        if (!this.ctx) return;
        const ctx = this.ctx;
        const w = this.canvas.width;
        const h = this.canvas.height;

        ctx.clearRect(0, 0, w, h);

        // Grid
        ctx.strokeStyle = 'rgba(0, 230, 255, 0.03)';
        ctx.lineWidth = 1;
        for (let x = 0; x < w; x += 50) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
        for (let y = 0; y < h; y += 50) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

        // Completed strokes
        this.strokes.forEach(stroke => this.drawStroke(stroke.points, stroke.color, stroke.width));

        // Current stroke
        if (this.currentStroke.length > 1) {
            this.drawStroke(this.currentStroke, this.color, this.lineWidth);
        }

        // Stroke counter
        ctx.fillStyle = 'rgba(0, 230, 255, 0.5)';
        ctx.font = '12px "Segoe UI"';
        ctx.fillText(`Strokes: ${this.strokes.length}`, 12, h - 12);
    },

    drawStroke(points, color, width) {
        if (points.length < 2) return;
        const ctx = this.ctx;

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) {
            ctx.lineTo(points[i].x, points[i].y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        ctx.stroke();

        // Glow effect
        ctx.strokeStyle = color + '40';
        ctx.lineWidth = width + 4;
        ctx.stroke();
    },

    /* ── Polling state ───────────────────────────────────────────────── */
    async pollState() {
        try {
            const state = JSON.parse(await pywebview.api.get_canvas_state());
            const colorEl = document.getElementById('current-color');
            if (colorEl && state.color) {
                colorEl.style.backgroundColor = state.color;
            }
        } catch (_) {}
    },

    /* ── Toolbar ─────────────────────────────────────────────────────── */
    setColor(color) {
        this.color = color;
        const colorEl = document.getElementById('current-color');
        if (colorEl) colorEl.style.backgroundColor = color;
    },

    clear() {
        this.strokes = [];
        this.currentStroke = [];
        this.render();
    },

    undo() {
        this.strokes.pop();
        this.render();
    },
};

window.addEventListener('pywebviewready', () => Canvas2D.init());
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => { if (!window.pywebview) Canvas2D.init(); }, 2000);
});
