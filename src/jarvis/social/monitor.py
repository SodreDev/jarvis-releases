"""O monitor das redes sociais (ADR-0060), somente leitura.

Duas peças:

* `EstadoDoMonitor` — puro, sem rede nem fio: recebe o que a página informou (`EstadoDaPagina`,
  vindo do evento `social` da extensão) e decide o estado de cada rede e quando avisar o dono.
  Avisa quando a contagem de não lidas **sobe**; quando cai (o dono leu), só guarda a nova base.
* `MonitorSocial` — o fio: assina os eventos do host do navegador preferido, pede à extensão a
  aba de fundo de cada rede ligada (`social.abrir`, reusa a que já existe) e entrega cada evento
  ao estado. Sem rede ligada, não assina nada e não abre nada.

O monitor nunca clica, digita nem rola: os únicos pedidos que ele faz são `social.abrir` e
`social.estado`. Os nomes que chegam da página são de terceiros e já vêm limpos e cortados pela
extensão; o protocolo valida de novo (`jarvis.navegador.protocolo.validar_evento`)."""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

from jarvis.politica.injecao import examinar
from jarvis.social.config import ConfiguracaoSocial
from jarvis.social.redes import IDS, rede

MAXIMO_DE_NOTIFICACOES: Final = 5
"""Por rede, no cartão da aba: as últimas cinco."""
NOMES_NO_AVISO: Final = 3
SEM_NOTICIA_S: Final = 90.0
"""Aba aberta e nenhum evento em 90 s: a extensão é a de antes (sem `social.js`) ou a aba
foi descartada pelo navegador."""
REABRIR_S: Final = 120.0
"""De quanto em quanto pedir de novo a aba de uma rede que ficou sem notícia."""
INTERVALO_S: Final = 2.0


class EventoInvalido(ValueError):
    """O evento `social` não cabe no contrato."""


@dataclass(frozen=True, slots=True)
class ConversaNaoLida:
    nome: str
    nao_lidas: int


@dataclass(frozen=True, slots=True)
class EstadoDaPagina:
    rede: str
    logado: bool
    nao_lidas: int
    conversas: tuple[ConversaNaoLida, ...] = ()
    formato: str = "conhecido"
    alerta: str = ""
    """Sinal de alerta que a página mostra (captcha, verificação, conta limitada…)."""

    @classmethod
    def do_evento(cls, evento: Mapping[str, Any]) -> EstadoDaPagina:
        """Do evento já validado pelo protocolo (`validar_evento`)."""
        try:
            return cls(
                rede=str(evento["rede"]),
                logado=bool(evento["logado"]),
                nao_lidas=int(evento["naoLidas"]),
                conversas=tuple(
                    ConversaNaoLida(str(c["nome"]), int(c["naoLidas"]))
                    for c in evento.get("conversas", [])
                ),
                formato=str(evento.get("formato", "conhecido")),
                alerta=str(evento.get("alerta", "")),
            )
        except (KeyError, TypeError, ValueError) as erro:
            raise EventoInvalido(f"evento social fora do contrato: {erro}") from None


@dataclass(frozen=True, slots=True)
class Notificacao:
    rede: str
    texto: str
    momento: float

    @property
    def hora(self) -> str:
        return datetime.fromtimestamp(self.momento).strftime("%H:%M")

    @property
    def nome_da_rede(self) -> str:
        return rede(self.rede).nome

    def para_a_tela(self) -> dict[str, str]:
        return {"hora": self.hora, "texto": self.texto}


ESTADOS: Final[dict[str, str]] = {
    "desligada": "desligada: o Jarvis não abre nem lê esta rede",
    "sem_extensao": "sem o navegador com a extensão do Jarvis aberto — abra o navegador",
    "abrindo": "abrindo a aba em segundo plano na sua janela…",
    "sem_noticia": "a aba não deu notícia: recarregue a extensão do Jarvis e a aba da rede",
    "esperando_login": "faça login nesta rede no seu navegador: o Jarvis não digita senha",
    "formato_desconhecido": "a página mudou e o Jarvis não reconhece o contador desta rede",
    "conectada": "conectada",
    "alerta": "sinal de alerta na página: envio pausado por 24 h — confira a aba você mesmo",
}
ALERTAS_DITOS: Final[dict[str, str]] = {
    "captcha": "a página pediu captcha",
    "verificacao": "a página pediu verificação",
    "limitada": "a página diz que a conta está limitada ou bloqueada",
    "atividade_incomum": "a página fala de atividade incomum",
    "logout": "a sessão caiu sem você sair",
    "elementos_sumiram": "a página mudou de repente",
}
"""Docs/redes-sociais-riscos.md §6: cada um pausa todo envio da rede por 24 h."""


@dataclass(slots=True)
class _DaRede:
    estado: str = "desligada"
    nao_lidas: int = 0
    base: int = 0
    """Até onde o dono já foi avisado: só a subida acima disto vira notificação."""
    conversas: tuple[ConversaNaoLida, ...] = ()
    alerta: str = ""
    """O último sinal de alerta dito ao dono (não repete o mesmo)."""
    pedida_em: float | None = None
    noticia_em: float | None = None
    notificacoes: deque[Notificacao] = field(
        default_factory=lambda: deque(maxlen=MAXIMO_DE_NOTIFICACOES)
    )


class EstadoDoMonitor:
    """O estado de cada rede e a regra de avisar. Seguro entre fios (uma trava)."""

    def __init__(self, relogio: Callable[[], float] = time.time) -> None:
        self._relogio = relogio
        self._trava = threading.Lock()
        self._redes: dict[str, _DaRede] = {r: _DaRede() for r in IDS}

    def ajustar(self, configuracao: ConfiguracaoSocial) -> None:
        """Rede desligada volta a «desligada» e esquece a base; ligada sem notícia, «abrindo»."""
        with self._trava:
            for identificador, da_rede in self._redes.items():
                if not configuracao.ajuste(identificador).monitorar:
                    self._redes[identificador] = _DaRede(notificacoes=da_rede.notificacoes)
                elif da_rede.estado == "desligada":
                    da_rede.estado = "abrindo"

    def marcar(self, identificador: str, estado: str) -> None:
        if estado not in ESTADOS:
            raise ValueError(f"estado desconhecido {estado!r}")
        with self._trava:
            da_rede = self._redes[identificador]
            if da_rede.estado != "desligada":
                da_rede.estado = estado

    def pedida(self, identificador: str) -> None:
        with self._trava:
            self._redes[identificador].pedida_em = self._relogio()

    def precisa_abrir(self, identificador: str) -> bool:
        """Nunca pedida, ou pedida há muito tempo sem notícia."""
        agora = self._relogio()
        with self._trava:
            da_rede = self._redes[identificador]
            if da_rede.pedida_em is None:
                return True
            ultima = max(da_rede.pedida_em, da_rede.noticia_em or 0.0)
            return agora - ultima >= REABRIR_S

    def conferir_noticia(self) -> None:
        """Pedida e muda há `SEM_NOTICIA_S`: diz que a aba não deu notícia."""
        agora = self._relogio()
        with self._trava:
            for da_rede in self._redes.values():
                if (
                    da_rede.estado == "abrindo"
                    and da_rede.pedida_em is not None
                    and da_rede.noticia_em is None
                    and agora - da_rede.pedida_em >= SEM_NOTICIA_S
                ):
                    da_rede.estado = "sem_noticia"

    def anotar(self, identificador: str, texto: str) -> Notificacao:
        """Uma notificação que não veio da página (o resultado de uma resposta no modo ausente)."""
        aviso = Notificacao(identificador, texto, self._relogio())
        with self._trava:
            self._redes[identificador].notificacoes.appendleft(aviso)
        return aviso

    def alerta(self, identificador: str) -> str:
        with self._trava:
            return self._redes[identificador].alerta

    def receber(self, pagina: EstadoDaPagina, *, notificar: bool) -> Notificacao | None:
        """O que a página informou. Devolve a notificação a dar ao dono: a contagem subiu, ou
        um sinal de alerta novo (este sempre, mesmo com «não avisa»: é o que para o envio)."""
        agora = self._relogio()
        with self._trava:
            da_rede = self._redes[pagina.rede]
            if da_rede.estado == "desligada":
                return None  # evento de rede que o dono não ligou: ignorado
            alerta = pagina.alerta
            if not alerta and da_rede.estado == "conectada":
                # Transições que também são sinal (§6): a sessão caiu, ou a página que funcionava
                # perdeu de repente os elementos que o canário confere.
                if pagina.formato != "conhecido":
                    alerta = "elementos_sumiram"
                elif not pagina.logado:
                    alerta = "logout"
            da_rede.noticia_em = agora
            if alerta in ALERTAS_DITOS:
                da_rede.estado = "alerta"
                if alerta == da_rede.alerta:
                    return None
                da_rede.alerta = alerta
                aviso = Notificacao(
                    pagina.rede,
                    f"{rede(pagina.rede).nome}: sinal de alerta — {ALERTAS_DITOS[alerta]}. "
                    "O Jarvis parou o envio desta rede por 24 h; confira a aba você mesmo.",
                    agora,
                )
                da_rede.notificacoes.appendleft(aviso)
                return aviso
            # O sinal de transição continua até a página voltar ao normal e logada.
            if (
                da_rede.estado == "alerta"
                and da_rede.alerta in ("logout", "elementos_sumiram")
                and (pagina.formato != "conhecido" or not pagina.logado)
            ):
                return None
            da_rede.alerta = ""
            if pagina.formato != "conhecido":
                da_rede.estado = "formato_desconhecido"
                return None
            if not pagina.logado:
                da_rede.estado = "esperando_login"
                return None
            da_rede.estado = "conectada"
            da_rede.nao_lidas = pagina.nao_lidas
            da_rede.conversas = pagina.conversas
            if pagina.nao_lidas <= da_rede.base:
                da_rede.base = pagina.nao_lidas  # o dono leu: a base desce sem aviso
                return None
            novas = pagina.nao_lidas - da_rede.base
            da_rede.base = pagina.nao_lidas
            if not notificar:
                return None
            aviso = Notificacao(pagina.rede, _texto(pagina, novas), agora)
            da_rede.notificacoes.appendleft(aviso)
            return aviso

    def para_a_tela(self, identificador: str) -> dict[str, Any]:
        with self._trava:
            da_rede = self._redes[identificador]
            frase = ESTADOS[da_rede.estado]
            if da_rede.estado == "alerta" and da_rede.alerta in ALERTAS_DITOS:
                frase = f"{ALERTAS_DITOS[da_rede.alerta]} — {frase}"
            if da_rede.estado == "conectada":
                frase = (
                    f"conectada — {da_rede.nao_lidas} não lida(s)"
                    if da_rede.nao_lidas
                    else "conectada — nada novo"
                )
            return {
                "estado": da_rede.estado,
                "alerta": da_rede.alerta,
                "frase": frase,
                "naoLidas": da_rede.nao_lidas,
                "notificacoes": [n.para_a_tela() for n in da_rede.notificacoes],
            }


NOME_SUSPEITO: Final = "uma conversa com nome suspeito"
"""No lugar do nome que tenta dar ordens ao Jarvis (ADR-0065): o aviso vai à voz e ao modelo."""


def _nome_seguro(nome: str) -> str:
    """O nome da conversa é de terceiros: o que tenta dar ordens não entra no aviso."""
    return NOME_SUSPEITO if examinar(nome) is not None else nome


def _texto(pagina: EstadoDaPagina, novas: int) -> str:
    """«2 mensagens novas — Ana (1), Bruno (1)». Só nomes e contagem: nunca o texto da mensagem."""
    nome = rede(pagina.rede).nome
    plural = "mensagem nova" if novas == 1 else "mensagens novas"
    quem = ", ".join(
        f"{_nome_seguro(c.nome)} ({c.nao_lidas})" for c in pagina.conversas[:NOMES_NO_AVISO]
    )
    resto = len(pagina.conversas) - NOMES_NO_AVISO
    if resto > 0:
        quem += f" e mais {resto}"
    return f"{nome}: {novas} {plural}" + (f" — {quem}" if quem else "")


# --- o fio ------------------------------------------------------------------------------------
class Assinatura(Protocol):
    def esperar(self, segundos: float) -> list[dict[str, Any]]: ...

    def fechar(self) -> None: ...


class Ponte(Protocol):
    """O pedaço do transporte do navegador que o monitor usa (`TransporteUnix` e o falso)."""

    def assinar(self, navegador: str = "") -> Assinatura: ...

    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]: ...


class MonitorSocial:
    """Assina os eventos do host e mantém uma aba de fundo por rede ligada."""

    def __init__(
        self,
        ponte: Ponte,
        *,
        configuracao: Callable[[], ConfiguracaoSocial],
        familia: Callable[[], str],
        ao_notificar: Callable[[Notificacao], None],
        ao_mudar: Callable[[], None],
        ao_alerta: Callable[[str, str], None] | None = None,
        ao_estado: Callable[[EstadoDaPagina], None] | None = None,
        estado: EstadoDoMonitor | None = None,
        intervalo_s: float = INTERVALO_S,
    ) -> None:
        self._ponte = ponte
        self._configuracao = configuracao
        self._familia = familia
        """A família do host a usar: o navegador preferido das redes, ou o principal."""
        self._ao_notificar = ao_notificar
        self._ao_mudar = ao_mudar
        self._ao_alerta = ao_alerta
        self.ao_estado = ao_estado
        """Cada estado de página recebido (a resposta no modo ausente, fatia D, ouve aqui)."""
        """(rede, alerta): o envio pausa a rede por 24 h (fatia D)."""
        self.estado = estado or EstadoDoMonitor()
        self._intervalo_s = intervalo_s
        self._acordar = threading.Event()
        self._parar = threading.Event()
        self._fio: threading.Thread | None = None

    def iniciar(self) -> None:
        self.estado.ajustar(self._configuracao())
        if self._fio is None or not self._fio.is_alive():
            self._parar.clear()
            self._fio = threading.Thread(target=self._rodar, name="jarvis-redes", daemon=True)
            self._fio.start()

    def atualizar(self) -> None:
        """O dono mexeu na aba: vale no próximo tique, sem reiniciar."""
        self.estado.ajustar(self._configuracao())
        self._acordar.set()
        self._ao_mudar()

    def parar(self, espera_s: float = 2.0) -> None:
        self._parar.set()
        self._acordar.set()
        if self._fio is not None:
            self._fio.join(espera_s)

    def _rodar(self) -> None:
        assinatura: Assinatura | None = None
        try:
            while not self._parar.is_set():
                ligadas = self._configuracao().monitoradas()
                if not ligadas:
                    if assinatura is not None:
                        with contextlib.suppress(Exception):
                            assinatura.fechar()
                        assinatura = None
                    self._acordar.wait(self._intervalo_s * 5)
                    self._acordar.clear()
                    continue
                assinatura = self._tique(assinatura, ligadas)
        finally:
            if assinatura is not None:
                with contextlib.suppress(Exception):
                    assinatura.fechar()

    def _tique(self, assinatura: Assinatura | None, ligadas: Sequence[str]) -> Assinatura | None:
        familia = self._familia()
        if assinatura is None:
            try:
                assinatura = self._ponte.assinar(familia)
            except OSError:
                assinatura = None
            except Exception:  # NavegadorIndisponivel e afins: tenta depois
                assinatura = None
            if assinatura is None:
                for identificador in ligadas:
                    self.estado.marcar(identificador, "sem_extensao")
                self._ao_mudar()
                self._acordar.wait(self._intervalo_s * 5)
                self._acordar.clear()
                return None
        for identificador in ligadas:
            if self.estado.precisa_abrir(identificador):
                self._abrir(identificador, familia)
        try:
            eventos = assinatura.esperar(self._intervalo_s)
        except Exception:  # o host fechou: assina de novo no próximo tique
            with contextlib.suppress(Exception):
                assinatura.fechar()
            return None
        mudou = False
        configuracao = self._configuracao()
        for evento in eventos:
            if evento.get("evento") != "social":
                continue
            try:
                pagina = EstadoDaPagina.do_evento(evento)
            except EventoInvalido:
                continue
            if pagina.rede not in ligadas:
                continue
            aviso = self.estado.receber(
                pagina, notificar=configuracao.ajuste(pagina.rede).notificar
            )
            mudou = True
            self._entregar(pagina.rede, aviso)
            self._repassar(pagina)
        self.estado.conferir_noticia()
        if mudou:
            self._ao_mudar()
        return assinatura

    def _abrir(self, identificador: str, familia: str) -> None:
        self.estado.pedida(identificador)
        self.estado.marcar(identificador, "abrindo")
        try:
            self._ponte.pedir("social.abrir", familia, rede=identificador)
        except Exception:  # a próxima tentativa vem em REABRIR_S
            self.estado.marcar(identificador, "sem_extensao")
            return
        with contextlib.suppress(Exception):  # o estado de agora, sem esperar o próximo evento
            resposta = self._ponte.pedir("social.estado", familia, rede=identificador)
            pagina = EstadoDaPagina.do_evento({"rede": identificador, **resposta})
            aviso = self.estado.receber(
                pagina, notificar=self._configuracao().ajuste(identificador).notificar
            )
            self._entregar(identificador, aviso)
            self._repassar(pagina)
        self._ao_mudar()

    def _repassar(self, pagina: EstadoDaPagina) -> None:
        if self.ao_estado is not None:
            with contextlib.suppress(Exception):
                self.ao_estado(pagina)

    def _entregar(self, identificador: str, aviso: Notificacao | None) -> None:
        if aviso is None:
            return
        alerta = self.estado.alerta(identificador)
        if alerta and self._ao_alerta is not None:
            self._ao_alerta(identificador, alerta)
        self._ao_notificar(aviso)


__all__ = [
    "ESTADOS",
    "ConversaNaoLida",
    "EstadoDaPagina",
    "EstadoDoMonitor",
    "EventoInvalido",
    "MonitorSocial",
    "Notificacao",
]
