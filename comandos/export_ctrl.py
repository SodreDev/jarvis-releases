# export_ctrl.py — Exporta o histórico de comandos para .md ou .txt
# Fonte: historico.jsonl (comandos do usuário com timestamp e origem)
import json
import datetime
import pathlib
import os

from config import PATHS

_HISTORICO_FILE = PATHS["historico"]


def _desktop() -> pathlib.Path:
    """Retorna o caminho da Área de Trabalho do usuário."""
    return pathlib.Path(os.environ.get("USERPROFILE", "C:/Users/Public")) / "Desktop"


def exportar_conversa(texto_cmd: str) -> str:
    """Exporta o histórico de comandos para .md ou .txt na Área de Trabalho.

    Detecta no texto do comando:
    - "hoje"   → filtra só os registros de hoje
    - "md" / "markdown" → formato Markdown; caso contrário usa .txt
    """
    tl = texto_cmd.lower()

    # Decide formato (.md ou .txt)
    fmt = "md" if ("md" in tl or "markdown" in tl) else "txt"

    # Filtra só hoje se pedido
    so_hoje = "hoje" in tl
    hoje = datetime.date.today().isoformat()

    try:
        with open(_HISTORICO_FILE, "r", encoding="utf-8") as f:
            entradas = [json.loads(linha) for linha in f if linha.strip()]
    except FileNotFoundError:
        return "Nenhum histórico encontrado para exportar, Senhor."

    if so_hoje:
        entradas = [e for e in entradas if e.get("ts", "").startswith(hoje)]

    if not entradas:
        periodo = "hoje" if so_hoje else "no histórico"
        return f"Nenhum comando encontrado {periodo} para exportar, Senhor."

    # Monta o conteúdo
    ts_arquivo = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefixo    = "hoje" if so_hoje else "completo"
    nome       = f"JARVIS_historico_{prefixo}_{ts_arquivo}.{fmt}"
    destino    = _desktop() / nome

    if fmt == "md":
        linhas = ["# J.A.R.V.I.S — Histórico de Comandos", ""]
        data_atual = None
        for e in entradas:
            data = e.get("ts", "")[:10]
            if data != data_atual:
                data_atual = data
                linhas += [f"## {data}", ""]
            hora   = e.get("ts", "")[11:19]
            icone  = "🎤" if e.get("origem") == "voz" else "⌨️"
            linhas.append(f"- `{hora}` {icone} {e.get('texto', '')}")
        linhas.append("")
        conteudo = "\n".join(linhas)
    else:
        linhas = ["J.A.R.V.I.S — Histórico de Comandos", "=" * 42, ""]
        data_atual = None
        for e in entradas:
            data = e.get("ts", "")[:10]
            if data != data_atual:
                data_atual = data
                linhas += ["", f"[{data}]"]
            hora   = e.get("ts", "")[11:19]
            icone  = "VOZ" if e.get("origem") == "voz" else "TXT"
            linhas.append(f"  {hora}  [{icone}]  {e.get('texto', '')}")
        conteudo = "\n".join(linhas)

    destino.write_text(conteudo, encoding="utf-8")
    n = len(entradas)
    return (
        f"{n} comando(s) exportado(s) para '{nome}' na Área de Trabalho, Senhor."
    )
