"""Diagnóstico de foco de janelas — o dono roda na sessão dele e cola o resultado (2026-10-21).

    uv run --frozen python tools/diagnostico_foco.py [--sem-titulos] [--sem-navegador]

Pedido do dono: o Jarvis não identificou o Brave em foco no monitor principal (dois monitores,
KDE Plasma/KWin). O que dava para provar fora da máquina dele foi provado num KWin 6.7.5 virtual
(`tools/harness_foco.py`); o KWin de verdade, os monitores de verdade e o Brave de verdade só a
sessão dele mostra. Este roteiro mostra **o que o Jarvis enxerga ali**, com o mesmo código:

- a sessão (Wayland/X11, KDE e a versão que o `kdotool` exige) — só estas variáveis, nunca o resto
  do ambiente (pode ter chave de API);
- o `kdotool`: onde está, a versão e se tem `kwinscript` (a leitura com monitores);
- a leitura nova (monitores, a ativa, a da frente em cada monitor) e a de antes (busca encadeada),
  com o tempo de cada uma;
- o que a ferramenta `window.focused` responderia ao Jarvis agora;
- com a extensão conectada, o que o próprio navegador acha que está em foco (`windows.focused`,
  só leitura: nada abre, nada muda).

Só lê. Não move, não foca e não fecha janela nenhuma; títulos vão cortados em 60 caracteres (ou
nenhum, com `--sem-titulos`: o título de uma aba pode ser privado).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from jarvis.executor.comandos import Saida, ambiente_do_programa, executar  # noqa: E402
from jarvis.executor.janelas import (  # noqa: E402
    EstadoDasJanelas,
    JanelasPorKdotool,
    de_app,
    foco_para_o_modelo,
    janelas_do_ambiente,
)

VARIAVEIS: Final = ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "KDE_SESSION_VERSION")
"""As únicas variáveis que aparecem com o valor. `WAYLAND_DISPLAY` e `DISPLAY`: só se existem."""
CORTE_DO_TITULO: Final = 60


def _titulo(texto: str, sem_titulos: bool) -> str:
    if sem_titulos:
        return "(título omitido)"
    return f"«{texto[:CORTE_DO_TITULO]}{'…' if len(texto) > CORTE_DO_TITULO else ''}»"


def _medir(funcao: Callable[[], Any]) -> tuple[Any, float]:
    comeco = time.perf_counter()
    resultado = funcao()
    return resultado, (time.perf_counter() - comeco) * 1000.0


def _sessao(ambiente: Mapping[str, str], escrever: Callable[[str], None]) -> None:
    valores = " · ".join(f"{v}={ambiente.get(v, '(ausente)')}" for v in VARIAVEIS)
    tem = " · ".join(
        f"{v}: {'sim' if ambiente.get(v) else 'não'}" for v in ("WAYLAND_DISPLAY", "DISPLAY")
    )
    escrever(f"sessão: {valores} · {tem}")
    if ambiente_do_programa("kdotool", ambiente) is not None:
        escrever(
            "  atenção: sem KDE_SESSION_VERSION neste ambiente — o kdotool recusaria rodar; o "
            "Jarvis completa a variável só para ele (comandos.ambiente_do_programa)"
        )


def _kdotool(escrever: Callable[[str], None]) -> bool:
    caminho = shutil.which("kdotool")
    if caminho is None:
        escrever("kdotool: NÃO ENCONTRADO no PATH deste processo — sem ele o Jarvis não vê janelas")
        return False
    try:
        versao = executar(["kdotool", "--version"], 3.0, None)
    except Exception as erro:  # o diagnóstico mostra a falha, não para nela
        escrever(f"kdotool: {caminho} · --version falhou: {type(erro).__name__}: {erro}")
        return True
    escrever(f"kdotool: {caminho} · {(versao.saida or versao.erro).strip()[:60]}")
    return True


def _estado(
    porta: JanelasPorKdotool, sem_titulos: bool, escrever: Callable[[str], None]
) -> EstadoDasJanelas | None:
    lido, ms = _medir(porta.estado)
    estado: EstadoDasJanelas | None = lido
    if estado is None:
        escrever(f"leitura nova (kwinscript): NÃO VEIO ({ms:.0f} ms) — kdotool sem kwinscript?")
        return None
    de_apps = [j for j in estado.janelas if de_app(j)]
    escrever(
        f"leitura nova (kwinscript): {ms:.0f} ms · {len(estado.janelas)} janelas "
        f"({len(de_apps)} de app) · {len(estado.monitores)} monitor(es)"
    )
    for monitor in estado.monitores:
        marca = " (principal)" if monitor.principal else ""
        teclado = " · teclado/mouse aqui" if monitor.nome == estado.monitor_ativo else ""
        escrever(
            f"  monitor {monitor.nome}{marca}: {monitor.largura}×{monitor.altura} em "
            f"{monitor.x},{monitor.y}{teclado}"
        )
    ativa = estado.ativa
    if ativa is None:
        escrever("janela ativa (a do teclado): NENHUMA (tudo minimizado ou a área de trabalho)")
    else:
        escrever(
            f"janela ativa (a do teclado): {ativa.classe} — {_titulo(ativa.titulo, sem_titulos)}"
            f" · monitor {ativa.monitor or '?'}{' (principal)' if ativa.principal else ''}"
        )
    escrever("na frente de cada monitor:")
    for monitor in estado.monitores:
        frente = estado.da_frente(monitor.nome)
        descricao = (
            f"{frente.classe} — {_titulo(frente.titulo, sem_titulos)}"
            if frente is not None
            else "(nenhuma janela de app à vista)"
        )
        escrever(f"  {monitor.nome}{' (principal)' if monitor.principal else ''}: {descricao}")
    escrever("janelas de app (monitor · classe · título · estado):")
    for janela in sorted(de_apps, key=lambda j: (j.monitor, not j.na_frente)):
        estados = [
            nome
            for nome, valor in (
                ("ATIVA", janela.ativa),
                ("na frente", janela.na_frente),
                ("minimizada", janela.minimizada),
                ("noutra área de trabalho", not janela.visivel and not janela.minimizada),
            )
            if valor
        ]
        escrever(
            f"  {janela.monitor or '?'} · {janela.classe} · {_titulo(janela.titulo, sem_titulos)}"
            f" · {', '.join(estados) or 'atrás'}"
        )
    return estado


def _encadeada(escrever: Callable[[str], None]) -> None:
    argv = [
        "kdotool",
        "search",
        "--class",
        ".",
        *("getwindowid", "%@", "getwindowname", "%@"),
        *("getwindowclassname", "%@", "getwindowpid", "%@"),
    ]
    saida, ms = _medir(lambda: executar(argv, 5.0, None))
    linhas = [linha for linha in saida.saida.splitlines() if linha.strip()]
    escrever(
        f"leitura de antes (busca encadeada): {ms:.0f} ms · código {saida.codigo} · "
        f"{len(linhas) // 4 if linhas else 0} janelas"
    )
    ativa: Saida
    ativa, ms = _medir(lambda: executar(["kdotool", "getactivewindow"], 3.0, None))
    situacao = "ok" if ativa.ok else f"FALHOU ({ativa.erro.strip()[:80]})"
    escrever(f"  getactivewindow: {situacao} · {ms:.0f} ms")


def _navegador(escrever: Callable[[str], None]) -> None:
    """O que o próprio navegador acha que está em foco — pela extensão, só leitura."""
    from jarvis.navegador.cliente import (
        ClienteDoNavegador,
        NavegadorFalhou,
        NavegadorIndisponivel,
        TransporteUnix,
    )

    try:
        cliente = ClienteDoNavegador(TransporteUnix.do_ambiente(os.environ))
        foco, ms = _medir(cliente.janela_em_foco)
    except (NavegadorIndisponivel, NavegadorFalhou) as erro:
        escrever(f"extensão do navegador: sem resposta ({str(erro)[:120]})")
        return
    escrever(
        f"extensão do navegador ({ms:.0f} ms): janela em foco para o navegador = "
        f"{foco.get('janelaId')} · aba ativa {foco.get('abaAtivaId')} · janelas "
        f"{foco.get('janelas')} (sem janela em foco = o navegador não é a janela ativa)"
    )


def principal(argv: Sequence[str] | None = None, escrever: Callable[[str], None] = print) -> int:
    opcoes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opcoes.add_argument("--sem-titulos", action="store_true", help="não mostra os títulos")
    opcoes.add_argument(
        "--sem-navegador", action="store_true", help="não pergunta nada à extensão do navegador"
    )
    args = opcoes.parse_args(argv)
    escrever(f"Diagnóstico de foco do Jarvis — {datetime.now():%Y-%m-%d %H:%M:%S}")
    _sessao(os.environ, escrever)
    porta = janelas_do_ambiente(os.environ)
    escrever(
        f"porta de janelas que o Jarvis usaria: {type(porta).__name__ if porta else 'nenhuma'}"
    )
    if _kdotool(escrever):
        kdotool = JanelasPorKdotool()
        _estado(kdotool, args.sem_titulos, escrever)
        _encadeada(escrever)
    if porta is not None:
        resposta, ms = _medir(lambda: foco_para_o_modelo(porta))
        if args.sem_titulos:
            texto = json.dumps(resposta, ensure_ascii=False)
            for janela in [resposta.get("foco")] + [
                m.get("na_frente") for m in resposta.get("monitores", [])
            ]:
                if isinstance(janela, dict) and janela.get("titulo"):
                    texto = texto.replace(json.dumps(janela["titulo"])[1:-1], "(título omitido)")
        else:
            texto = json.dumps(resposta, ensure_ascii=False)
        escrever(f"window.focused responderia ({ms:.0f} ms): {texto[:1500]}")
    if not args.sem_navegador:
        _navegador(escrever)
    escrever(
        "Cole tudo isto na conversa. Para ver mudar: deixe o Brave na frente do monitor principal, "
        "clique noutra janela do segundo monitor e rode de novo."
    )
    return 0


if __name__ == "__main__":
    sys.exit(principal())
