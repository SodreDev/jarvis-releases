"""Diagnóstico da ponte com o navegador: o dono roda na sessão dele e cola o resultado (30/10).

    uv run --frozen python tools/diagnostico_navegador.py [--turnos N] [--json]

Pedido do dono: o app travava e o Jarvis «não sabe mais usar a extensão». O que dava para provar
fora da máquina dele foi provado com hosts e extensões falsos (testes) e no contêiner
(`tools/harness_navegador.py`); o Brave de verdade, a extensão que está carregada nele e o host
que ele lançou só a sessão do dono mostra. Este roteiro mostra **o que o Jarvis enxerga ali**,
com o mesmo código:

- a configuração do navegador (`navegador_controlado`, o principal) — só estes campos;
- a instalação: manifestos do host por navegador, o stub e o programa que ele chama, e a cópia
  da extensão que o navegador carrega (`~/.local/share/jarvis/extensao`) contra a do Jarvis;
- os sockets dos hosts (vivo, morto), os processos de host (pid, idade, quem os lançou) e se há
  host repetido da mesma família;
- a versão da ponte em cada host vivo: `host.versao` (o host responde sozinho) e `ponte.versao`
  (a extensão responde) — só versões e permissões: nenhuma aba, URL, título ou página;
- da trilha de diagnóstico, só códigos: como os últimos turnos acabaram, ferramenta que começou e
  não terminou, o erro do motor (já redigido pela trilha);
- no fim, **o que fazer**, em ordem.

Só lê: não abre, não fecha e não mexe em aba nenhuma. Nada de chave nem de ambiente sai daqui.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from jarvis.navegador.cliente import (  # noqa: E402
    ClienteDoNavegador,
    NavegadorIndisponivel,
    TransporteUnix,
    VersaoDaPonte,
    familia_do_host,
)
from jarvis.navegador.estado import manifestos  # noqa: E402
from jarvis.navegador.host import pasta_dos_sockets  # noqa: E402
from jarvis.navegador.instalar import EXTENSAO_NO_USUARIO, STUB_NO_USUARIO  # noqa: E402
from jarvis.navegador.protocolo import VERSAO_DA_PONTE  # noqa: E402
from jarvis.trilha import ARQUIVO as ARQUIVO_DA_TRILHA  # noqa: E402

MODULO_DO_HOST: Final = "jarvis.navegador.host"
CAMPOS_DA_TRILHA: Final = (
    "evento",
    "tool_id",
    "status",
    "codigo",
    "motivo",
    "fim",
    "cancelado",
    "objetivo",
    "ms",
    "ms_total",
    "ms_primeiro_token",
    "motor",
    "erro",
)
"""Os únicos campos da trilha que saem daqui (a trilha já só guarda código e número)."""
VERSAO_NO_JS: Final = re.compile(r"const VERSAO_DA_PONTE = (\d+);")


def _versao_do_manifesto(pasta: Path) -> str:
    try:
        dados = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(dados.get("version", "")) if isinstance(dados, dict) else ""


def _versao_no_fundo(pasta: Path) -> int | None:
    try:
        achado = VERSAO_NO_JS.search((pasta / "background.js").read_text(encoding="utf-8"))
    except OSError:
        return None
    return int(achado.group(1)) if achado else None


def instalacao(home: Path) -> dict[str, Any]:
    """Os manifestos do host, o stub e a cópia da extensão — o que o `--instalar` grava."""
    copia = home / EXTENSAO_NO_USUARIO
    stub = home / STUB_NO_USUARIO
    alvo = ""
    try:
        for linha in stub.read_text(encoding="utf-8").splitlines():
            if linha.startswith("exec "):
                alvo = linha.split()[1]
    except OSError:
        pass
    return {
        "manifestos": [
            {"navegador": m.navegador, "pronto": m.pronto, "executavel": m.executavel}
            for m in manifestos(home)
        ],
        "stub": str(stub) if stub.exists() else "",
        "stub_chama": alvo,
        "stub_chama_existe": bool(alvo) and Path(alvo).exists(),
        "copia_da_extensao": str(copia) if copia.is_dir() else "",
        "copia_manifesto": _versao_do_manifesto(copia),
        "copia_versao_da_ponte": _versao_no_fundo(copia),
        "repositorio_manifesto": _versao_do_manifesto(RAIZ / "extensao"),
        "versao_esperada": VERSAO_DA_PONTE,
    }


def sockets(pasta: Path) -> list[dict[str, Any]]:
    """Cada `*.sock` da pasta dos hosts: aceita conexão (host vivo) ou não (arquivo que sobrou)."""
    achados: list[dict[str, Any]] = []
    try:
        caminhos = sorted(pasta.glob("*.sock"))
    except OSError:
        return achados
    agora = time.time()
    for caminho in caminhos:
        vivo = True
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conexao:
                conexao.settimeout(1.0)
                conexao.connect(str(caminho))
        except OSError:
            vivo = False
        try:
            idade = agora - caminho.stat().st_mtime
        except OSError:
            idade = -1.0
        achados.append(
            {
                "socket": caminho.name,
                "familia": caminho.name.split("-", 1)[0],
                "vivo": vivo,
                "idade_min": round(idade / 60, 1),
            }
        )
    return achados


def _ler(caminho: Path) -> str:
    try:
        return caminho.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def processos_do_host(proc: Path = Path("/proc")) -> list[dict[str, Any]]:
    """Os processos do host (`python -m jarvis.navegador.host`): pid, estado, idade e o nome do
    programa que o lançou (o navegador). Só o nome do executável do pai — nada da linha de comando
    dele."""
    tique = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    try:
        ligado_ha = float(_ler(proc / "uptime").split()[0])
    except (IndexError, ValueError):
        ligado_ha = 0.0
    achados: list[dict[str, Any]] = []
    for pasta in proc.glob("[0-9]*"):
        linha = _ler(pasta / "cmdline").replace("\x00", " ")
        if MODULO_DO_HOST not in linha:
            continue
        estado = _ler(pasta / "stat")
        campos = estado.rsplit(")", 1)[-1].split()
        pai = int(campos[1]) if len(campos) > 1 and campos[1].isdigit() else 0
        inicio = int(campos[19]) if len(campos) > 19 and campos[19].isdigit() else 0
        try:
            nome_do_pai = (proc / str(pai) / "exe").readlink().name if pai else ""
        except OSError:
            nome_do_pai = _ler(proc / str(pai) / "comm").strip()
        achados.append(
            {
                "pid": int(pasta.name),
                "estado": campos[0] if campos else "?",
                "idade_min": round((ligado_ha - inicio / tique) / 60, 1) if inicio else None,
                "pai": pai,
                "lancado_por": nome_do_pai,
                "familia": "firefox" if "moz-extension" in linha or "@" in linha else "chromium",
            }
        )
    return sorted(achados, key=lambda p: p["pid"])


def versoes(pasta: Path, vivos: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """`host.versao` e `ponte.versao` em cada host vivo, com o tempo de cada pergunta."""
    resultado: list[dict[str, Any]] = []
    for item in vivos:
        transporte = TransporteUnix(pasta)
        cliente = ClienteDoNavegador(transporte)
        cliente.navegador = str(item["familia"])
        comeco = time.monotonic()
        try:
            versao: VersaoDaPonte | None = cliente.versao()
            falha = ""
        except NavegadorIndisponivel as erro:
            versao, falha = None, str(erro)[:160]
        ms = round((time.monotonic() - comeco) * 1000, 1)
        resultado.append(
            {
                "socket": item["socket"],
                "familia": item["familia"],
                "ms": ms,
                "falha": falha,
                "host": versao.host if versao else None,
                "extensao": versao.extensao if versao else None,
                "manifesto": versao.manifesto if versao else "",
                "pid_do_host": versao.pid_do_host if versao else None,
                "permissoes": dict(versao.permissoes) if versao else {},
                "o_que_fazer": versao.o_que_fazer() if versao else "",
            }
        )
    return resultado


def trilha(pasta: Path, turnos: int) -> dict[str, Any]:
    """Os últimos `turnos` turnos da trilha, só nos campos de código e número."""
    eventos: list[dict[str, Any]] = []
    for arquivo in (pasta / f"{ARQUIVO_DA_TRILHA}.1", pasta / ARQUIVO_DA_TRILHA):
        for linha in _ler(arquivo).splitlines():
            try:
                dado = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(dado, dict):
                eventos.append(dado)
    ids: list[str] = []
    for evento in eventos:
        turno = str(evento.get("turno", ""))
        if evento.get("evento") == "turno.inicio" and turno not in ids:
            ids.append(turno)
    escolhidos = set(ids[-turnos:])
    linhas: list[dict[str, Any]] = []
    comecadas: dict[tuple[str, str], int] = {}
    for evento in eventos:
        if str(evento.get("turno", "")) not in escolhidos:
            continue
        enxuto = {c: evento[c] for c in CAMPOS_DA_TRILHA if c in evento and evento[c] not in ("",)}
        if "erro" in enxuto:
            enxuto["erro"] = str(enxuto["erro"])[:120]
        if isinstance(evento.get("t"), (int, float)):
            enxuto["hora"] = time.strftime("%d/%m %H:%M:%S", time.localtime(evento["t"]))
        chave = (str(evento.get("turno", "")), str(evento.get("tool_id", "")))
        if evento.get("evento") == "ferramenta.inicio":
            comecadas[chave] = comecadas.get(chave, 0) + 1
        elif evento.get("evento") == "ferramenta" and comecadas.get(chave):
            comecadas[chave] -= 1
        linhas.append(enxuto)
    presas = sorted({tool for (_, tool), n in comecadas.items() if n > 0})
    return {"eventos": linhas, "ferramentas_que_nao_terminaram": presas}


def o_que_fazer(relatorio: Mapping[str, Any]) -> list[str]:
    """Em ordem: o primeiro item destrava o próximo."""
    passos: list[str] = []
    inst = relatorio["instalacao"]
    if not any(m["pronto"] for m in inst["manifestos"]):
        passos.append("rodar `uv run jarvis-native-host --instalar` no repositório do Jarvis")
    elif inst["stub"] and not inst["stub_chama_existe"]:
        passos.append(
            "o stub do host aponta para um programa que não existe mais: rodar "
            "`uv run jarvis-native-host --instalar` de novo"
        )
    if inst["copia_da_extensao"] and inst["copia_versao_da_ponte"] != VERSAO_DA_PONTE:
        passos.append(
            "a cópia da extensão em ~/.local/share/jarvis/extensao é de antes: rodar "
            "`uv run jarvis-native-host --instalar` (copia a nova) e depois Recarregar no navegador"
        )
    vivos = [s for s in relatorio["sockets"] if s["vivo"]]
    if not vivos:
        passos.append(
            "nenhum host vivo: abrir o navegador com a extensão do Jarvis carregada (ou clicar em "
            "Recarregar no card do Jarvis em brave://extensions)"
        )
    por_familia: dict[str, int] = {}
    for item in vivos:
        por_familia[item["familia"]] = por_familia.get(item["familia"], 0) + 1
    repetidas = [f for f, n in por_familia.items() if n > 1]
    if repetidas:
        passos.append(
            f"há mais de um host vivo da família {', '.join(repetidas)} (dois navegadores ou dois "
            "perfis com a extensão): o Jarvis fala com o mais novo — feche o que não usa"
        )
    for versao in relatorio["versoes"]:
        if versao["falha"]:
            passos.append(
                f"o host {versao['socket']} aceitou a conexão mas não respondeu "
                f"({versao['falha']}): Recarregar a extensão do Jarvis no navegador"
            )
        elif versao["o_que_fazer"]:
            passos.append(versao["o_que_fazer"])
    zumbis = [p for p in relatorio["processos"] if p["estado"] == "Z"]
    if zumbis:
        passos.append(
            f"{len(zumbis)} processo(s) de host zumbi: fechar e abrir o navegador os recolhe"
        )
    presas = relatorio["trilha"]["ferramentas_que_nao_terminaram"]
    if presas:
        passos.append(
            f"ferramenta que começou e não terminou na trilha ({', '.join(presas)}): cole este "
            "relatório para a análise"
        )
    return list(dict.fromkeys(passos))


def coletar(
    *,
    home: Path,
    ambiente: Mapping[str, str],
    pasta_da_trilha: Path,
    turnos: int,
    proc: Path = Path("/proc"),
) -> dict[str, Any]:
    pasta = pasta_dos_sockets(ambiente, os.getuid())
    lista = sockets(pasta)
    relatorio: dict[str, Any] = {
        "versao_esperada": VERSAO_DA_PONTE,
        "instalacao": instalacao(home),
        "pasta_dos_sockets": str(pasta),
        "sockets": lista,
        "processos": processos_do_host(proc),
        "versoes": versoes(pasta, [s for s in lista if s["vivo"]]),
        "trilha": trilha(pasta_da_trilha, turnos),
    }
    relatorio["o_que_fazer"] = o_que_fazer(relatorio)
    return relatorio


def _configuracao(ambiente: Mapping[str, str]) -> dict[str, Any]:
    from jarvis.voz.config import ConfiguracaoInvalida, ler

    try:
        configuracao = ler(ambiente=ambiente)
    except (ConfiguracaoInvalida, OSError) as erro:
        return {"erro": str(erro)[:160]}
    return {
        "navegador_controlado": configuracao.navegador_controlado,
        "navegador_principal": configuracao.navegador_principal,
        "familia_do_host": familia_do_host(configuracao.navegador_principal),
    }


def imprimir(relatorio: Mapping[str, Any], escrever: Callable[[str], None]) -> None:
    escrever(f"Jarvis — diagnóstico do navegador (ponte esperada: v{relatorio['versao_esperada']})")
    config = relatorio.get("configuracao", {})
    escrever(f"configuração: {json.dumps(config, ensure_ascii=False)}")
    inst = relatorio["instalacao"]
    prontos = [m["navegador"] for m in inst["manifestos"] if m["pronto"]]
    escrever(f"host instalado para: {', '.join(prontos) or 'nenhum navegador'}")
    escrever(
        f"stub: {inst['stub'] or 'ausente'} → {inst['stub_chama'] or '-'}"
        + ("" if inst["stub_chama_existe"] else " (NÃO EXISTE)")
    )
    escrever(
        f"cópia da extensão: manifesto {inst['copia_manifesto'] or '-'}, ponte "
        f"v{inst['copia_versao_da_ponte']}; repositório: manifesto {inst['repositorio_manifesto']}"
    )
    escrever(f"sockets em {relatorio['pasta_dos_sockets']}:")
    for item in relatorio["sockets"] or [{"socket": "nenhum", "vivo": False, "idade_min": 0}]:
        estado = "vivo" if item["vivo"] else "morto (sobrou do host que saiu)"
        escrever(f"  - {item['socket']}: {estado}, {item['idade_min']} min")
    escrever("processos de host:")
    for processo in relatorio["processos"] or [{"pid": "nenhum"}]:
        escrever(f"  - {json.dumps(processo, ensure_ascii=False)}")
    escrever("versões (host.versao / ponte.versao):")
    for versao in relatorio["versoes"] or [{"socket": "nenhum host vivo"}]:
        escrever(f"  - {json.dumps(versao, ensure_ascii=False)}")
    trilha_ = relatorio["trilha"]
    escrever(f"trilha (últimos turnos, só códigos): {len(trilha_['eventos'])} eventos")
    for evento in trilha_["eventos"][-40:]:
        escrever(f"  {json.dumps(evento, ensure_ascii=False)}")
    escrever("o que fazer:")
    for passo in relatorio["o_que_fazer"] or ["nada: a ponte está em dia"]:
        escrever(f"  - {passo}")


def principal(argv: Sequence[str] | None = None, escrever: Callable[[str], None] = print) -> int:
    opcoes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opcoes.add_argument("--turnos", type=int, default=8, help="turnos da trilha (padrão 8)")
    opcoes.add_argument("--json", action="store_true", help="só a linha RELATORIO {json}")
    args = opcoes.parse_args(argv)
    ambiente = dict(os.environ)
    estado = ambiente.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    relatorio = coletar(
        home=Path.home(),
        ambiente=ambiente,
        pasta_da_trilha=Path(estado) / "jarvis" / "voz" / "diagnostico",
        turnos=max(1, args.turnos),
    )
    relatorio["configuracao"] = _configuracao(ambiente)
    if not args.json:
        imprimir(relatorio, escrever)
    escrever("RELATORIO " + json.dumps(relatorio, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
