# core/dev_mode — Subsistema de Modo Desenvolvedor do J.A.R.V.I.S.
#
# Permite ao Jarvis controlar fluxos de desenvolvimento no VSCode via voz.
# Pipeline: voz → classificação → prompt_architect → prompt_guard → vscode_bridge → Copilot
#
# API pública:
#   activate(app)   → ativa modo dev, inicia WebSocket server
#   deactivate(app) → desativa modo dev, para WebSocket server
#   status(app)     → retorna estado atual
#   send_task(app, intent, user_request) → monta prompt e envia ao VSCode

from __future__ import annotations

from core.dev_mode.dev_mode_manager import activate, deactivate, status, send_task

__all__ = ["activate", "deactivate", "status", "send_task"]
