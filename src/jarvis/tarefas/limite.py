"""O limite da tarefa vira notificação ao Jarvis, e quem decide é ele (ADR-0070; emenda as ADR-0059
e 0062).

Antes, ao estourar o teto de passos ou de tempo, a guarda de laço ou o orçamento de falhas, o código
escrevia a pergunta («já dei N passos… posso continuar?») ou o fim («Parei sem terminar…», «Não
consegui. Tentei…»). Agora o código só **conta o que aconteceu** — o pedido, cada passo com a
ferramenta, o status e o erro real, o que deu certo, quanto gastou — e entrega isso ao motor da
tarefa, numa rodada sem ferramentas em que ele pode pensar. O motor **decide**:

- `continuar` por mais N passos (até um bloco), com a estratégia nova que ele escolheu;
- `perguntar` algo ao dono, com as palavras dele (a resposta do dono volta a ele como evento);
- `encerrar`, explicando com as palavras dele o que ficou feito e o que faltou.

O código ainda segura o custo, sem escrever frase: o motor continua sozinho no máximo
`CONTINUACOES_SEM_O_DONO` vezes seguidas; depois, as opções dele são perguntar ou encerrar. O «sim»
do dono zera a conta.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

CONTINUACOES_SEM_O_DONO: Final = 2
"""Quantas vezes seguidas o motor pode decidir continuar sem perguntar ao dono."""
PASSOS_NA_NOTIFICACAO: Final = 12
"""Os últimos passos que vão, um por linha, na notificação: o prompt tem teto (ADR-0047)."""
CARACTERES_DO_MOTIVO: Final = 160
MARCA_DA_NOTIFICACAO: Final = "NOTIFICAÇÃO DO LIMITE DA TAREFA"
"""O começo da nota: é por ela que um motor de teste reconhece a rodada da decisão."""


class MotivoDoLimite(StrEnum):
    PASSOS = "teto_de_passos"
    TEMPO = "teto_de_tempo"
    LACO = "laco"
    FALHAS = "orcamento_de_falhas"
    RODADAS = "rodadas_sem_passo"


_O_QUE_E: Final = {
    MotivoDoLimite.PASSOS: "a tarefa chegou ao teto de passos do bloco sem terminar",
    MotivoDoLimite.TEMPO: "a tarefa chegou ao tempo do bloco sem terminar",
    MotivoDoLimite.LACO: "a guarda de laço viu os mesmos passos se repetindo sem avançar, de novo "
    "depois do aviso",
    MotivoDoLimite.FALHAS: "as tentativas que falharam esgotaram o orçamento de falhas",
    MotivoDoLimite.RODADAS: "várias rodadas suas neste passo não chegaram a um passo válido",
}


@dataclass(frozen=True, slots=True)
class LimiteDaTarefa:
    """O motor da tarefa chegou a um limite dele (o orçamento de falhas, as rodadas de um passo):
    não é o fim — o gestor monta a notificação e o motor decide."""

    motivo: MotivoDoLimite
    detalhe: str = ""


@dataclass(frozen=True, slots=True)
class NotificacaoDoLimite:
    """O estado real da tarefa no limite: dado para o motor, nunca frase para o dono."""

    motivo: MotivoDoLimite
    pedido: str
    passos: tuple[str, ...]
    certos: int
    falhos: int
    passos_dados: int
    segundos: float
    bloco: int
    detalhe: str = ""
    proximo: str = ""
    """A ferramenta que o motor ia propor agora (no teto de passos, ele já tinha o próximo)."""
    resposta_do_dono: str = ""
    """O que o dono respondeu à pergunta que o motor fez (vazio = ninguém perguntou)."""
    opcoes: tuple[str, ...] = ("continuar", "perguntar", "encerrar")

    def para_o_motor(self) -> str:
        linhas = [
            f"{MARCA_DA_NOTIFICACAO} (evento do sistema, não é o dono falando): "
            f"{_O_QUE_E[self.motivo]}.",
            f"Pedido: {self.pedido}",
            f"Gasto: {self.passos_dados} passo(s), {self.segundos:.0f} s; {self.certos} deram "
            f"certo, {self.falhos} falharam.",
        ]
        if self.detalhe:
            linhas.append(f"Detalhe: {self.detalhe}")
        if self.passos:
            linhas.append("Passos (o mais recente por último):")
            linhas += [f"- {p}" for p in self.passos]
        if self.proximo:
            linhas.append(f"O próximo passo que você tinha proposto: {self.proximo}")
        if self.resposta_do_dono:
            linhas.append(f"O dono respondeu à sua pergunta: {self.resposta_do_dono}.")
        linhas.append(_instrucao(self.opcoes, self.bloco))
        return "\n".join(linhas)

    def em_poucas_palavras(self) -> str:
        """Para o card e a trilha: o motivo e os números, sem argumento nem resultado."""
        return (
            f"{self.motivo}: {self.passos_dados} passo(s), {self.certos} certo(s), "
            f"{self.falhos} falha(s), {self.segundos:.0f} s"
        )


def _instrucao(opcoes: Sequence[str], bloco: int) -> str:
    explicadas = {
        "continuar": f'"continuar" (diga em "passos" quantos, de 1 a {bloco}, e em "estrategia" '
        "o que vai fazer diferente)",
        "perguntar": '"perguntar" (em "texto", a pergunta ao dono, com as suas palavras: o que '
        "falta e o que você precisa dele; sem as palavras sim e não)",
        "encerrar": '"encerrar" (em "texto", o que você diz ao dono: o que ficou feito, o que '
        "faltou e por quê, só com o que as ferramentas confirmaram)",
    }
    escolhas = "; ".join(explicadas[o] for o in opcoes)
    return (
        "Pense no estado acima e decida você. Não peça ferramenta nesta rodada. Responda com UMA "
        'linha JSON: {"decisao": …, "passos": …, "estrategia": …, "texto": …}. '
        f"Decisões possíveis: {escolhas}. O texto é falado ao dono: uma ou duas frases, sem "
        "markdown, sem citar ferramenta."
    )


def notificacao(
    motivo: MotivoDoLimite,
    pedido: str,
    feitos: Sequence[ResultadoDeFerramenta],
    *,
    segundos: float,
    bloco: int,
    detalhe: str = "",
    proximo: str = "",
    opcoes: tuple[str, ...] = ("continuar", "perguntar", "encerrar"),
) -> NotificacaoDoLimite:
    linhas: list[str] = []
    for resultado in feitos[-PASSOS_NA_NOTIFICACAO:]:
        motivo_real = " ".join(resultado.motivo.split())[:CARACTERES_DO_MOTIVO]
        causa = f" [{resultado.causa}]" if resultado.causa else ""
        linha = f"{resultado.tool_id} → {resultado.status}{causa}"
        linhas.append(f"{linha}: {motivo_real}" if motivo_real else linha)
    return NotificacaoDoLimite(
        motivo=motivo,
        pedido=" ".join(pedido.split())[:200],
        passos=tuple(linhas),
        certos=sum(1 for r in feitos if r.status == "ok"),
        falhos=sum(1 for r in feitos if r.status != "ok"),
        passos_dados=len(feitos),
        segundos=segundos,
        bloco=bloco,
        detalhe=detalhe,
        proximo=proximo,
        opcoes=opcoes,
    )


@dataclass(frozen=True, slots=True)
class DecisaoNoLimite:
    acao: str
    passos: int = 0
    estrategia: str = ""
    texto: str = ""


_JSON: Final = re.compile(r"\{.*\}", re.S)


def ler_decisao(texto: str, opcoes: Sequence[str], bloco: int) -> DecisaoNoLimite:
    """A decisão que o motor escreveu. Sem JSON legível, o texto dele é o que ele quer dizer ao
    dono: encerrar com ele (se encerrar é opção). Decisão fora das opções vira a primeira que cabe:
    `continuar` sem vez pergunta, se houver texto, e senão encerra."""
    achado = _JSON.search(texto)
    dados: dict[str, object] = {}
    if achado is not None:
        try:
            lido = json.loads(achado.group(0))
        except ValueError:
            lido = None
        if isinstance(lido, dict):
            dados = lido
    acao = str(dados.get("decisao", "")).strip().casefold()
    fala = str(dados.get("texto", "") if dados else _JSON.sub("", texto)).strip()
    estrategia = str(dados.get("estrategia", "")).strip()
    try:
        passos = int(str(dados.get("passos", 0)))
    except ValueError:
        passos = 0
    passos = max(1, min(bloco, passos or bloco))
    if acao not in opcoes:
        acao = "perguntar" if fala and "perguntar" in opcoes and acao == "continuar" else ""
        acao = acao or ("encerrar" if "encerrar" in opcoes else opcoes[0])
    if acao == "perguntar" and not fala:
        acao = "encerrar" if "encerrar" in opcoes else acao
    return DecisaoNoLimite(acao, passos, estrategia, fala)
