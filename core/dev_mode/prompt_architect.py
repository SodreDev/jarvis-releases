# core/dev_mode/prompt_architect.py — Monta prompts estruturados de alta qualidade.
#
# Transforma uma intenção de desenvolvimento (feature_request, refactor, debug, etc.)
# e a descrição do usuário em um prompt completo e detalhado para o Copilot Agent.
#
# Pipeline: intent + user_request + WorkspaceContext → prompt estruturado

from __future__ import annotations

from core.dev_mode.prompt_templates import (
    AUTONOMOUS_MODE_BLOCK,
    INTENT_TO_TEMPLATE,
    OUTPUT_FORMAT_TEMPLATES,
    ROLE_BLOCK,
    SUPERVISED_MODE_BLOCK,
    WORKFLOW_TEMPLATES,
)
from core.dev_mode.workspace_analyzer import WorkspaceContext


def architect_prompt(
    intent: str,
    user_request: str,
    workspace: WorkspaceContext,
    *,
    autonomous: bool = True,
    visual_context: str = "",
) -> str:
    """Constrói um prompt estruturado completo a partir dos componentes.

    Args:
        intent: Tipo de tarefa (dev_feature, dev_refactor, dev_debug, dev_test, dev_explain).
        user_request: Descrição da tarefa como falada pelo usuário.
        workspace: Contexto do projeto analisado pelo workspace_analyzer.
        autonomous: Se True usa modo autônomo, senão modo supervisionado.

    Returns:
        Prompt completo formatado em seções (ROLE, EXECUTION MODE, etc.).
    """
    # Resolve o template key a partir do intent
    template_key = INTENT_TO_TEMPLATE.get(intent, "feature_request")

    # Monta cada seção
    sections: list[str] = []

    # ── ROLE ──────────────────────────────────────────────────────────────────
    sections.append(f"ROLE\n{ROLE_BLOCK}")

    # ── EXECUTION MODE ────────────────────────────────────────────────────────
    mode_block = AUTONOMOUS_MODE_BLOCK if autonomous else SUPERVISED_MODE_BLOCK
    sections.append(mode_block)

    # ── PROJECT CONTEXT ───────────────────────────────────────────────────────
    ctx_text = workspace.to_prompt_section()
    sections.append(f"PROJECT CONTEXT\n{ctx_text}")

    # ── TASK ──────────────────────────────────────────────────────────────────
    task_section = f"TASK\n{user_request}"
    sections.append(task_section)
    # ── VISUAL CONTEXT (screenshot Qwen) ──────────────────────────────────
    if visual_context:
        sections.append(f"VISUAL CONTEXT (screenshot atual da tela)\n{visual_context}")
    # ── WORKFLOW ──────────────────────────────────────────────────────────────
    steps = WORKFLOW_TEMPLATES.get(template_key, WORKFLOW_TEMPLATES["feature_request"])
    numbered = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))
    sections.append(f"WORKFLOW\n{numbered}")

    # ── OUTPUT FORMAT ─────────────────────────────────────────────────────────
    output_fmt = OUTPUT_FORMAT_TEMPLATES.get(
        template_key, OUTPUT_FORMAT_TEMPLATES["feature_request"]
    )
    sections.append(output_fmt)

    # ── Montagem final ────────────────────────────────────────────────────────
    separator = "\n\n" + "─" * 72 + "\n\n"
    return separator.join(sections)
