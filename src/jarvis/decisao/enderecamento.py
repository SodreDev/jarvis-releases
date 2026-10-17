"""Detector de endereçamento: a fala transcrita é **para o Jarvis**? (ADR-0029)

Na escuta contínua (`escuta = "vad"`) todo trecho que o VAD abre vira pedido — inclusive o dono
falando sozinho, com outra pessoa ou a TV. O detector faz duas perguntas fechadas por fala,
numa única chamada ao classificador:

- `falando_com_o_jarvis` (noul): o falante espera que o assistente responda ou faça algo?
- `pedido` (escolha): `ignorar` · `resposta` · `sugestao` · `acao` — `ignorar` **primeiro**, porque
  o modelo puxa para a primeira opção e o erro barato é ignorar.

**Regra de ouro: na dúvida, não age e não interrompe.** Prazo estourado, serviço fora, resposta
fora do formato, probabilidade no meio — tudo vira "ignorar", com o motivo dito. O detector só é
consultado para uma fala **nova** com o Jarvis em repouso: nunca decide interromper o que o
Jarvis está dizendo (barge-in continua sendo do dono, com a barra ou a voz do VAD).

**Histerese.** Entrar na conversa exige `p ≥ entrar` (0,80); com a conversa em andamento (houve
fala endereçada há menos de `janela_de_conversa_s`) basta `p ≥ permanecer` (0,55) — "e a
segunda?" não repete "Jarvis". O meio-termo (`p` entre `recusar` e o limiar) não age: é "incerto",
contado à parte de "não era comigo".

**Privacidade.** O estado enviado é só a fala transcrita e dois sinais locais (se o Jarvis acabou
de perguntar algo; se a conversa está em andamento). Nada de memória, histórico, resultado de
ferramenta ou o que o Jarvis disse (D20: dado sensível nunca vai a nuvem).
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from jarvis.decisao.interface import (
    ClassificadorDeDecisao,
    DecisaoIndisponivel,
    DecisaoRecusada,
    Pergunta,
    PerguntaEscolha,
    PerguntaNoul,
    RespostaEscolha,
    RespostaNoul,
)
from jarvis.voz.interface import Cancelado, nunca_cancelado


class Intencao(StrEnum):
    IGNORAR = "ignorar"
    RESPOSTA = "resposta"
    SUGESTAO = "sugestao"
    ACAO = "acao"


class Motivo(StrEnum):
    ENDERECADA = "endereçada"
    NAO_ERA_COMIGO = "não era comigo"
    INCERTO = "incerto"
    SEM_INTENCAO = "sem pedido claro"
    FORA_DO_AR = "classificador fora"


PERGUNTAS: Final[dict[str, Pergunta]] = {
    "falando_com_o_jarvis": PerguntaNoul(
        instrucoes=(
            "A fala em `fala` foi dita por uma pessoa a um assistente de voz chamado Jarvis, "
            "esperando que ele responda, sugira ou faça algo."
        ),
        sim=(
            "A pessoa se dirige ao assistente: pede algo, faz uma pergunta que ele pode responder, "
            "dá uma ordem ou responde ao que o assistente acabou de perguntar."
        ),
        nao=(
            "A pessoa fala sozinha, pensa em voz alta, conversa com outra pessoa, comenta algo "
            "para si ou é som de TV, vídeo ou música."
        ),
    ),
    "pedido": PerguntaEscolha(
        instrucoes=(
            "O que a fala em `fala` pede ao assistente de voz Jarvis? Se não pede nada a ele, "
            "escolha ignorar."
        ),
        opcoes={
            "ignorar": (
                "Não é um pedido ao assistente: fala sozinha, conversa com outra pessoa, "
                "comentário, TV ou ruído."
            ),
            "resposta": "Quer uma informação, explicação ou resposta; ou apenas conversar.",
            "sugestao": "Pede opinião, recomendação, ideia ou escolha entre alternativas.",
            "acao": (
                "Pede que o assistente faça algo no computador: abrir, criar, mudar, tocar, "
                "procurar, anotar, lembrar."
            ),
        },
    ),
}


@dataclass(frozen=True, slots=True)
class Limiares:
    entrar: float = 0.80
    """`p(falando com o Jarvis)` mínima para **começar** uma conversa."""
    permanecer: float = 0.55
    """A mesma, com a conversa em andamento (histerese)."""
    recusar: float = 0.30
    """Abaixo disto é "não era comigo"; entre isto e o limiar vigente é "incerto"."""
    escolha_minima: float = 0.50
    """Probabilidade mínima da intenção escolhida: abaixo, o pedido não está claro."""
    janela_de_conversa_s: float = 20.0
    prazo_s: float = 1.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.recusar < self.permanecer <= self.entrar <= 1.0:
            raise ValueError("limiares precisam de 0 ≤ recusar < permanecer ≤ entrar ≤ 1")


@dataclass(frozen=True, slots=True)
class Decisao:
    agir: bool
    motivo: Motivo
    intencao: Intencao = Intencao.IGNORAR
    p_com_o_jarvis: float | None = None
    ms: float = 0.0
    detalhe: str = ""

    def frase(self) -> str:
        """Uma linha para a tela. **Nunca** repete a fala."""
        p = "" if self.p_com_o_jarvis is None else f" · p={self.p_com_o_jarvis:.2f}"
        quem = f"{self.intencao.value}" if self.agir else self.motivo.value
        return f"endereçamento: {quem}{p} · {self.ms:.0f} ms"


@dataclass(slots=True)
class DetectorDeEnderecamento:
    classificador: ClassificadorDeDecisao
    limiares: Limiares = field(default_factory=Limiares)
    relogio: Callable[[], float] = time.monotonic
    consultas: int = 0
    enderecadas: int = 0
    nao_era_comigo: int = 0
    incertas: int = 0
    falhas: int = 0
    latencias_ms: list[float] = field(default_factory=list)
    _ultima_enderecada: float | None = field(default=None, repr=False)

    @property
    def em_conversa(self) -> bool:
        return (
            self._ultima_enderecada is not None
            and self.relogio() - self._ultima_enderecada <= self.limiares.janela_de_conversa_s
        )

    def avaliar(
        self,
        fala: str,
        *,
        jarvis_perguntou: bool = False,
        cancelado: Cancelado = nunca_cancelado,
    ) -> Decisao:
        em_conversa = self.em_conversa
        estado = {
            "fala": fala.strip(),
            "o_assistente_acabou_de_fazer_uma_pergunta": "sim" if jarvis_perguntou else "não",
            "ja_estavamos_conversando": "sim" if em_conversa else "não",
        }
        comeco = time.monotonic()
        self.consultas += 1
        try:
            respostas = self.classificador.decidir(estado, PERGUNTAS, cancelado=cancelado)
            noul = respostas["falando_com_o_jarvis"]
            escolha = respostas["pedido"]
            if not isinstance(noul, RespostaNoul) or not isinstance(escolha, RespostaEscolha):
                raise DecisaoIndisponivel("resposta fora do formato: tipos trocados")
        except (DecisaoIndisponivel, KeyError) as erro:
            self.falhas += 1
            tipo = "recusado" if isinstance(erro, DecisaoRecusada) else "indisponível"
            return Decisao(
                agir=False,
                motivo=Motivo.FORA_DO_AR,
                ms=(time.monotonic() - comeco) * 1000.0,
                detalhe=f"{tipo}: {erro}",
            )
        ms = (time.monotonic() - comeco) * 1000.0
        self.latencias_ms.append(ms)
        p = noul.probabilidade
        minimo = self.limiares.permanecer if em_conversa else self.limiares.entrar
        if p >= minimo:
            intencao = Intencao(escolha.escolha)
            if intencao is Intencao.IGNORAR:
                self.nao_era_comigo += 1
                return Decisao(False, Motivo.NAO_ERA_COMIGO, intencao, p, ms)
            if escolha.probabilidade_da_escolha < self.limiares.escolha_minima:
                self.incertas += 1
                return Decisao(False, Motivo.SEM_INTENCAO, intencao, p, ms)
            self.enderecadas += 1
            self._ultima_enderecada = self.relogio()
            return Decisao(True, Motivo.ENDERECADA, intencao, p, ms)
        if p <= self.limiares.recusar:
            self.nao_era_comigo += 1
            return Decisao(False, Motivo.NAO_ERA_COMIGO, Intencao.IGNORAR, p, ms)
        self.incertas += 1
        return Decisao(False, Motivo.INCERTO, Intencao.IGNORAR, p, ms)

    def resumo(self) -> str:
        if not self.latencias_ms:
            return f"endereçamento: {self.consultas} consulta(s), {self.falhas} falha(s)"
        ordenadas = sorted(self.latencias_ms)
        p95 = ordenadas[min(len(ordenadas) - 1, int(0.95 * len(ordenadas)))]
        return (
            f"endereçamento: {self.consultas} consulta(s) · endereçadas {self.enderecadas} · "
            f"não era comigo {self.nao_era_comigo} · incertas {self.incertas} · "
            f"falhas {self.falhas} · latência p50 {statistics.median(ordenadas):.0f} ms, "
            f"p95 {p95:.0f} ms"
        )
