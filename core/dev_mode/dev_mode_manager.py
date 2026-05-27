# core/dev_mode/dev_mode_manager.py — Orquestrador do Modo Desenvolvedor.
#
# Módulo funcional (sem classe) — segue o padrão de core/game_mode_manager.py.
# Recebe `app` (instância de JarvisApp) como parâmetro para manipular estado.
#
# API pública:
#   activate(app)   → ativa modo dev, inicia WebSocket bridge
#   deactivate(app) → desativa modo dev, para WebSocket bridge
#   status(app)     → retorna string de status
#   send_task(app, intent, user_request) → pipeline completo: analyze → build → guard → send

from __future__ import annotations

import json
import os

from core.dev_mode.prompt_architect import architect_prompt
from core.dev_mode.prompt_guard import validate_prompt
from core.dev_mode.vscode_bridge import VSCodeBridge
from core.dev_mode.workspace_analyzer import analyze_workspace


# ── Configuração ──────────────────────────────────────────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "dev_config.json")


def _load_config() -> dict:
    """Carrega dev_config.json. Retorna defaults se não encontrar."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[DEV MODE] Erro ao carregar config: {e}")
        return {"ws_port": 6589, "projects": [], "prompt_defaults": {"execution_mode": "autonomous"}}


def _get_project(config: dict, path_hint: str = "") -> dict | None:
    """Encontra um projeto configurado. Se path_hint vazio, retorna o primeiro."""
    projects = config.get("projects", [])
    if not projects:
        return None

    if path_hint:
        # Tenta match por substring no caminho
        hint_lower = path_hint.lower()
        for proj in projects:
            if hint_lower in proj.get("path", "").lower():
                return proj

    # Retorna o primeiro projeto disponível
    return projects[0]


# ── API pública ───────────────────────────────────────────────────────────────

def activate(app) -> str:
    """Ativa o Modo Desenvolvedor: inicia o servidor WebSocket para comunicação com VSCode.

    Seta app._dev_mode = True e cria/inicia app._dev_bridge.
    Retorna string de feedback para JARVIS falar.
    """
    config = _load_config()
    port = config.get("ws_port", 6589)

    # Cria bridge se não existir
    if not getattr(app, "_dev_bridge", None):
        app._dev_bridge = VSCodeBridge(port=port)

    app._dev_mode = True

    # Inicia o servidor WebSocket
    try:
        app._dev_bridge.start()
    except Exception as e:
        print(f"[DEV MODE] Erro ao iniciar bridge: {e}")
        return (
            "Modo Desenvolvedor ativado, senhor, mas houve um erro ao iniciar "
            f"o servidor WebSocket: {e}. Verifique se a porta {port} está disponível."
        )

    projects = config.get("projects", [])
    proj_names = ", ".join(p.get("name", "?") for p in projects[:3])
    proj_info = f" Projetos configurados: {proj_names}." if proj_names else ""

    # Abre o VSCode no primeiro projeto configurado
    import subprocess
    opened_proj = None
    for proj in projects:
        proj_path = proj.get("path", "").strip()
        if proj_path:
            try:
                subprocess.Popen(["code", proj_path], shell=True)
                opened_proj = proj.get("name", proj_path)
                print(f"[DEV MODE] VSCode aberto em: {proj_path}")
            except Exception as e:
                print(f"[DEV MODE] Erro ao abrir VSCode: {e}")
            break  # abre só o primeiro por padrão

    vscode_info = f" Abrindo '{opened_proj}' no VSCode." if opened_proj else ""

    print(f"[DEV MODE] Ativado. WebSocket na porta {port}.{proj_info}")
    return (
        f"Modo Desenvolvedor ativado, senhor."
        f"{vscode_info}"
        f" Servidor WebSocket pronto na porta {port}.{proj_info}"
    )


def deactivate(app) -> str:
    """Desativa o Modo Desenvolvedor: para o servidor WebSocket.

    Seta app._dev_mode = False e para app._dev_bridge.
    Retorna string de feedback para JARVIS falar.
    """
    app._dev_mode = False

    bridge = getattr(app, "_dev_bridge", None)
    if bridge:
        try:
            bridge.stop()
        except Exception as e:
            print(f"[DEV MODE] Erro ao parar bridge: {e}")
        app._dev_bridge = None

    print("[DEV MODE] Desativado.")
    return "Modo Desenvolvedor desativado, senhor. Servidor WebSocket encerrado."


def status(app) -> str:
    """Retorna string descrevendo o estado atual do Dev Mode."""
    if not getattr(app, "_dev_mode", False):
        return "Modo Desenvolvedor está INATIVO, senhor."

    bridge = getattr(app, "_dev_bridge", None)
    if bridge and bridge.running:
        n = bridge.client_count
        conn_status = f"{n} cliente(s) VSCode conectado(s)" if n > 0 else "nenhum cliente VSCode conectado"
        return f"Modo Desenvolvedor está ATIVO, senhor. Servidor WebSocket rodando — {conn_status}."
    return "Modo Desenvolvedor está ATIVO, senhor, mas o servidor WebSocket não está respondendo."


def send_task(app, intent: str, user_request: str) -> str:
    """Pipeline completo: analisa workspace → monta prompt → valida → envia ao VSCode.

    Args:
        app: Instância de JarvisApp.
        intent: Tipo de tarefa (dev_feature, dev_refactor, dev_debug, dev_test, dev_explain).
        user_request: Descrição da tarefa como falada pelo usuário.

    Returns:
        String de feedback para JARVIS falar.
    """
    # Verifica se o modo dev está ativo
    if not getattr(app, "_dev_mode", False):
        return (
            "Modo Desenvolvedor não está ativo, senhor. "
            "Diga 'ativa modo dev' para começar."
        )

    bridge = getattr(app, "_dev_bridge", None)
    if not bridge or not bridge.running:
        return (
            "Servidor WebSocket não está rodando, senhor. "
            "Reative o modo dev para reconectar."
        )

    if not bridge.is_connected():
        return (
            "Nenhum VSCode conectado, senhor. "
            "Abra o VSCode e conecte a extensão Jarvis Dev Bridge."
        )

    # 1. Carrega config e localiza projeto
    config = _load_config()
    defaults = config.get("prompt_defaults", {})
    proj = _get_project(config)

    if not proj:
        return (
            "Nenhum projeto configurado, senhor. "
            "Adicione um projeto ao dev_config.json."
        )

    project_path = proj.get("path", "")
    print(f"[DEV MODE] Analisando workspace: {project_path}")

    # 2. Analisa workspace
    workspace = analyze_workspace(project_path)
    print(f"[DEV MODE] Projeto: {workspace.project_name}, Linguagem: {workspace.language}, "
          f"Framework: {workspace.framework or 'nenhum'}")

    # 2b. Captura screenshot com Qwen para contexto visual
    visual_context = ""
    try:
        import base64, io
        from PIL import ImageGrab
        img = ImageGrab.grab()
        max_w = 1280
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        from config import LMSTUDIO_VISION_MODEL
        msgs = [
            {"role": "system", "content": (
                "You are a screen analysis assistant. Describe concisely what is currently "
                "visible on the screen: open files, visible code, error messages, terminal output, "
                "active applications. Be specific and factual. Max 8 sentences."
            )},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": f"The developer said: '{user_request}'. What do you see on screen that is relevant?"}
            ]},
        ]
        resp = app._lm.chat.completions.create(
            model=LMSTUDIO_VISION_MODEL,
            messages=msgs,
            max_tokens=400,
            temperature=0.3,
        )
        visual_context = resp.choices[0].message.content or ""
        print(f"[DEV MODE] Contexto visual capturado ({len(visual_context)} chars)")
    except Exception as e:
        print(f"[DEV MODE] Visão indisponível (Qwen não carregado?): {e}")

    # 3. Constrói prompt estruturado
    autonomous = defaults.get("execution_mode", "autonomous") == "autonomous"
    prompt = architect_prompt(
        intent=intent,
        user_request=user_request,
        workspace=workspace,
        autonomous=autonomous,
        visual_context=visual_context,
    )
    print(f"[DEV MODE] Prompt gerado ({len(prompt)} chars)")

    # 4. Valida prompt (Prompt Guard)
    validation = validate_prompt(prompt)
    if not validation.is_valid:
        warnings_text = "; ".join(validation.warnings[:3])
        print(f"[DEV MODE] Prompt REJEITADO: {warnings_text}")
        return (
            f"O prompt foi rejeitado pela validação de segurança, senhor. "
            f"Problemas encontrados: {warnings_text}."
        )

    if validation.warnings:
        print(f"[DEV MODE] Prompt com avisos: {validation.warnings}")

    # 5. Envia ao VSCode via WebSocket
    from core.dev_mode.prompt_templates import INTENT_TO_TEMPLATE
    template_key = INTENT_TO_TEMPLATE.get(intent, "feature_request")

    sent = bridge.send_prompt(
        prompt=validation.sanitized_prompt,
        intent=template_key,
        autonomous=autonomous,
    )

    if sent:
        _INTENT_LABELS = {
            "feature_request": "implementação de feature",
            "refactor": "refatoração",
            "debug": "debugging",
            "test_generation": "geração de testes",
            "explain_code": "explicação de código",
        }
        label = _INTENT_LABELS.get(template_key, template_key)
        return (
            f"Tarefa de {label} enviada ao Copilot, senhor. "
            f"O prompt estruturado foi entregue ao VSCode. "
            f"Projeto: {workspace.project_name}."
        )
    else:
        return (
            "Não foi possível enviar o prompt ao VSCode, senhor. "
            "Verifique a conexão da extensão."
        )
