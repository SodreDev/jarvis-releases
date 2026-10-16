"""Sem rede: cai para PTT e **diz** isso (cartão F1-14).

"Degradar é obrigatório; degradar em silêncio é defeito." Então a perda de rede é detectada
**no adaptador** — no objeto que faz a chamada remota —, nunca mexendo no firewall da máquina e
nunca esperando o `timeout` que o SDK de alguém escolheu. Três regras, que são as do projeto
aplicadas à rede:

1. **O prazo é nosso.** `chamar` passa o prazo restante para quem faz a chamada e **mede** o
   que levou. Resposta que chegou depois do prazo é tratada como falha, igual ao orçamento
   vencido do S1 (F1-08): informação velha não decide nada.
2. **Nada pendurado** (§3.3 regra 5). Pedido que caiu é **descartado**, com o `call_id`
   registrado; quando a rede volta, ele **não** é refeito. Repetir pedido velho é o defeito que
   a regra 5 existe para proibir — e aqui a estrutura impede: `chamar` recusa um `call_id` que
   está na lista de descartados, sem nem olhar a sonda.
3. **O aviso é uma frase, e sai uma vez.** `reservar_aviso_por_voz` devolve a frase na primeira
   chamada e `None` nas seguintes, e isso fica **no arquivo** de degradação — então nem reiniciar
   o processo faz o Jarvis repetir no ouvido do dono.

A degradação fica num arquivo da pasta de sessão (`degradacao.json`), pelo mesmo motivo do
microfone (`jarvis.microfone`): os onze tipos de evento da §3.2 são fechados, e "o serviço caiu"
não é um deles. Quem lê é a `ui` — que desliga a escuta contínua, liga o PTT e mostra a frase.

**Dois escritores, uma trava.** O arquivo é escrito pelo adaptador (aqui) e por quem fala o
aviso (`reservar_aviso_por_voz`, no `agentd`), e os dois fazem ler → decidir → escrever. Troca
atômica resolve bytes pela metade, não perda de atualização: sem trava, A lê, B lê, A escreve e
B escreve por cima — o `call_id` que A acrescentou some, e pedido que caiu volta a ser
refeito, que é o que a regra 5 proíbe. Por isso cada par ler→escrever acontece dentro de
`tranca_exclusiva` (`degradacao.json.lock`).
"""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, TypeVar, runtime_checkable

from jarvis.ambiente import VARIAVEL_CI, ambiente_ou_os, em_ci, verdadeiro
from jarvis.arquivos import (
    LeituraOcupada,
    escrever_atomico,
    ler_texto,
    tranca_exclusiva,
)

ARQUIVO_DEGRADACAO: Final = "degradacao.json"
PRAZO_PADRAO_S: Final = 2.0
"""Prazo de uma chamada remota. Não é SLO: é o teto que impede `timeout` herdado de minutos."""
PRAZO_DA_SONDA_S: Final = 0.3
"""A sonda só responde "dá para falar com o serviço?" — esperar mais que isso é travar a UI."""
VARIAVEL_BACKEND: Final = "JARVIS_REDE_BACKEND"
VARIAVEL_DISPONIVEL: Final = "JARVIS_REDE_DISPONIVEL"
VARIAVEL_ARQUIVO: Final = "JARVIS_REDE_ARQUIVO"

T = TypeVar("T")


class ErroDeRede(RuntimeError):
    """Base dos erros de rede do projeto."""


class ServicoIndisponivel(ErroDeRede):
    """O serviço remoto não respondeu, ou respondeu fora do prazo."""


class RedeProibidaEmCI(ErroDeRede):
    """Aceite (d) do F1-14: com `CI=1` ninguém abre socket externo, nem por acidente."""


class Backend(StrEnum):
    INJETADA = "injetada"
    """Sonda de teste: o estado vem de variável ou de arquivo (outro processo derruba a rede)."""

    SOCKET = "socket"
    """Produção: `connect` com prazo curto. Recusa rodar sob `CI=1`."""


@runtime_checkable
class Sonda(Protocol):
    """ "Dá para falar com o serviço agora?" — e nada mais que isso."""

    nome: str

    def disponivel(self) -> bool: ...


@dataclass(slots=True)
class SondaInjetada:
    """A rede é o que o teste disser. Com `arquivo`, outro processo derruba e levanta."""

    ligada: bool = True
    arquivo: Path | None = None
    nome: str = "injetada"
    consultas: int = 0

    def disponivel(self) -> bool:
        self.consultas += 1
        if self.arquivo is None:
            return self.ligada
        try:
            return verdadeiro(ler_texto(self.arquivo))
        except LeituraOcupada:
            return self.ligada  # disputa de arquivo não é queda de rede


@dataclass(slots=True)
class SondaDeSocket:
    """Sonda de produção: um `connect` com prazo curto, e **nunca** sob CI.

    A proibição mora aqui, no código de produção, e não só na fixture — exatamente como
    `proibir_dispositivo_em_ci` faz com a placa de som (F1-01). É o que faz o aceite (d) ser
    estrutural: a suíte não tem como abrir socket externo por descuido.
    """

    host: str
    porta: int
    prazo_s: float = PRAZO_DA_SONDA_S
    nome: str = "socket"
    ambiente: Mapping[str, str] | None = None

    def disponivel(self) -> bool:
        if em_ci(self.ambiente):
            raise RedeProibidaEmCI(
                f"{VARIAVEL_CI} está ligado: a suíte não abre socket externo "
                f"(use {VARIAVEL_BACKEND}={Backend.INJETADA})"
            )
        try:
            with socket.create_connection((self.host, self.porta), timeout=self.prazo_s):
                return True
        except OSError:
            return False


def sonda_do_ambiente(
    *,
    host: str = "",
    porta: int = 0,
    ambiente: Mapping[str, str] | None = None,
) -> Sonda:
    """A sonda que o ambiente pediu; valor desconhecido é erro, não padrão silencioso."""
    fonte = ambiente_ou_os(ambiente)
    bruto = fonte.get(VARIAVEL_BACKEND, "").strip().lower()
    backend = Backend.INJETADA if not bruto else None
    if backend is None:
        try:
            backend = Backend(bruto)
        except ValueError:
            validos = ", ".join(b.value for b in Backend)
            raise ValueError(
                f"{VARIAVEL_BACKEND}={bruto!r} não existe; use um de: {validos}"
            ) from None
    if backend is Backend.SOCKET:
        return SondaDeSocket(host=host, porta=porta, ambiente=ambiente)
    caminho = fonte.get(VARIAVEL_ARQUIVO, "").strip()
    return SondaInjetada(
        ligada=verdadeiro(fonte.get(VARIAVEL_DISPONIVEL, "1")),
        arquivo=Path(caminho) if caminho else None,
    )


@dataclass(frozen=True, slots=True)
class Degradacao:
    """O que está degradado, em dados. `frase` é **uma** frase, a que a `ui` mostra."""

    ativa: bool = False
    servico: str = ""
    frase: str = ""
    epoch: int = 0
    avisado_por_voz: bool = False
    descartados: tuple[str, ...] = ()
    """`call_id`s que caíram com a rede. Ficam aqui para **nunca** serem refeitos (regra 5)."""

    def para_dict(self) -> dict[str, Any]:
        return {
            "ativa": self.ativa,
            "servico": self.servico,
            "frase": self.frase,
            "epoch": self.epoch,
            "avisado_por_voz": self.avisado_por_voz,
            "descartados": list(self.descartados),
        }


def frase_de_queda(servico: str) -> str:
    """Uma frase, dizendo o que deixou de funcionar e o que ainda funciona. Aceite (b)."""
    return (
        f"Perdi a conexão com {servico}, então vou continuar ouvindo e respondendo aqui no "
        "computador enquanto isso, só por botão de falar."
    )


def frase_de_volta(servico: str) -> str:
    """A volta também é declarada — e sem ressuscitar nada (aceite (c))."""
    return (
        f"A conexão com {servico} voltou, e não refiz nada do que ficou pela metade: "
        "pode pedir de novo quando quiser."
    )


def escrever_degradacao(raiz: Path, degradacao: Degradacao) -> None:
    """Troca atômica, com o pid no temporário: este arquivo tem **dois** escritores."""
    escrever_atomico(
        raiz / ARQUIVO_DEGRADACAO, json.dumps(degradacao.para_dict(), ensure_ascii=False)
    )


def ler_degradacao(raiz: Path) -> Degradacao:
    """Sem arquivo (ou ilegível), nada está degradado: a `ui` não inventa aviso.

    Arquivo **ocupado** (disputa no Windows) também conta como "nada a dizer agora": quem
    chama mantém o que tinha, em vez de anunciar uma queda que ninguém observou.
    """
    try:
        bruto = ler_texto(raiz / ARQUIVO_DEGRADACAO)
    except LeituraOcupada:
        return Degradacao()
    if bruto is None:
        return Degradacao()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        return Degradacao()
    if not isinstance(dados, dict):
        return Degradacao()
    descartados = dados.get("descartados", [])
    return Degradacao(
        ativa=bool(dados.get("ativa", False)),
        servico=str(dados.get("servico", "")),
        frase=str(dados.get("frase", "")),
        epoch=int(dados.get("epoch", 0)),
        avisado_por_voz=bool(dados.get("avisado_por_voz", False)),
        descartados=tuple(str(c) for c in descartados) if isinstance(descartados, list) else (),
    )


def reservar_aviso_por_voz(raiz: Path) -> str | None:
    """A frase para dizer em voz alta, **uma vez**. Depois disso, `None`.

    A reserva é gravada antes de alguém falar: se o processo morrer entre reservar e sintetizar,
    o dono perde um aviso — e perder um aviso é melhor que ouvir o mesmo aviso em loop, que é o
    aceite (e) do cartão. Ler e reservar acontecem **dentro da trava**: é o que faz "uma vez"
    valer com dois processos, e não só com um.
    """
    with tranca_exclusiva(raiz / ARQUIVO_DEGRADACAO):
        degradacao = ler_degradacao(raiz)
        if not degradacao.ativa or degradacao.avisado_por_voz or not degradacao.frase:
            return None
        escrever_degradacao(raiz, replace(degradacao, avisado_por_voz=True))
        return degradacao.frase


@dataclass(slots=True)
class AdaptadorRemoto:
    """Uma chamada remota com prazo nosso, degradação declarada e nada pendurado."""

    servico: str
    raiz: Path
    sonda: Sonda
    prazo_s: float = PRAZO_PADRAO_S
    agora: Callable[[], float] = time.monotonic
    chamadas: int = 0
    recusas_por_descarte: int = 0
    _degradacao: Degradacao = field(default_factory=Degradacao)

    def __post_init__(self) -> None:
        self._degradacao = ler_degradacao(self.raiz)

    @property
    def degradacao(self) -> Degradacao:
        return self._degradacao

    @property
    def degradado(self) -> bool:
        return self._degradacao.ativa

    def chamar(self, fazer: Callable[[float], T], *, call_id: str, epoch: int = 0) -> T | None:
        """Faz a chamada remota, ou declara a degradação e devolve `None`.

        `fazer` recebe o **prazo restante** em segundos: é assim que não existe `timeout`
        herdado — quem chama o serviço recebe o nosso prazo, não o padrão do SDK.
        """
        if call_id in self._degradacao.descartados:
            # Regra 5: pedido que caiu não volta. Nem sendo pedido de novo pelo mesmo id.
            self.recusas_por_descarte += 1
            return None
        if not self.sonda.disponivel():
            self._cair(call_id=call_id, epoch=epoch)
            return None
        comeco = self.agora()
        self.chamadas += 1
        try:
            resultado = fazer(self.prazo_s)
        except (ErroDeRede, OSError, TimeoutError):
            self._cair(call_id=call_id, epoch=epoch)
            return None
        if self.agora() - comeco > self.prazo_s:
            # Chegou, mas fora do prazo: é informação velha, e o serviço não está servindo.
            self._cair(call_id=call_id, epoch=epoch)
            return None
        self._voltar()
        return resultado

    def conferir(self, *, epoch: int = 0) -> Degradacao:
        """Pergunta à sonda sem fazer chamada — é o que a volta da rede precisa."""
        if self.sonda.disponivel():
            self._voltar()
        else:
            self._cair(call_id=None, epoch=epoch)
        return self._degradacao

    def _no_disco(self) -> Degradacao:
        """O arquivo é a verdade, e a cópia em memória é só cache.

        **Isto é correção de um defeito que o aceite (e) pegou.** O arquivo tem dois
        escritores: este adaptador e quem fala o aviso (`reservar_aviso_por_voz`, no `agentd`).
        Enquanto `_cair` escrevia a partir da cópia em memória, cada nova queda apagava o
        `avisado_por_voz` que o `agentd` tinha acabado de gravar — e o Jarvis repetia o mesmo
        aviso no ouvido do dono, uma vez por chamada que caía. Cinquenta chamadas, cinquenta
        avisos. Com a leitura antes da escrita, o episódio avisa uma vez.
        """
        do_disco = ler_degradacao(self.raiz)
        descartados = tuple(dict.fromkeys((*do_disco.descartados, *self._degradacao.descartados)))
        return replace(do_disco, descartados=descartados)

    def _cair(self, *, call_id: str | None, epoch: int) -> None:
        # A trava abraça o par ler→escrever: sem ela, o `call_id` que o outro processo
        # acrescentou agora é sobrescrito, e a regra 5 passa a depender de sorte.
        with tranca_exclusiva(self.raiz / ARQUIVO_DEGRADACAO):
            atual = self._no_disco()
            descartados = atual.descartados
            if call_id is not None and call_id not in descartados:
                descartados = (*descartados, call_id)
            self._degradacao = Degradacao(
                ativa=True,
                servico=self.servico,
                frase=frase_de_queda(self.servico),
                epoch=epoch or atual.epoch,
                # O aviso por voz já dado continua dado: cair de novo no mesmo episódio não
                # devolve a frase para o ouvido do dono (aceite (e)).
                avisado_por_voz=atual.ativa and atual.avisado_por_voz,
                descartados=descartados,
            )
            escrever_degradacao(self.raiz, self._degradacao)

    def _voltar(self) -> None:
        with tranca_exclusiva(self.raiz / ARQUIVO_DEGRADACAO):
            atual = self._no_disco()
            if not atual.ativa and not self._degradacao.ativa:
                return
            # A lista de descartados **sobrevive** à volta: é ela que garante que nada velho
            # ressuscita (aceite (c)).
            self._degradacao = Degradacao(
                ativa=False,
                servico=self.servico,
                frase=frase_de_volta(self.servico),
                epoch=atual.epoch,
                avisado_por_voz=False,
                descartados=atual.descartados,
            )
            escrever_degradacao(self.raiz, self._degradacao)
