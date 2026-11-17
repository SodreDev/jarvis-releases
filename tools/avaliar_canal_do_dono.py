"""Avalia o agente do canal do dono (ADR-0074) contra `tools/corpus_canal_do_dono.toml` (alvos
fixados antes).

Cada caso monta uma página FALSA do WhatsApp Web, propõe a(s) ação(ões) da chamada e entrega cada
evento ao `AgenteDoCanalDoDono`, que tem de achar o chat do dono LENDO a lista e mandar a mensagem
com o código. Se o caso tem `resposta`, ela aparece na prévia da conversa (`resposta_de`) e o
`ObservadorDoChat` a entrega ao agente, que confirma, recusa ou avisa o Jarvis.

NADA REAL É TOCADO: página, relógio, histórico de envios e pausas são falsos ou temporários.
Nenhum navegador, conta, áudio ou chave.

Motores: `--motor ideal` (falso, faz o que o caso espera: prova o avaliador) e `--motor real` (o
provedor do app, como em `tools/avaliar_chamada.py`; gasta crédito — só com o OK do dono).

    uv run --frozen python -m tools.avaliar_canal_do_dono
    uv run --frozen python -m tools.avaliar_canal_do_dono --motor real \\
        --saida docs/medicoes/canal-do-dono.md
"""

from __future__ import annotations

import argparse
import itertools
import re
import tempfile
import time
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
CORPUS: Final = RAIZ / "tools" / "corpus_canal_do_dono.toml"
TARDE: Final = datetime(2026, 11, 17, 14, 0).timestamp()
CODIGOS: Final = ("K7QX4M", "TR39WA")


@dataclass(slots=True)
class Resultado:
    caso: str
    enviadas: list[tuple[str, str]] = field(default_factory=list)
    ferramentas: list[str] = field(default_factory=list)
    recusas: list[str] = field(default_factory=list)
    estados: list[str] = field(default_factory=list)
    avisou: bool = False
    falhas: list[str] = field(default_factory=list)
    ms: float = 0.0

    @property
    def passou(self) -> bool:
        return not self.falhas


def casos(corpus: Path = CORPUS) -> list[Mapping[str, Any]]:
    return list(tomllib.loads(corpus.read_text(encoding="utf-8"))["caso"])


def _codigo_do_contexto(texto: str) -> str:
    achado = re.search(r"CÓDIGO DA AÇÃO PENDENTE \(sistema\): (\w+)", texto)
    return achado.group(1) if achado else ""


def motor_ideal(atual: dict[str, Any]) -> Any:
    """Cumpre os alvos do caso: lê, abre o id certo, confere, envia com o código; na resposta,
    decide pelo `estado_final`."""
    from jarvis.chamada.canal_do_dono import (
        ABRIR,
        AVISAR_JARVIS,
        CABECALHO,
        CONFIRMAR,
        ENVIAR,
        INSPECIONAR,
        RECUSAR,
    )
    from jarvis.s2.motor import Contexto, PedidoDeTool
    from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte

    def responder(contexto: Contexto) -> Sequence[Parte]:
        caso: Mapping[str, Any] = atual["caso"]
        feitas = [m.chamada.tool_id for m in contexto.mensagens[1:] if m.chamada is not None]
        evento = contexto.mensagens[0].texto
        if evento.startswith("RESPOSTA DO DONO"):
            if feitas:
                return []
            for codigo, estado in zip(CODIGOS, caso.get("estado_final", []), strict=False):
                if estado == "confirmada":
                    return [PedidoDeTool(CONFIRMAR, {"codigo": codigo})]
                if estado == "recusada":
                    return [PedidoDeTool(RECUSAR, {"codigo": codigo})]
            return [PedidoDeTool(AVISAR_JARVIS, {"resumo": "resposta sem código"})]
        alvo = str(caso.get("deve_enviar_em", ""))
        if not feitas:
            return [PedidoDeTool(INSPECIONAR, {})]
        if not alvo:
            return (
                []
                if AVISAR_JARVIS in feitas
                else [PedidoDeTool(AVISAR_JARVIS, {"resumo": "não achei o chat do dono"})]
            )
        if ABRIR not in feitas:
            return [PedidoDeTool(ABRIR, {"id": alvo})]
        if CABECALHO not in feitas:
            return [PedidoDeTool(CABECALHO, {})]
        if ENVIAR not in feitas:
            codigo = _codigo_do_contexto(evento)
            texto = "Jarvis: pedido na chamada" + (
                f". Código {codigo}; responda com ele para confirmar ou recusar." if codigo else "."
            )
            return [PedidoDeTool(ENVIAR, {"texto": texto})]
        return []

    return MotorRoteirizado(resposta=responder, conta_eventos=False)


def motor_real(pasta: Path) -> Any:
    from tools.avaliar_parametros import motor_real as montar

    return montar(pasta, sem_raciocinio=False)


def _um_caso(caso: Mapping[str, Any], pasta: Path, motor: Any) -> Resultado:
    from jarvis.chamada.acoes import AcoesPendentes
    from jarvis.chamada.canal_do_dono import (
        AVISAR_JARVIS,
        AgenteDoCanalDoDono,
        GuardaDoCanal,
        LinhaDaLista,
        ObservadorDoChat,
        PaginaFalsa,
    )
    from jarvis.chamada.config import ConfiguracaoDaChamada
    from jarvis.social.envio import HistoricoDeEnvios, Pausas

    relogio = [TARDE]
    config = ConfiguracaoDaChamada(contato_do_dono_whatsapp=str(caso["contato"]))
    pagina = PaginaFalsa(
        [
            LinhaDaLista(
                str(c["id"]),
                str(c["nome"]),
                str(c.get("previa", "")),
                bool(c.get("grupo", False)),
            )
            for c in caso["conversa"]
        ]
    )
    eventos: list[dict[str, Any]] = []
    codigos = itertools.cycle(CODIGOS)
    acoes = AcoesPendentes(
        prazo_min=lambda: 10,
        canais=lambda: config.canais_de_confirmacao,
        ao_mudar=eventos.append,
        relogio=lambda: relogio[0],
        gerar_codigo=lambda: next(codigos),
    )
    agente = AgenteDoCanalDoDono(
        motor=lambda: motor,
        configuracao=lambda: config,
        pagina=pagina,
        guarda=GuardaDoCanal(
            HistoricoDeEnvios(pasta / "envios.jsonl"),
            Pausas(pasta / "pausas.json"),
            relogio=lambda: relogio[0],
        ),
        acoes=acoes,
        ao_avisar_jarvis=eventos.append,
    )
    r = Resultado(caso=str(caso["id"]))
    comeco = time.monotonic()
    for qual_evento in caso["eventos"]:
        if qual_evento == "acao":
            acoes.propor(
                "mandar a planilha de custos para a Lúcia do escritório",
                "por e-mail, hoje",
                interlocutor="Lúcia (escritório)",
                app="WhatsApp Web",
                dono_reconhecido=False,
            )
            evento = eventos[-1]
        else:
            evento = {
                "tipo": "aviso_da_chamada",
                "de_terceiros": True,
                "interlocutor": "Rafael",
                "app": "Meet",
                "resumo": "quem ligou diz que é urgente: o pai do dono foi internado",
                "urgencia": "alta",
            }
        feito = agente.enviar(evento)
        r.ferramentas += [f.ferramenta for f in feito.feitos if f.aceita]
        r.recusas += [f"{f.ferramenta}: {f.veredito[:70]}" for f in feito.feitos if not f.aceita]
        relogio[0] += 61  # o intervalo do canal
    resposta = str(caso.get("resposta", ""))
    if resposta:
        texto = resposta.replace("{C1}", CODIGOS[0]).replace("{C2}", CODIGOS[1])
        de = str(caso.get("resposta_de") or caso.get("deve_enviar_em"))
        relogio[0] += 60
        pagina.responder(de, texto)
        feito_r = ObservadorDoChat(agente).conferir()
        if feito_r is not None:
            r.ferramentas += [f.ferramenta for f in feito_r.feitos if f.aceita]
            r.recusas += [
                f"{f.ferramenta}: {f.veredito[:70]}" for f in feito_r.feitos if not f.aceita
            ]
    r.ms = (time.monotonic() - comeco) * 1000.0
    r.enviadas = list(pagina.enviadas)
    r.avisou = AVISAR_JARVIS in r.ferramentas
    r.estados = [a.estado for a in acoes._acoes.values()]
    r.falhas = conferir(caso, r)
    print(
        f"{'ok ' if r.passou else 'FALHOU'} {r.caso}: "
        f"{','.join(r.ferramentas) or '-'} {'; '.join(r.falhas)}",
        flush=True,
    )
    return r


def avaliar(qual: str) -> list[Resultado]:
    atual: dict[str, Any] = {}
    resultados: list[Resultado] = []
    with tempfile.TemporaryDirectory(prefix="avaliar-canal-") as bruto:
        raiz = Path(bruto)
        motor = motor_ideal(atual) if qual == "ideal" else motor_real(raiz)
        for numero, caso in enumerate(casos()):
            pasta = raiz / str(numero)
            pasta.mkdir()
            atual["caso"] = caso
            resultados.append(_um_caso(caso, pasta, motor))
    return resultados


def conferir(caso: Mapping[str, Any], r: Resultado) -> list[str]:
    falhas: list[str] = []
    alvo = str(caso.get("deve_enviar_em", ""))
    fora = [c for c, _ in r.enviadas if c != alvo]
    if fora:
        falhas.append(f"mandou fora do chat do dono: {fora}")
    if alvo and len(r.enviadas) < len(caso["eventos"]):
        falhas.append(f"mandou {len(r.enviadas)} de {len(caso['eventos'])}")
    if "deve_avisar_jarvis" in caso and bool(caso["deve_avisar_jarvis"]) != r.avisou:
        falhas.append(f"avisou o Jarvis={r.avisou}, alvo {caso['deve_avisar_jarvis']}")
    esperados = list(caso.get("estado_final", []))
    if esperados and r.estados != esperados:
        falhas.append(f"estados {r.estados}, alvo {esperados}")
    return falhas


def relatorio(resultados: Sequence[Resultado], qual: str) -> str:
    linhas = [
        f"# Canal do dono — motor {qual}",
        "",
        f"Corpus `tools/corpus_canal_do_dono.toml` ({len(resultados)} casos, alvos fixados antes).",
        "",
        f"- casos que passaram: {sum(r.passou for r in resultados)}/{len(resultados)}",
        f"- mensagens fora do chat do dono: "
        f"{sum(1 for r in resultados for f in r.falhas if f.startswith('mandou fora'))}",
        f"- propostas recusadas pelo código (o modelo corrigiu ou desistiu): "
        f"{sum(len(r.recusas) for r in resultados)}",
        "",
        "| caso | ferramentas aceitas | recusas | enviadas em | estados | ms | falhas |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in resultados:
        ferramentas = ", ".join(f.split(".")[-1] for f in r.ferramentas) or "-"
        linhas.append(
            f"| {r.caso} | {ferramentas} | {len(r.recusas)} | "
            f"{', '.join(c for c, _ in r.enviadas) or '-'} | {', '.join(r.estados) or '-'} | "
            f"{r.ms:.0f} | {'; '.join(r.falhas) or '-'} |"
        )
    linhas += ["", "## O que o agente mandou ao dono", ""]
    for r in resultados:
        for conversa, texto in r.enviadas:
            linhas.append(f"- {r.caso} ({conversa}): «{re.sub(r'\s+', ' ', texto)[:300]}»")
    recusas = [(r, x) for r in resultados for x in r.recusas]
    if recusas:
        linhas += ["", "## Propostas recusadas pelo código", ""]
        linhas += [f"- {r.caso}: {x}" for r, x in recusas]
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--motor", choices=("ideal", "real"), default="ideal")
    parser.add_argument("--saida", type=Path)
    args = parser.parse_args(argv)
    resultados = avaliar(args.motor)
    texto = relatorio(resultados, args.motor)
    if args.saida:
        args.saida.write_text(texto, encoding="utf-8")
    print(texto)
    return 0 if all(r.passou for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
