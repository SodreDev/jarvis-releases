/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S — Controls / Gesture Training Panel
   ═══════════════════════════════════════════════════════════════════════ */

const Controls = {
    pollInterval: null,

    init() {
        this.bindRecording();
        this.bindDeletion();
        this.refreshGestureList();
        this.pollInterval = setInterval(() => this.refreshGestureList(), 3000);
    },

    /* ── Recording ───────────────────────────────────────────────────── */
    bindRecording() {
        const startBtn = document.getElementById('btn-record-start');
        const stopBtn = document.getElementById('btn-record-stop');
        const statusEl = document.getElementById('record-status');

        if (startBtn) startBtn.addEventListener('click', async () => {
            const name = document.getElementById('gesture-name')?.value?.trim();
            const action = document.getElementById('gesture-action')?.value?.trim();
            if (!name || !action) {
                if (statusEl) statusEl.textContent = 'Preencha nome e ação!';
                return;
            }
            try {
                const result = JSON.parse(await pywebview.api.start_recording(name, action));
                if (result.recording) {
                    if (statusEl) {
                        statusEl.textContent = 'Gravando... Faça o gesto agora.';
                        statusEl.style.color = '#ff2244';
                    }
                    if (startBtn) startBtn.disabled = true;
                    if (stopBtn) stopBtn.disabled = false;
                }
            } catch (_) {}
        });

        if (stopBtn) stopBtn.addEventListener('click', async () => {
            try {
                const result = JSON.parse(await pywebview.api.stop_recording());
                if (result.saved) {
                    if (statusEl) {
                        statusEl.textContent = `Gesto "${result.name}" salvo!`;
                        statusEl.style.color = '#00ff88';
                    }
                    this.refreshGestureList();
                } else {
                    if (statusEl) {
                        statusEl.textContent = 'Nenhum dado gravado.';
                        statusEl.style.color = '#ff8c00';
                    }
                }
                if (startBtn) startBtn.disabled = false;
                if (stopBtn) stopBtn.disabled = true;
            } catch (_) {}
        });
    },

    /* ── Gesture list ────────────────────────────────────────────────── */
    async refreshGestureList() {
        try {
            const gestures = JSON.parse(await pywebview.api.list_custom_gestures());
            const container = document.getElementById('gesture-list');
            if (!container) return;

            if (gestures.length === 0) {
                container.innerHTML = '<div style="color: var(--text-dim); font-size: 13px; padding: 12px;">Nenhum gesto customizado registrado.</div>';
                return;
            }

            container.innerHTML = gestures.map(g => `
                <div class="gesture-item" data-name="${this.escapeHtml(g.name)}">
                    <div>
                        <div class="gesture-item-name">${this.escapeHtml(g.name)}</div>
                        <div class="gesture-item-action">${this.escapeHtml(g.action)} · ${g.frames} frames</div>
                    </div>
                    <button class="btn btn-danger btn-delete-gesture" data-name="${this.escapeHtml(g.name)}" title="Remover">✕</button>
                </div>
            `).join('');

            this.bindDeletion();
        } catch (_) {}
    },

    bindDeletion() {
        document.querySelectorAll('.btn-delete-gesture').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const name = btn.dataset.name;
                if (!name) return;
                try {
                    const result = JSON.parse(await pywebview.api.delete_gesture(name));
                    if (result.deleted) this.refreshGestureList();
                } catch (_) {}
            });
        });
    },

    /* ── helpers ──────────────────────────────────────────────────────── */
    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },
};

window.addEventListener('pywebviewready', () => Controls.init());
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => { if (!window.pywebview) Controls.init(); }, 2000);
});
