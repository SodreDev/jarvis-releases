"""Contrato do microfone entre a `ui` e o `audio-io` (cartão F1-13).

**Por que não é evento do barramento.** A §3.2 fecha onze tipos de evento, e nenhum deles é
"abra o microfone": acrescentar um é emenda de SPEC, que é do dono (ADR). O PTT e o *kill
switch* usam o mesmo mecanismo que a pasta de sessão já usa para `sessao`, `pronto` e
`quadros-de-audio` — arquivo pequeno na pasta de execução, trocado por `Path.replace`
(atômico nos dois sistemas). O barramento continua carregando **decisão**; isto é **controle de
dispositivo**, e quem manda no dispositivo é o dono.

**A direção dos dois arquivos é o que faz o indicador não mentir:**

- `microfone-pedido.json` é o que o dono **pediu** — escrito pela `ui`, lido pelo `audio-io`;
- `microfone-estado.json` é o que a fonte **está fazendo** — escrito pelo `audio-io`, lido pela
  `ui`.

O indicador da `ui` lê **só o segundo**. Nunca o primeiro, nunca a sua própria intenção: é por
isso que ele não pode acender com a fonte fechada nem apagar com a fonte aberta. E `amostras`
conta a abertura **atual**, voltando a zero quando a fonte fecha — assim "indicador apagado"
e "zero amostra" são a mesma afirmação, do jeito que o cartão pede.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from jarvis.arquivos import LeituraOcupada, escrever_atomico, ler_texto

CORROMPIDO: Final[dict[str, Any]] = {}
"""Marcador de "o arquivo existe, deu para ler e o conteúdo não presta" — diferente de
ausente e diferente de ocupado."""

ARQUIVO_PEDIDO: Final = "microfone-pedido.json"
ARQUIVO_ESTADO: Final = "microfone-estado.json"


class PedidoCorrompido(ValueError):
    """O arquivo de pedido existe, deu para ler e não é um pedido.

    Não é ausência ("a `ui` não pediu nada"), não é disputa ("não deu para ler agora") e não é
    pichação ("modo que não existe", que é JSON válido). É byte estragado, e quem chama decide
    o que fazer com um tique de byte estragado — ver `ler_pedido`.
    """


class Modo(StrEnum):
    """Como o microfone deve se comportar. Escolha do dono, não do assistente."""

    ESCUTA = "escuta"
    """Escuta contínua: a fonte fica aberta e quem decide fala é o VAD (F1-05)."""

    PTT = "ptt"
    """*Push to talk*: a fonte abre enquanto a tecla está apertada, e só."""

    DESLIGADO = "desligado"
    """*Kill switch*: fonte fechada, playback silenciado. Nada que a UI peça reabre."""


@dataclass(frozen=True, slots=True)
class Pedido:
    """O que o dono pediu. `pressionado` só tem sentido no modo PTT."""

    modo: Modo = Modo.ESCUTA
    pressionado: bool = False

    @property
    def quer_fonte_aberta(self) -> bool:
        if self.modo is Modo.DESLIGADO:
            return False
        if self.modo is Modo.PTT:
            return self.pressionado
        return True

    def para_dict(self) -> dict[str, Any]:
        return {"modo": str(self.modo), "pressionado": self.pressionado}


@dataclass(frozen=True, slots=True)
class EstadoDaFonte:
    """O que a fonte **está** fazendo, medido no `audio-io`. É o que o indicador mostra."""

    aberta: bool = False
    amostras: int = 0
    """Amostras desta abertura. Fecha a fonte, volta a zero — o cartão cobra isso.

    É um **retrato**: o `audio-io` republica a cada 250 ms, e na hora em que `aberta`,
    `modo` ou `indisponivel` mudam. Então o número pode estar até 250 ms atrasado, mas o
    zero do fechamento **nunca** atrasa, que é o que o indicador precisa."""
    amostras_totais: int = 0
    device_id: str | None = None
    indisponivel: str | None = None
    """Frase do erro quando não há dispositivo para abrir (estado vazio útil da `ui`)."""
    modo: Modo = Modo.ESCUTA

    def para_dict(self) -> dict[str, Any]:
        return {
            "aberta": self.aberta,
            "amostras": self.amostras,
            "amostras_totais": self.amostras_totais,
            "device_id": self.device_id,
            "indisponivel": self.indisponivel,
            "modo": str(self.modo),
        }


def _escrever(caminho: Path, dados: dict[str, Any]) -> None:
    """Grava inteiro ou não grava (ver `jarvis.arquivos`).

    Sem a troca atômica, o leitor pega JSON pela metade exatamente quando o estado está
    mudando — que é o único momento em que ele é interessante.
    """
    escrever_atomico(caminho, json.dumps(dados, ensure_ascii=False))


def _ler(caminho: Path) -> dict[str, Any] | None:
    """`None` para ausente **ou** corrompido; `LeituraOcupada` sobe para quem chama decidir."""
    bruto = ler_texto(caminho)
    if bruto is None:
        return None
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        return CORROMPIDO
    return dados if isinstance(dados, dict) else CORROMPIDO


def escrever_pedido(raiz: Path, pedido: Pedido) -> None:
    _escrever(raiz / ARQUIVO_PEDIDO, pedido.para_dict())


def ler_pedido(raiz: Path) -> Pedido | None:
    """O pedido do dono, ou `None` quando não há pedido novo para aplicar.

    **Quatro** casos, e eles não são o mesmo:

    - **ausente**: a `ui` ainda não pediu nada → `None`, e quem chama segue com o que tinha;
    - **ocupado** (disputa de arquivo no Windows): também `None` — ruído de um instante não é
      ordem, e desligar o microfone por isso seria piscar na cara do dono;
    - **corrompido** (não é JSON, ou não é um mapa): levanta `PedidoCorrompido`, e **quem
      chama decide**. Byte estragado num tique é a mesma família do "ocupado", não uma ordem:
      meia escrita pega antes do `replace`, cache invalidado em VM ou overlayfs. O `audio-io`
      decide por teimosia (`ControleDoMicrofone`): mantém o pedido anterior e só desliga se a
      corrupção insistir;
    - **modo que não existe**, com JSON válido: `DESLIGADO` na primeira leitura. Isso não é
      glitch, é pichação — alguém escreveu um pedido inteiro e inválido —, e aí o padrão tem
      de ser o mais silencioso, não o mais útil.
    """
    try:
        dados = _ler(raiz / ARQUIVO_PEDIDO)
    except LeituraOcupada:
        return None
    if dados is None:
        return None
    if dados is CORROMPIDO:
        raise PedidoCorrompido(f"{raiz / ARQUIVO_PEDIDO} não é um pedido legível")
    try:
        modo = Modo(str(dados["modo"]))
    except (KeyError, ValueError):
        return Pedido(modo=Modo.DESLIGADO)
    return Pedido(modo=modo, pressionado=bool(dados.get("pressionado", False)))


def escrever_estado(raiz: Path, estado: EstadoDaFonte) -> None:
    _escrever(raiz / ARQUIVO_ESTADO, estado.para_dict())


def ler_estado(raiz: Path) -> EstadoDaFonte:
    """O estado da fonte. Sem arquivo (ou corrompido), o indicador fica **apagado**.

    Na dúvida, o indicador não acende: indicador que acende por falta de informação é
    exatamente o indicador que mente. Arquivo **ocupado** levanta `LeituraOcupada` para o
    painel reaproveitar o último estado em vez de piscar.
    """
    dados = _ler(raiz / ARQUIVO_ESTADO)
    if dados is None or dados is CORROMPIDO:
        return EstadoDaFonte()
    try:
        modo = Modo(str(dados.get("modo", Modo.ESCUTA)))
    except ValueError:
        modo = Modo.ESCUTA
    indisponivel = dados.get("indisponivel")
    device_id = dados.get("device_id")
    return EstadoDaFonte(
        aberta=bool(dados.get("aberta", False)),
        amostras=int(dados.get("amostras", 0)),
        amostras_totais=int(dados.get("amostras_totais", 0)),
        device_id=None if device_id is None else str(device_id),
        indisponivel=None if indisponivel is None else str(indisponivel),
        modo=modo,
    )
