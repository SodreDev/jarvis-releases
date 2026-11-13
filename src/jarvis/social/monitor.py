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

from jarvis.navegador.cliente import (
    ExtensaoDesatualizada,
    NavegadorFalhou,
    NavegadorIndisponivel,
    SemResposta,
)
from jarvis.navegador.protocolo import VERSAO_DA_PONTE
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
REABRIR_APOS_FALHA_S: Final = 15.0
"""O pedido da aba falhou (a extensão não respondeu, recusou, estava sem host): tenta de novo
logo, sem esperar os `REABRIR_S` de quem só ficou sem notícia."""
INTERVALO_S: Final = 2.0
PRAZO_DE_CONEXAO_S: Final = 30.0
"""Quanto tempo o monitor procura o host da extensão antes de dizer que ela não está conectada:
na partida do navegador (o fundo da extensão ainda não chamou o host) e no «Recarregar» (o host
é relançado), o socket some por alguns segundos. Dentro do prazo, «conectando», tentando a cada
`INTERVALO_S`; fora dele, a frase do que faltou, tentando a cada `INTERVALO_S * 5`."""


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
    "conectando": "procurando o navegador com a extensão do Jarvis…",
    "sem_navegador": "o navegador não está aberto: abra-o (o Jarvis tenta de novo sozinho)",
    "sem_extensao": (
        "a extensão do Jarvis não está conectada: confira na página de extensões do navegador "
        "(brave://extensions) se o Jarvis está ativo neste perfil e clique em Recarregar — o "
        "Jarvis tenta de novo sozinho"
    ),
    "extensao_antiga": (
        "a extensão do Jarvis no navegador é de uma versão anterior: clique em Recarregar no card "
        "do Jarvis (brave://extensions) — isso também relança o host"
    ),
    "sem_resposta": "a extensão não respondeu ao abrir a aba: o Jarvis tenta de novo em 15 s",
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
    falhou_em: float | None = None
    """O último `social.abrir` que falhou: a próxima tentativa vem em `REABRIR_APOS_FALHA_S`."""
    codigo: str = ""
    """O código da última falha (`sem_host`, `extensao_desatualizada`, `sem_resposta`…)."""
    notificacoes: deque[Notificacao] = field(
        default_factory=lambda: deque(maxlen=MAXIMO_DE_NOTIFICACOES)
    )


class EstadoDoMonitor:
    """O estado de cada rede e a regra de avisar. Seguro entre fios (uma trava)."""

    def __init__(self, relogio: Callable[[], float] = time.time) -> None:
        self._relogio = relogio
        self._trava = threading.Lock()
        self._redes: dict[str, _DaRede] = {r: _DaRede() for r in IDS}
        self._versao_antiga = ""
        """O código da versão velha da ponte (`extensao_v3`, `host_v4`), ou vazio se em dia."""

    def versao(self, codigo: str) -> None:
        """O que a pergunta de versão ao host achou: vazio = em dia."""
        with self._trava:
            self._versao_antiga = codigo

    def ajustar(self, configuracao: ConfiguracaoSocial) -> None:
        """Rede desligada volta a «desligada» e esquece a base; ligada sem notícia, «abrindo»."""
        with self._trava:
            for identificador, da_rede in self._redes.items():
                if not configuracao.ajuste(identificador).monitorar:
                    self._redes[identificador] = _DaRede(notificacoes=da_rede.notificacoes)
                elif da_rede.estado == "desligada":
                    da_rede.estado = "abrindo"

    def marcar(self, identificador: str, estado: str, codigo: str = "") -> None:
        if estado not in ESTADOS:
            raise ValueError(f"estado desconhecido {estado!r}")
        with self._trava:
            da_rede = self._redes[identificador]
            if da_rede.estado != "desligada":
                da_rede.estado = estado
                da_rede.codigo = codigo

    def pedida(self, identificador: str) -> None:
        with self._trava:
            da_rede = self._redes[identificador]
            da_rede.pedida_em = self._relogio()
            da_rede.falhou_em = None

    def falhou(self, identificador: str, estado: str, codigo: str) -> None:
        """O `social.abrir` não deu: diz o que faltou e pede de novo em `REABRIR_APOS_FALHA_S`."""
        self.marcar(identificador, estado, codigo)
        with self._trava:
            self._redes[identificador].falhou_em = self._relogio()

    def reconectou(self, identificadores: Sequence[str]) -> None:
        """O host voltou (assinatura nova): cada rede pede a aba de novo já — o `social.abrir`
        reusa a que existe e o `social.estado` traz o estado de agora, sem esperar o minuto."""
        with self._trava:
            for identificador in identificadores:
                da_rede = self._redes[identificador]
                da_rede.pedida_em = None
                da_rede.falhou_em = None

    def precisa_abrir(self, identificador: str) -> bool:
        """Nunca pedida, pedida há muito tempo sem notícia, ou o último pedido falhou."""
        agora = self._relogio()
        with self._trava:
            da_rede = self._redes[identificador]
            if da_rede.pedida_em is None:
                return True
            if da_rede.falhou_em is not None:
                return agora - da_rede.falhou_em >= REABRIR_APOS_FALHA_S
            ultima = max(da_rede.pedida_em, da_rede.noticia_em or 0.0)
            return agora - ultima >= REABRIR_S

    def diagnostico(self, identificador: str) -> dict[str, str]:
        """O que vai à trilha (só códigos): o estado e o código da última falha."""
        with self._trava:
            da_rede = self._redes[identificador]
            codigo = da_rede.codigo or (
                self._versao_antiga if da_rede.estado != "desligada" else ""
            )
            return {"rede": identificador, "estado": da_rede.estado, "codigo": codigo}

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
            da_rede.codigo = ""
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
            if self._versao_antiga and da_rede.estado not in ("desligada", "extensao_antiga"):
                frase = f"{frase} — atenção: {ESTADOS['extensao_antiga']}"
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
        navegador_aberto: Callable[[], bool | None] | None = None,
        ao_diagnostico: Callable[[Mapping[str, str]], None] | None = None,
        prazo_de_conexao_s: float = PRAZO_DE_CONEXAO_S,
        relogio: Callable[[], float] = time.monotonic,
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
        self._navegador_aberto = navegador_aberto
        """Há processo do navegador escolhido rodando? `None` = não dá para saber. Separa «abra
        o navegador» de «a extensão não está conectada» quando o host não aparece."""
        self._ao_diagnostico = ao_diagnostico
        """Cada mudança do estado de uma rede, em códigos (`rede`, `estado`, `codigo`…): vai à
        trilha de diagnóstico, para o dono mandar o que aconteceu."""
        self._prazo_de_conexao_s = prazo_de_conexao_s
        self._relogio = relogio
        self._sem_host_desde: float | None = None
        self._registrado: dict[str, tuple[str, ...]] = {}
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
                self._registrar(ligadas)
        finally:
            if assinatura is not None:
                with contextlib.suppress(Exception):
                    assinatura.fechar()

    def _sem_host(self, ligadas: Sequence[str]) -> None:
        """Nenhum host da extensão aceitou a assinatura. Dentro do prazo de conexão (o navegador
        partindo, o «Recarregar» relançando o host) é «conectando» e tenta logo; depois, diz o
        que faltou — o navegador fechado ou a extensão desconectada — e tenta a cada 10 s."""
        agora = self._relogio()
        if self._sem_host_desde is None:
            self._sem_host_desde = agora
        if agora - self._sem_host_desde < self._prazo_de_conexao_s:
            estado, codigo, espera = "conectando", "sem_host", self._intervalo_s
        else:
            aberto: bool | None = None
            if self._navegador_aberto is not None:
                with contextlib.suppress(Exception):
                    aberto = self._navegador_aberto()
            if aberto is False:
                estado, codigo = "sem_navegador", "navegador_fechado"
            else:
                estado, codigo = "sem_extensao", "sem_host"
            espera = self._intervalo_s * 5
        for identificador in ligadas:
            self.estado.marcar(identificador, estado, codigo)
        self._ao_mudar()
        self._registrar(ligadas)
        self._acordar.wait(espera)
        self._acordar.clear()

    def _conferir_versao(self, familia: str) -> None:
        """Uma vez por assinatura: a extensão ou o host de antes (sem `social.js` novo, ou com o
        protocolo velho) dizem «Recarregar», em vez de falhar calados mais adiante."""
        perguntar = getattr(self._ponte, "versao", None)
        if perguntar is None:
            return
        try:
            versao = perguntar(familia)
        except Exception:  # pergunta que não deu: não é motivo para parar o monitor
            return
        extensao = getattr(versao, "extensao", None)
        host = getattr(versao, "host", None)
        if extensao is None or extensao < VERSAO_DA_PONTE:
            self.estado.versao(f"extensao_v{extensao or 0}")
        elif host is None or host < VERSAO_DA_PONTE:
            self.estado.versao(f"host_v{host or 0}")
        else:
            self.estado.versao("")

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
                self._sem_host(ligadas)
                return None
            self._sem_host_desde = None
            self._conferir_versao(familia)
            self.estado.reconectou(ligadas)
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
        except ExtensaoDesatualizada:
            # O host de agora não conhece `social.abrir`: a extensão (e o host) são de antes.
            self.estado.falhou(identificador, "extensao_antiga", "extensao_desatualizada")
            self._ao_mudar()
            return
        except SemResposta:
            self.estado.falhou(identificador, "sem_resposta", "sem_resposta")
            self._ao_mudar()
            return
        except NavegadorFalhou as erro:
            self.estado.falhou(identificador, "sem_resposta", erro.codigo)
            self._ao_mudar()
            return
        except NavegadorIndisponivel:
            # O host sumiu entre a assinatura e o pedido: o próximo tique assina de novo.
            self.estado.falhou(identificador, "conectando", "sem_host")
            self._ao_mudar()
            return
        except Exception:  # qualquer outra: tenta de novo em REABRIR_APOS_FALHA_S
            self.estado.falhou(identificador, "sem_resposta", "falha")
            self._ao_mudar()
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

    def _registrar(self, ligadas: Sequence[str]) -> None:
        """Na trilha, só quando o estado (ou o código) de uma rede muda: nunca a cada tique."""
        if self._ao_diagnostico is None:
            return
        for identificador in ligadas:
            dados = self.estado.diagnostico(identificador)
            chave = tuple(dados.values())
            if self._registrado.get(identificador) == chave:
                continue
            self._registrado[identificador] = chave
            with contextlib.suppress(Exception):
                self._ao_diagnostico(dados)

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
