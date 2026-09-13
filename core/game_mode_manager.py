# core/game_mode_manager.py — Game Mode: libera VRAM para jogos.
#
# Responsabilidades:
#   activate(app)   → descarrega TODOS os modelos carregados, força chat via Groq
#   deactivate(app) → recarrega o modelo de texto, restaura chat local
#
# Fluxo correto segundo docs LM Studio 0.4.6:
#   GET  /api/v1/models → lista modelos; campo loaded_instances[].id = instance_id real
#   POST /api/v1/models/unload  {"instance_id": "<id>"}
#   POST /api/v1/models/load    {"model": "<key>"}

from __future__ import annotations
import requests as _req


# ── Helpers de resposta ────────────────────────────────────────────────────────

def _ok(resp) -> bool:
    """True somente se resposta indica sucesso real (sem {'error':...} no corpo)."""
    if resp.status_code not in (200, 201, 204):
        return False
    try:
        j = resp.json()
        if isinstance(j, dict) and "error" in j:
            return False
    except Exception:
        pass
    return True


# ── GET /api/v1/models ────────────────────────────────────────────────────────

def _listar_modelos(base: str) -> list[dict]:
    """Retorna a lista de modelos de GET /api/v1/models, ou [] em caso de erro."""
    try:
        r = _req.get(f"{base}/api/v1/models", timeout=10)
        if r.status_code == 200:
            return r.json().get("models", [])
    except Exception as e:
        print(f"[GAME MODE] GET /api/v1/models erro: {e}")
    return []


def _instancias_carregadas(base: str) -> list[str]:
    """Retorna lista de instance_id de TODOS os modelos atualmente carregados."""
    ids: list[str] = []
    for model in _listar_modelos(base):
        for inst in model.get("loaded_instances", []):
            inst_id = inst.get("id")
            if inst_id:
                ids.append(inst_id)
    return ids


def _encontrar_chave_modelo(base: str, config_identifier: str) -> str | None:
    """Procura o campo 'key' de um modelo baixado que corresponda ao identificador do config.
    LM Studio usa chaves curtas (ex: 'llama-3.2-3b-instruct'), não o caminho HuggingFace completo."""
    # Extrai o nome curto: "meta-llama/llama-3.2-3b-instruct" → "llama-3.2-3b-instruct"
    short = config_identifier.split("/")[-1].lower()
    for model in _listar_modelos(base):
        key = model.get("key", "")
        # Correspondência exata, por prefixo, ou substring
        if key.lower() == short or short in key.lower() or key.lower() in short:
            print(f"[GAME MODE] Modelo encontrado: key={key!r} para config={config_identifier!r}")
            return key
        # Fallback: verifica display_name
        dn = model.get("display_name", "").lower()
        if short in dn:
            print(f"[GAME MODE] Modelo encontrado via display_name: key={key!r}")
            return key
    print(f"[GAME MODE] Modelo NÃO encontrado na lista: {config_identifier!r} (short={short!r})")
    return None


# ── Unload e Load ─────────────────────────────────────────────────────────────

def _descarregar_instancia(base: str, instance_id: str) -> bool:
    """POST /api/v1/models/unload com o instance_id real retornado pela API."""
    url = f"{base}/api/v1/models/unload"
    try:
        r = _req.post(url, json={"instance_id": instance_id}, timeout=15)
        print(f"[GAME MODE] UNLOAD id={instance_id!r} → {r.status_code} {r.text[:150]}")
        return _ok(r)
    except Exception as e:
        print(f"[GAME MODE] UNLOAD erro para {instance_id!r}: {e}")
        return False


def _carregar_modelo(base: str, key: str) -> bool:
    """POST /api/v1/models/load usando o 'key' do modelo."""
    url = f"{base}/api/v1/models/load"
    try:
        r = _req.post(url, json={"model": key}, timeout=90)
        print(f"[GAME MODE] LOAD key={key!r} → {r.status_code} {r.text[:150]}")
        return _ok(r)
    except Exception as e:
        print(f"[GAME MODE] LOAD erro para {key!r}: {e}")
        return False


# ── API pública ───────────────────────────────────────────────────────────────

def _lm_base(app) -> str:
    from config import LMSTUDIO_BASE_URL
    return LMSTUDIO_BASE_URL.replace("/v1", "").rstrip("/")


def activate(app) -> str:
    """Ativa o Game Mode: descarrega todos os modelos carregados e força chat via Groq.
    Seta app._game_mode = True antes de descarregar para evitar chamadas ao LM Studio."""
    base = _lm_base(app)

    # Força Groq ANTES de descarregar para não bloquear a thread
    app._game_mode = True
    print("[GAME MODE] Ativado — listando instâncias carregadas...")

    instancias = _instancias_carregadas(base)
    print(f"[GAME MODE] Instâncias carregadas: {instancias}")

    if not instancias:
        return (
            "Modo Jogo ativado, senhor. "
            "Nenhum modelo estava carregado no LM Studio. "
            "Estou operando via Groq enquanto você joga."
        )

    descarregados = sum(1 for iid in instancias if _descarregar_instancia(base, iid))

    if descarregados == len(instancias):
        return (
            "Modo Jogo ativado, senhor. "
            f"{descarregados} modelo(s) descarregado(s). VRAM liberada. "
            "Estou operando via Groq enquanto você joga."
        )
    elif descarregados > 0:
        return (
            "Modo Jogo ativado, senhor. "
            f"{descarregados} de {len(instancias)} modelo(s) descarregado(s). "
            "Estou operando via Groq enquanto você joga."
        )
    else:
        return (
            "Modo Jogo ativado, senhor. "
            "Não foi possível descarregar os modelos via API. "
            "Para liberar VRAM completamente, descarregue manualmente no LM Studio. "
            "Estou operando via Groq."
        )


def deactivate(app) -> str:
    """Desativa o Game Mode: recarrega o modelo de texto (visão permanece descarregada).
    Seta app._game_mode = False e zera o circuit breaker `_lm_skip_until`."""
    from config import LMSTUDIO_TEXT_MODEL

    base = _lm_base(app)

    # Desativa modo antes de tentar carregar localmente
    app._game_mode = False
    # Zera o circuit breaker de context-overflow para que o pr\u00f3ximo turno
    # tente o LM Studio novamente em vez de continuar preso no Groq.
    try:
        app._lm_skip_until = 0.0
    except Exception:
        pass
    print("[GAME MODE] Desativado — recarregando modelo de texto via lms (ctx=14000)…")

    # Caminho preferido: usa o helper do app que invoca `lms load --context-length 14000`
    # garantindo que o modelo volte com ctx grande (sen\u00e3o estoura a 4096 default).
    load_ok = False
    try:
        load_ok = bool(app._garantir_lm_model_carregado(
            LMSTUDIO_TEXT_MODEL, context_length=14000, ttl_seconds=0
        ))
    except Exception as e:
        print(f"[GAME MODE] _garantir_lm_model_carregado falhou: {e}")

    # Fallback: se o helper n\u00e3o carregou (ex: lms.exe ausente), tenta a API REST.
    if not load_ok:
        key = _encontrar_chave_modelo(base, LMSTUDIO_TEXT_MODEL)
        if key:
            load_ok = _carregar_modelo(base, key)
        else:
            return (
                "Modo Jogo desativado, senhor. "
                "Não encontrei o modelo de texto na lista do LM Studio. "
                "Por favor, carregue o modelo manualmente no painel. "
                "No momento, continuarei usando o Groq como fallback."
            )

    if load_ok:
        return (
            "Modo Jogo desativado, senhor. "
            "Modelo de linguagem recarregado com contexto estendido. "
            "Voltei à operação local. O modelo de visão permanece descarregado."
        )
    else:
        return (
            "Modo Jogo desativado, senhor. "
            f"Tentei carregar o modelo '{LMSTUDIO_TEXT_MODEL}' mas a API retornou erro. "
            "Por favor, carregue o modelo no painel do LM Studio. "
            "No momento, continuarei usando o Groq como fallback."
        )


def status(app) -> str:
    """Retorna string descrevendo o estado atual do Game Mode."""
    if getattr(app, "_game_mode", False):
        return "Modo Jogo está ATIVO, senhor. IA rodando via Groq, VRAM liberada para jogos."
    return "Modo Jogo está INATIVO, senhor. IA rodando localmente via LM Studio."
