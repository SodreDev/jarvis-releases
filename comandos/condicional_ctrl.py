# comandos/condicional_ctrl.py — J.A.R.V.I.S.
# Ações condicionais: "se X acontecer, faça Y"
# Monitora: notificações, palavras-chave em janelas, apps em foco, horários
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os
import re
import time
import uuid
import datetime
import threading
from typing import Callable, Optional

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
from config import PATHS
_FILE = PATHS["condicionais"]

# ── Estrutura de uma regra condicional ────────────────────────────────────────
# {
#   "id": "uuid4[:8]",
#   "nome": "Aviso do João",
#   "ativo": true,
#   "condicao": {
#     "tipo": "notificacao_palavra"  | "notificacao_remetente" | "app_em_foco"
#              | "horario"           | "palavra_na_tela",
#     "valor": "João",               # palavra-chave, nome, hora, etc.
#     "app": "discord",              # filtro de app (opcional)
#   },
#   "acao": {
#     "tipo": "tts"         | "som" | "executar_sys",
#     "valor": "João te mandou mensagem!",
#   },
#   "uma_vez": false,   # se true, dispara só na próxima ocorrência e se desativa
#   "disparou_em": "",
# }

_monitor_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_notify_cb: Optional[Callable[[str], None]]  = None   # callback TTS
_execsys_cb: Optional[Callable[[str, str], None]] = None  # callback executar_sys
_som_file: str = ""  # caminho opcional para som de alerta


def _load() -> list[dict]:
    if os.path.exists(_FILE):
        try:
            with open(_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save(regras: list[dict]) -> None:
    with open(_FILE, "w", encoding="utf-8") as f:
        json.dump(regras, f, ensure_ascii=False, indent=2)


def _get_janela_ativa() -> str:
    """Retorna o título da janela em foco."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value.lower()
    except Exception:
        return ""


def _get_app_em_foco() -> str:
    """Retorna o nome do executável do processo em foco."""
    try:
        import ctypes
        import ctypes.wintypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import psutil
        proc = psutil.Process(pid.value)
        return proc.name().lower()
    except Exception:
        return ""


def _tocar_som(caminho: str) -> None:
    try:
        import subprocess
        subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", caminho],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        try:
            import ctypes
            ctypes.windll.winmm.PlaySoundW(caminho, None, 0x0001)  # SND_ASYNC
        except Exception:
            pass


def _disparar_acao(regra: dict) -> None:
    acao = regra.get("acao", {})
    tipo = acao.get("tipo", "tts")
    valor = acao.get("valor", "")
    if tipo == "tts" and _notify_cb:
        _notify_cb(f"Alerta: {valor}")
    elif tipo == "som":
        _tocar_som(valor or _som_file)
    elif tipo == "executar_sys" and _execsys_cb:
        partes = valor.split(":", 1)
        _execsys_cb(partes[0], partes[1] if len(partes) > 1 else "")
    elif tipo == "tts_e_som":
        if _notify_cb:
            _notify_cb(f"Alerta: {valor}")
        if _som_file:
            _tocar_som(_som_file)


# ── Monitor de notificações ───────────────────────────────────────────────────
# O JARVIS já tem monitor de notificações em notif_ctrl.py
# Aqui integramos via shared queue de notificações

_notif_queue: list[dict] = []  # preenchida externamente por notif_ctrl

def enqueue_notificacao(app: str, titulo: str, body: str) -> None:
    """Chamado pelo monitor de notificações do JARVIS para checar condicionais."""
    _notif_queue.append({"app": app, "titulo": titulo, "body": body,
                         "ts": datetime.datetime.now().isoformat()})
    if len(_notif_queue) > 100:
        _notif_queue.pop(0)


def _verificar_regras_notif(notif: dict) -> None:
    regras = _load()
    regras_atualizadas = False
    for r in regras:
        if not r.get("ativo", True):
            continue
        cond = r.get("condicao", {})
        tipo_c = cond.get("tipo", "")
        valor_c = cond.get("valor", "").lower()
        app_c   = cond.get("app", "").lower()

        match   = False
        if tipo_c == "notificacao_remetente":
            texto = notif.get("titulo", "").lower() + " " + notif.get("body", "").lower()
            match = valor_c in texto
            if app_c and app_c not in notif.get("app", "").lower():
                match = False
        elif tipo_c == "notificacao_palavra":
            texto = notif.get("titulo", "").lower() + " " + notif.get("body", "").lower()
            match = bool(re.search(re.escape(valor_c), texto))
            if app_c and app_c not in notif.get("app", "").lower():
                match = False

        if match:
            print(f"[CONDICIONAL] Regra '{r['nome']}' disparada por notificação.")
            _disparar_acao(r)
            r["disparou_em"] = datetime.datetime.now().isoformat()[:16]
            if r.get("uma_vez"):
                r["ativo"] = False
            regras_atualizadas = True

    if regras_atualizadas:
        _save(regras)


def _monitor_loop() -> None:
    """Loop que verifica regras de app_em_foco, horário e recurso_sistema."""
    global _ciclos_recurso
    ultimo_minuto = -1
    ultimo_app = ""
    while not _stop_event.is_set():
        regras = _load()
        agora = datetime.datetime.now()
        regras_atualizadas = False

        # Drena fila de notificações
        while _notif_queue:
            notif = _notif_queue.pop(0)
            _verificar_regras_notif(notif)

        # Intervalo de recurso: a cada 15 ciclos (≈ 30 s)
        _ciclos_recurso += 1
        check_recurso = (_ciclos_recurso % 15 == 0)

        for r in regras:
            if not r.get("ativo", True):
                continue
            cond   = r.get("condicao", {})
            tipo_c = cond.get("tipo", "")
            valor_c = cond.get("valor", "").lower()

            if tipo_c == "app_em_foco":
                app_atual = _get_app_em_foco()
                if valor_c in app_atual and app_atual != ultimo_app:
                    print(f"[CONDICIONAL] Regra '{r['nome']}' — app em foco: {app_atual}")
                    _disparar_acao(r)
                    r["disparou_em"] = agora.isoformat()[:16]
                    if r.get("uma_vez"):
                        r["ativo"] = False
                    regras_atualizadas = True
                ultimo_app = app_atual

            elif tipo_c == "horario":
                if agora.minute != ultimo_minuto:
                    hora_str = valor_c  # HH:MM
                    try:
                        h, m = map(int, hora_str.split(":"))
                        if agora.hour == h and agora.minute == m:
                            print(f"[CONDICIONAL] Regra '{r['nome']}' — horário: {hora_str}")
                            _disparar_acao(r)
                            r["disparou_em"] = agora.isoformat()[:16]
                            if r.get("uma_vez"):
                                r["ativo"] = False
                            regras_atualizadas = True
                    except Exception:
                        pass

            elif tipo_c == "palavra_na_tela":
                janela = _get_janela_ativa()
                if valor_c in janela:
                    print(f"[CONDICIONAL] Regra '{r['nome']}' — '{valor_c}' na tela.")
                    _disparar_acao(r)
                    r["disparou_em"] = agora.isoformat()[:16]
                    if r.get("uma_vez"):
                        r["ativo"] = False
                    regras_atualizadas = True

            elif tipo_c == "recurso_sistema" and check_recurso:
                # valor_cond = "cpu:>:90:%" | "ram:<:2:GB" | "disco:>:90:%"
                partes = valor_c.split(":")
                if len(partes) == 4:
                    recurso, op, limite_str, unidade = partes
                    try:
                        limite = float(limite_str)
                    except ValueError:
                        continue
                    atual = _get_recurso_valor(recurso, unidade)
                    if atual < 0:
                        continue
                    disparar = (op == ">" and atual > limite) or (op == "<" and atual < limite)
                    if disparar:
                        # Anti-spam: aguarda 5 min desde o último disparo
                        ultima = r.get("disparou_em", "")
                        if ultima:
                            try:
                                diff = (agora - datetime.datetime.fromisoformat(ultima)).total_seconds()
                                if diff < 300:
                                    disparar = False
                            except Exception:
                                pass
                    if disparar:
                        op_label = "acima de" if op == ">" else "abaixo de"
                        print(f"[CONDICIONAL] Recurso alert: {recurso} ({atual:.1f}{unidade}) {op_label} {limite}{unidade}")
                        _disparar_acao(r)
                        r["disparou_em"] = agora.isoformat()[:16]
                        if r.get("uma_vez"):
                            r["ativo"] = False
                        regras_atualizadas = True

        if agora.minute != ultimo_minuto:
            ultimo_minuto = agora.minute

        if regras_atualizadas:
            _save(regras)

        _stop_event.wait(2)  # verifica a cada 2s


# Contador de ciclos para polling de recursos (a cada 30s ≈ 15 × 2s)
_ciclos_recurso = 0


def _get_recurso_valor(recurso: str, unidade: str) -> float:
    """Lê o valor atual do recurso via psutil."""
    try:
        import psutil
        if recurso == "cpu":
            return psutil.cpu_percent(interval=0.2)         # %
        elif recurso == "ram":
            mem = psutil.virtual_memory()
            if unidade == "GB":
                return mem.available / 1024 ** 3            # GB livres
            return 100.0 - mem.percent                      # % livre
        elif recurso == "disco":
            du = psutil.disk_usage("C:")
            if unidade == "GB":
                return du.free / 1024 ** 3                  # GB livres
            return du.percent                               # % usado
    except Exception:
        pass
    return -1.0


def start_monitor(
    notify_callback: Callable[[str], None],
    execsys_callback: Callable[[str, str], None],
) -> None:
    global _monitor_thread, _stop_event, _notify_cb, _execsys_cb
    _notify_cb  = notify_callback
    _execsys_cb = execsys_callback
    _stop_event.clear()
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _monitor_thread = threading.Thread(target=_monitor_loop, daemon=True)
    _monitor_thread.start()
    print("[CONDICIONAIS] Monitor iniciado.")


# ── API Pública ──────────────────────────────────────────────────────────────

def criar(
    nome: str,
    tipo_cond: str,
    valor_cond: str,
    tipo_acao: str,
    valor_acao: str,
    app: str = "",
    uma_vez: bool = False,
) -> str:
    """
    Cria uma nova regra condicional.
    tipo_cond: notificacao_remetente | notificacao_palavra | app_em_foco | horario | palavra_na_tela
    tipo_acao: tts | som | executar_sys | tts_e_som
    """
    regras = _load()
    nova = {
        "id":    str(uuid.uuid4())[:8],
        "nome":  nome,
        "ativo": True,
        "condicao": {
            "tipo":  tipo_cond,
            "valor": valor_cond,
            "app":   app,
        },
        "acao": {
            "tipo":  tipo_acao,
            "valor": valor_acao,
        },
        "uma_vez":    uma_vez,
        "disparou_em": "",
        "criada_em":  datetime.datetime.now().isoformat()[:16],
    }
    regras.append(nova)
    _save(regras)
    vez_str = "(uma vez)" if uma_vez else "(sempre)"
    return (
        f"Regra '{nome}' criada {vez_str}: "
        f"Se '{tipo_cond}:{valor_cond}' → {tipo_acao}:'{valor_acao}', senhor."
    )


def listar() -> str:
    regras = _load()
    if not regras:
        return "Nenhuma regra condicional configurada, senhor."
    linhas = []
    for r in regras:
        est = "✅" if r.get("ativo") else "⏸"
        c   = r["condicao"]
        a   = r["acao"]
        linhas.append(
            f"{est} [{r['id']}] '{r['nome']}'\n"
            f"     SE {c['tipo']}:{c['valor']}"
            + (f" (app:{c['app']})" if c.get("app") else "")
            + f" → {a['tipo']}:{a['valor']}"
        )
    return f"Regras condicionais ({len(linhas)}):\n" + "\n".join(linhas)


def pausar_regra(id_ou_nome: str) -> str:
    regras = _load()
    for r in regras:
        if r["id"] == id_ou_nome or r["nome"].lower() == id_ou_nome.lower():
            r["ativo"] = False
            _save(regras)
            return f"Regra '{r['nome']}' pausada, senhor."
    return f"Regra '{id_ou_nome}' não encontrada, senhor."


def ativar_regra(id_ou_nome: str) -> str:
    regras = _load()
    for r in regras:
        if r["id"] == id_ou_nome or r["nome"].lower() == id_ou_nome.lower():
            r["ativo"] = True
            _save(regras)
            return f"Regra '{r['nome']}' ativada, senhor."
    return f"Regra '{id_ou_nome}' não encontrada, senhor."


def remover(id_ou_nome: str) -> str:
    regras = _load()
    antes = len(regras)
    regras = [r for r in regras
              if r["id"] != id_ou_nome and r["nome"].lower() != id_ou_nome.lower()]
    if len(regras) == antes:
        return f"Regra '{id_ou_nome}' não encontrada, senhor."
    _save(regras)
    return f"Regra '{id_ou_nome}' removida, senhor."


# ── Alertas de Recursos do Sistema ───────────────────────────────────────────

def criar_alerta_recurso(texto_cmd: str) -> str:
    """Cria um alerta condicional de recurso (CPU, RAM, disco) por voz.

    Exemplos:
      "me avisa quando a CPU ultrapassar 90%"
      "alerta se a memória RAM ficar abaixo de 2 GB"
      "notifica quando o disco C estiver acima de 90% cheio"
    """
    tl = texto_cmd.lower()

    # Detecta recurso
    if re.search(r"\bcpu\b", tl):
        recurso = "cpu"
        unidade_padrao = "%"
    elif re.search(r"\b(mem[oó]ria|ram)\b", tl):
        recurso = "ram"
        unidade_padrao = "GB"
    elif re.search(r"\b(disco|hd|ssd|armazenamento|c:)\b", tl):
        recurso = "disco"
        unidade_padrao = "%"
    else:
        return "Não entendi o recurso — diga CPU, RAM ou disco, Senhor."

    # Detecta operador
    if re.search(r"\b(?:acima|ultrapassa[r]?|maior|supera[r]?|excede[r]?)\b", tl):
        operador = ">"
        op_label = "acima de"
    elif re.search(r"\b(?:abaixo|menor|cai[r]?|ficar?\s+abaixo|menos\s+de)\b", tl):
        operador = "<"
        op_label = "abaixo de"
    else:
        return "Não entendi a condição — diga 'acima de' ou 'abaixo de', Senhor."

    # Detecta valor + unidade
    m_val = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(gb|%|g\b)?", tl)
    if not m_val:
        return "Não entendi o valor limite, Senhor."
    valor = float(m_val.group(1).replace(",", "."))
    unidade_raw = (m_val.group(2) or "").strip()
    unidade = "GB" if unidade_raw.startswith("g") else (unidade_raw or unidade_padrao)

    # Monta regra
    nome       = f"Recurso {recurso.upper()} {op_label} {valor}{unidade}"
    valor_cond = f"{recurso}:{operador}:{valor}:{unidade}"
    valor_acao = (
        f"Atenção, Senhor: {recurso.upper()} está {op_label} {valor}{unidade}."
    )
    return criar(
        nome=nome,
        tipo_cond="recurso_sistema",
        valor_cond=valor_cond,
        tipo_acao="tts",
        valor_acao=valor_acao,
    )


def listar_alertas_recurso() -> str:
    """Lista apenas as regras do tipo recurso_sistema."""
    regras = [r for r in _load() if r.get("condicao", {}).get("tipo") == "recurso_sistema"]
    if not regras:
        return "Nenhum alerta de recursos configurado, Senhor."
    linhas = [f"Alertas de recursos ({len(regras)}):"]
    for r in regras:
        est = "✅" if r.get("ativo") else "⏸"
        vc  = r["condicao"]["valor"]               # "cpu:>:90:%"
        linhas.append(f"  {est} [{r['id']}] {r['nome']}  (cond: {vc})")
    return "\n".join(linhas)


def cancelar_alertas_recurso() -> str:
    """Remove todas as regras do tipo recurso_sistema."""
    regras = _load()
    antes = len(regras)
    regras = [r for r in regras if r.get("condicao", {}).get("tipo") != "recurso_sistema"]
    removidos = antes - len(regras)
    if removidos == 0:
        return "Nenhum alerta de recursos para cancelar, Senhor."
    _save(regras)
    return f"{removidos} alerta(s) de recursos cancelado(s), Senhor."
