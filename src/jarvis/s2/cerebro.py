"""O cérebro: uma conversa contínua, dona do contexto, que responde em stream (ADR-0025).

Decisão do dono (2026-10-16): **um** cérebro com conversa contínua, interrompível, que começa a
falar enquanto gera e, interrompido, para de falar **e de gerar**. Este módulo é a parte do
`s2` que faz isso, sem processo e sem barramento — quem publica é o chamador, por `publicar` —,
para o contrato ser testado inteiro em memória:

- **A conversa é nossa** (regra 2). O motor recebe o contexto montado aqui a cada pedido.
- **Só o tocado volta** (regra 3). A resposta só entra na conversa por `ouvido`, com o texto que
  o dono ouviu; resposta de que ninguém confirmou o tocado **não existe** para o modelo (§3.3,
  regra 4) — inclusive a que foi gerada inteira.
- **Pedaço por fronteira** (regra 7). O texto do motor passa pelo `FatiadorDeFala` (a mesma regra
  do TTS) e sai um `ResponseChunk` por pedaço.
- **Cancelamento** (regra 9). Visto o cancelamento, nada mais daquele epoch é publicado, e o
  iterador do motor é fechado — é o `finally` dele que mata processo ou conexão. O tempo entre
  ver o cancelamento e o motor parado é medido e fica na `Resposta`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.barramento.contrato import prioridade_canonica, validar
from jarvis.barramento.envelope import Envelope, Tipo, Trust, uuid7
from jarvis.executor.ferramentas import (
    Confirmar,
    ExecutorDeFerramentas,
    ResultadoDeFerramenta,
    negar_sempre,
)
from jarvis.fatiador import Corte, FatiadorDeFala, PedacoDeFala
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.politica.memoria import AlcanceDeMemoria, Proveniencia, TurnoCorrente
from jarvis.s2.avisos import AvisoLiberado, frase_do_aviso
from jarvis.s2.fluxo_de_acao import FluxoDeAcao
from jarvis.s2.memoria_do_turno import MemoriaDoTurno, consultar
from jarvis.s2.motor import (
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    PedidoDeTool,
    Pensar,
)
from jarvis.s2.pendencias import RegistroDePendencias
from jarvis.s2.persona import prompt_de_sistema
from jarvis.s2.portao import AutorizacoesExplicitas, PortaoDeAcao
from jarvis.voz.interface import Cancelado, nunca_cancelado

MAXIMO_DE_PASSOS: Final = 12
"""Chamadas de ferramenta que um turno pode encadear antes de ter de responder."""
PRAZO_DO_LACO_DE_FERRAMENTAS_S: Final = 90.0
"""Orçamento total do laço agêntico; inclui pensar e executar as ferramentas."""
# Nome preservado para quem importava o teto antigo. Agora cada rodada tem exatamente um passo:
# o resultado volta ao motor antes de ele poder propor o próximo.
MAXIMO_DE_RODADAS: Final = MAXIMO_DE_PASSOS
TURNOS_NO_CONTEXTO: Final = 12
"""Orçamento fixo de conversa no contexto (regra 5): os últimos turnos estáveis. O resumo do que
ficou para trás é trabalho de segundo plano, fora desta fatia."""

Publicar = Callable[[dict[str, Any]], None]
"""Recebe o payload de um `ResponseChunk`. No processo, vira envelope (`envelope_do_pedaco`)."""
Mostrar = Callable[[str], None]
"""Recebe o texto da resposta como está agora, a cada delta: é o que a tela mostra. A fala vai em
lotes de 14..18 palavras (`FatiadorDeFala`); a tela não espera o lote — segue a geração."""
AvisarStatus = Callable[[str], None]
"""Enfileira um status curto; a fronteira de voz decide quando (e se) ele será falado."""


@dataclass(slots=True)
class Conversa:
    """Os turnos estáveis da sessão. Do Jarvis, só o que tocou."""

    sistema: str = field(default_factory=prompt_de_sistema)
    """A persona (`persona.md`), no lugar do prompt curto do provisório."""
    turnos: list[Mensagem] = field(default_factory=list)
    maximo: int = TURNOS_NO_CONTEXTO

    def contexto(self) -> Contexto:
        return Contexto(sistema=self.sistema, mensagens=tuple(self.turnos[-self.maximo :]))


@dataclass(slots=True)
class Resposta:
    """O que aconteceu num turno, para a auditoria e para o harness."""

    response_id: str
    turn_id: str
    epoch: int
    motor: str
    gerado: str = ""
    """Tudo o que o motor entregou — **não** é o que o dono ouviu, e não volta ao contexto."""
    publicados: list[dict[str, Any]] = field(default_factory=list)
    fim: MotivoDoFim = MotivoDoFim.CONCLUIDO
    detalhe: str = ""
    pediu_pensar: bool = False
    deltas_depois_do_cancelamento: int = 0
    ferramentas: list[ResultadoDeFerramenta] = field(default_factory=list)
    """Cada chamada do turno, com o que aconteceu — para a auditoria e para o teste."""
    memoria: MemoriaDoTurno | None = None
    """O que o livro lembrou e foi ao prompt neste turno (fatia 7), com a proveniência."""
    ms_ate_contexto: float = 0.0
    ms_ate_primeiro_token: float | None = None
    """Do turno aceito ao primeiro texto que o motor entregou (antes do fatiador)."""
    ms_ate_primeiro_pedaco: float | None = None
    ms_cancelamento_ate_motor_parado: float | None = None

    @property
    def cancelada(self) -> bool:
        return self.fim is MotivoDoFim.CANCELADO


@dataclass(slots=True)
class Cerebro:
    """Uma conversa, um motor trocável, e o stream de pedaços de fala."""

    motor: MotorDeConversa
    conversa: Conversa = field(default_factory=Conversa)
    livro: LivroDeMemoria | None = None
    """O histórico persistente (ADR-0026, M1). Sem ele, a conversa vive só na memória."""
    session_id: str = ""
    id_da_conversa: str = ""
    """A conversa persistente a que os turnos pertencem no livro (reabrir o app a continua).
    Vazio = a da sessão, como antes."""
    turno_corrente: TurnoCorrente | None = None
    ferramentas: ExecutorDeFerramentas | None = None
    """O executor das tools do catálogo v1 (ADR-0028). Sem ele, pedido de tool volta negado."""
    confirmar: Confirmar = negar_sempre
    """Como o dono confirma: a janela liga aqui. Sem janela, toda confirmação é não."""
    lembrar_a_cada_turno: bool = True
    """Com livro, consulta a memória antes de cada resposta (fatia 7, `memoria_do_turno`)."""
    alcance_de_memoria: AlcanceDeMemoria = field(default_factory=AlcanceDeMemoria)
    """O que o dono deixou a memória alcançar (ADR-0026, regra 7) — o D20 decide com ele."""
    ao_lembrar: Callable[[MemoriaDoTurno], None] | None = None
    """Chamada da linha do cérebro quando a consulta termina, antes do motor: é por onde a tela
    mostra "lembrei: …". Quem liga aqui guarda e volta."""
    maximo_de_passos: int = MAXIMO_DE_PASSOS
    """Teto configurável de chamadas no encadeamento de ferramentas deste turno."""
    prazo_do_laco_de_ferramentas_s: float = PRAZO_DO_LACO_DE_FERRAMENTAS_S
    """Teto configurável, em segundos, para o encadeamento inteiro."""
    ao_status: AvisarStatus | None = None
    """Porta para a fila de avisos: status nunca é publicado por cima da fala em curso."""
    relogio: Callable[[], float] = time.monotonic
    """Relógio injetável para medir o prazo do laço sem tornar o teste lento."""
    portao: PortaoDeAcao | None = None
    """O portão contextual (Jev) antes de cada ferramenta (`jarvis.s2.fluxo_de_acao`). Com ele, a
    confirmação vira pendência que não prende o turno, o "sim" pode ser falado e a execução
    confirmada vai para uma tarefa. `None` = o caminho de antes: só o PDP, e a janela bloqueia."""
    pendencias: RegistroDePendencias = field(default_factory=RegistroDePendencias)
    autorizacoes: AutorizacoesExplicitas = field(default_factory=AutorizacoesExplicitas)
    _pendentes: dict[str, Resposta] = field(default_factory=dict)

    @property
    def fluxo(self) -> FluxoDeAcao | None:
        if self.portao is None:
            return None
        return FluxoDeAcao(self.portao, self.pendencias, self.autorizacoes)

    def resolver_pendencia(self, pendencia_id: str, sim: bool) -> bool:
        """O clique do dono numa pendência (não bloqueante). Devolve se ela ainda valia."""
        fluxo = self.fluxo
        if fluxo is None or self.ferramentas is None:
            return False
        resultado = fluxo.resolver(self.ferramentas, pendencia_id, sim=sim)
        if resultado is None:
            return False
        if resultado.status == "despachado":
            self._status("Confirmado: está rodando em segundo plano; aviso quando terminar.")
        elif sim and resultado.status != "ok":
            self._status(f"Não deu para fazer o que você confirmou: {resultado.motivo}")
        return True

    @property
    def proveniencia(self) -> Proveniencia:
        """A origem de uma escrita de memória neste turno — do estado do cérebro, nunca do
        modelo (ADR-0026, regra 2). Sem histórico não há episódio, e a escrita é negada."""
        return Proveniencia(turno=self.turno_corrente, motor=self.motor.nome)

    def responder(
        self,
        texto_do_dono: str,
        *,
        epoch: int,
        publicar: Publicar,
        turn_id: str = "",
        cancelado: Cancelado = nunca_cancelado,
        modo: Modo = Modo.RAPIDO,
        trust: str = "user_voice",
        avisos: Sequence[AvisoLiberado] = (),
        mostrar: Mostrar | None = None,
    ) -> Resposta:
        """Responde a um turno estável do dono, publicando os pedaços enquanto o motor gera.

        `avisos` são os que a fila liberou junto com esta mensagem e que o `s2` decidiu falar
        (ADR-0025, regra 13, decisão do dono): vão **antes** da resposta, em pedaços marcados
        com `notif_ids`, e o motor fica sabendo que já foram ditos — informa, depois responde.
        """
        comeco = time.monotonic()
        # Resposta anterior sem `ouvido`: ninguém confirmou que tocou, então não existe (P4).
        self._pendentes.clear()
        anteriores = tuple(self.conversa.turnos)
        self.conversa.turnos.append(Mensagem("dono", texto_do_dono))
        self.turno_corrente = None
        if self.ferramentas is not None:
            self.ferramentas.novo_turno(texto_do_dono)
        if self.livro is not None:
            episodio = self.livro.gravar_turno(
                session_id=self.id_da_conversa or self.session_id,
                papel="dono",
                texto=texto_do_dono,
                trust=trust,
            )
            self.turno_corrente = TurnoCorrente(episodio, texto_do_dono, trust)
        fluxo = self.fluxo
        nota_da_pendencia = ""
        if fluxo is not None and self.ferramentas is not None:
            # A fala é lida primeiro contra a pergunta pendente (se houver uma válida): "sim"
            # resolve **aquela** e o turno é só a confirmação; outro assunto a cancela.
            leitura = fluxo.ler_a_resposta(
                self.ferramentas, texto_do_dono, mensagens=anteriores, cancelado=cancelado
            )
            if leitura.frase:
                return self._so_dizer(
                    leitura.frase,
                    epoch=epoch,
                    turn_id=turn_id,
                    publicar=publicar,
                    cancelado=cancelado,
                    comeco=comeco,
                    ferramentas=[leitura.resultado] if leitura.resultado else [],
                    mostrar=mostrar,
                )
            nota_da_pendencia = leitura.nota
            self.autorizacoes.novo_turno(texto_do_dono)
        memoria = None
        contexto = self.conversa.contexto()
        if nota_da_pendencia:
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{nota_da_pendencia}", mensagens=contexto.mensagens
            )
        if self.livro is not None and self.lembrar_a_cada_turno:
            memoria = consultar(
                self.livro,
                texto_do_dono,
                onde=self.motor.onde,
                motor=self.motor.nome,
                alcance=self.alcance_de_memoria,
            )
            if self.ao_lembrar is not None:
                self.ao_lembrar(memoria)
            if memoria.bloco():
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{memoria.bloco()}",
                    mensagens=contexto.mensagens,
                )
        if avisos:
            ditos = " ".join(frase_do_aviso(a) for a in avisos)
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\nAntes desta resposta você já disse ao dono, em "
                f"voz: «{ditos}» Não repita o aviso: responda à mensagem dele.",
                mensagens=contexto.mensagens,
            )
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor=self.motor.nome,
            ms_ate_contexto=_ms_desde(comeco),
            memoria=memoria,
        )
        fatiador = FatiadorDeFala()
        crescer = _tela(resposta, mostrar)
        visto_cancelamento = self._falar_avisos(
            avisos, resposta, publicar, comeco, cancelado, crescer
        )
        catalogo = self.ferramentas.catalogo_para_o_modelo() if self.ferramentas else ()
        resultados: list[Mensagem] = []
        limite_do_laco = self.relogio() + self.prazo_do_laco_de_ferramentas_s

        def prazo_esgotado() -> bool:
            return self.relogio() >= limite_do_laco

        def cancelado_no_laco() -> bool:
            return cancelado() or prazo_esgotado()

        for passo in range(1, self.maximo_de_passos + 1):
            if visto_cancelamento is not None:
                break
            if cancelado_no_laco():
                if cancelado():
                    visto_cancelamento = time.monotonic()
                else:
                    resposta.fim = MotivoDoFim.PRAZO
                    resposta.detalhe = (
                        f"o laço de ferramentas passou de "
                        f"{self.prazo_do_laco_de_ferramentas_s:.0f} s"
                    )
                break
            da_vez = Contexto(
                sistema=contexto.sistema,
                mensagens=(*contexto.mensagens, *resultados),
                ferramentas=catalogo,
            )
            pedidos, visto_cancelamento = self._rodada(
                da_vez, modo, cancelado_no_laco, fatiador, resposta, publicar, comeco, crescer
            )
            if prazo_esgotado() and not cancelado():
                visto_cancelamento = None
                resposta.fim = MotivoDoFim.PRAZO
                resposta.detalhe = (
                    f"o laço de ferramentas passou de {self.prazo_do_laco_de_ferramentas_s:.0f} s"
                )
                break
            if (
                visto_cancelamento is not None
                or not pedidos
                or resposta.fim is not MotivoDoFim.CONCLUIDO
            ):
                break
            # O que o motor disse antes de pedir a ferramenta ("deixa eu ver") sai agora, mesmo
            # abaixo do piso de 14 palavras do lote: até a ferramenta voltar não há mais texto.
            # Com `alimentar(" ")` (antes de 7507cd5 bastava), a frase ficava no buffer e era
            # falada só depois da ferramenta.
            for pedaco in fatiador.descarregar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            # Uma por vez: o próximo pedido só pode nascer depois que o modelo viu este
            # resultado. Pedidos adicionais da mesma geração são especulativos e ficam de fora.
            pedido = pedidos[0]
            if cancelado_no_laco():
                if cancelado():
                    visto_cancelamento = time.monotonic()
                else:
                    resposta.fim = MotivoDoFim.PRAZO
                    resposta.detalhe = (
                        f"o laço de ferramentas passou de "
                        f"{self.prazo_do_laco_de_ferramentas_s:.0f} s"
                    )
                break
            resultado = self._chamar(pedido, cancelado_no_laco, texto_do_dono)
            resposta.ferramentas.append(resultado)
            resultados.append(Mensagem("ferramenta", resultado.para_o_modelo()))
            self._status(f"Passo {passo} terminou; avaliando o resultado.")
            if resultado.aviso:
                # Tool moderada: o aviso é do código, e sai agora, em voz (dono, 2026-10-18).
                resposta.gerado += resultado.aviso + " "
                crescer()
                for pedaco in fatiador.alimentar(resultado.aviso + " ") + fatiador.descarregar():
                    self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            if resultado.status == "pendente":
                # A pergunta é a última coisa do turno: o laço de voz fica livre para o "sim".
                break
            if prazo_esgotado() and not cancelado():
                resposta.fim = MotivoDoFim.PRAZO
                resposta.detalhe = (
                    f"o laço de ferramentas passou de {self.prazo_do_laco_de_ferramentas_s:.0f} s"
                )
                break
            if cancelado():
                visto_cancelamento = time.monotonic()
        else:
            resposta.detalhe = (
                f"o motor pediu ferramenta {self.maximo_de_passos} vezes sem responder"
            )
        if visto_cancelamento is None and cancelado():
            visto_cancelamento = time.monotonic()
        if visto_cancelamento is not None or resposta.fim is MotivoDoFim.CANCELADO:
            resposta.fim = MotivoDoFim.CANCELADO
            parado = time.monotonic()
            resposta.ms_cancelamento_ate_motor_parado = (
                (parado - visto_cancelamento) * 1000.0 if visto_cancelamento is not None else 0.0
            )
        else:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        self.autorizacoes.encerrar()
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _so_dizer(
        self,
        frase: str,
        *,
        epoch: int,
        turn_id: str,
        publicar: Publicar,
        cancelado: Cancelado,
        comeco: float,
        ferramentas: list[ResultadoDeFerramenta],
        mostrar: Mostrar | None = None,
    ) -> Resposta:
        """Um turno sem motor: a frase é do código (a resposta do dono a uma pendência)."""
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor="portao",
            gerado=frase,
            ferramentas=ferramentas,
            ms_ate_contexto=_ms_desde(comeco),
        )
        _tela(resposta, mostrar)()
        fatiador = FatiadorDeFala()
        for pedaco in fatiador.alimentar(frase):
            if cancelado():
                resposta.fim = MotivoDoFim.CANCELADO
                break
            self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
        else:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _rodada(
        self,
        contexto: Contexto,
        modo: Modo,
        cancelado: Cancelado,
        fatiador: FatiadorDeFala,
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
        crescer: Callable[[], None],
    ) -> tuple[list[PedidoDeTool], float | None]:
        """Uma chamada ao motor: publica o texto em pedaços e junta os pedidos de ferramenta."""
        pedidos: list[PedidoDeTool] = []
        visto_cancelamento: float | None = None
        deltas = self.motor.gerar(contexto, modo, cancelado)
        try:
            for delta in deltas:
                if isinstance(delta, Fim):
                    resposta.fim, resposta.detalhe = delta.motivo, delta.detalhe
                    if delta.motivo is MotivoDoFim.CANCELADO:
                        visto_cancelamento = time.monotonic()
                    break
                if isinstance(delta, Pensar):
                    # Regra 4: quem refaz no modo `pensar` (com a ponte) é o chamador.
                    resposta.pediu_pensar = True
                    continue
                if isinstance(delta, PedidoDeTool):
                    pedidos.append(delta)  # o modelo propõe; quem dispõe é o código (P1)
                    continue
                if resposta.ms_ate_primeiro_token is None and delta.texto.strip():
                    resposta.ms_ate_primeiro_token = _ms_desde(comeco)
                resposta.gerado += delta.texto
                crescer()  # a tela, já: o lote de fala pode levar 14 palavras para fechar
                for pedaco in fatiador.alimentar(delta.texto):
                    if cancelado():
                        visto_cancelamento = time.monotonic()
                        break
                    self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
                if visto_cancelamento is None and cancelado():
                    visto_cancelamento = time.monotonic()
                if visto_cancelamento is not None:
                    break
        finally:
            # Fechar o iterador é o que faz o motor parar de gerar (o `finally` dele).
            deltas.close()
        return pedidos, visto_cancelamento

    def _chamar(
        self, pedido: PedidoDeTool, cancelado: Cancelado, texto_do_dono: str = ""
    ) -> ResultadoDeFerramenta:
        if self.ferramentas is None:
            return ResultadoDeFerramenta(
                pedido.tool_id, "negado", motivo="nenhuma ferramenta está ligada nesta sessão"
            )
        fluxo = self.fluxo
        if fluxo is not None:
            return fluxo.chamar(
                self.ferramentas,
                pedido,
                pedido_do_dono=texto_do_dono,
                mensagens=self.conversa.turnos,
                cancelado=cancelado,
                confirmar=self.confirmar,
                session_id=self.session_id,
                proveniencia=self.proveniencia,
            )
        return self.ferramentas.executar(
            pedido.tool_id,
            pedido.args,
            cancelado=cancelado,
            confirmar=self.confirmar,
            session_id=self.session_id,
            proveniencia=self.proveniencia,
        )

    def _status(self, texto: str) -> None:
        """Entrega progresso à fila sem deixar uma falha dela derrubar o turno."""
        if self.ao_status is None:
            return
        try:
            self.ao_status(texto)
        except Exception:
            return

    def avisar(
        self,
        avisos: Sequence[AvisoLiberado],
        *,
        epoch: int,
        publicar: Publicar,
        cancelado: Cancelado = nunca_cancelado,
    ) -> Resposta:
        """Piso livre, sem mensagem do dono: só os avisos, sem chamar o motor (regra 12)."""
        comeco = time.monotonic()
        self._pendentes.clear()
        resposta = Resposta(
            response_id=f"r-{uuid7()}", turn_id=f"t-{uuid7()}", epoch=epoch, motor="avisos"
        )
        fatiador = FatiadorDeFala()
        if self._falar_avisos(avisos, resposta, publicar, comeco, cancelado) is None:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        else:
            resposta.fim = MotivoDoFim.CANCELADO
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _falar_avisos(
        self,
        avisos: Sequence[AvisoLiberado],
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
        cancelado: Cancelado,
        crescer: Callable[[], None] = lambda: None,
    ) -> float | None:
        """Publica a frase de cada aviso; devolve o instante do cancelamento, se houve."""
        for aviso in avisos:
            if cancelado():
                return time.monotonic()
            frase = frase_do_aviso(aviso)
            resposta.gerado += frase + " "
            crescer()
            # Cada aviso é uma fala completa: seu residual pode ser curto, mas precisa sair
            # com o próprio notif_id antes do próximo aviso ou da resposta. Compartilhar o
            # buffer perderia a identidade de avisos menores que o piso normal de 14 palavras.
            fatiador = FatiadorDeFala()
            for pedaco in fatiador.alimentar(frase) + fatiador.fechar():
                if not pedaco.texto:
                    continue
                if cancelado():
                    return time.monotonic()
                self._publicar(
                    resposta, pedaco, publicar, comeco, ultimo=False, notif_ids=[aviso.notif_id]
                )
        return time.monotonic() if cancelado() else None

    def ouvido(
        self,
        response_id: str,
        texto_tocado: str,
        *,
        interrompida: bool,
        played_ms: int | None = None,
    ) -> None:
        """O que de fato tocou da resposta — só isso entra na conversa (regra 3, P4).

        Com histórico, o turno vai para o livro com o `played_ms` real: sem ele, o livro recusa.
        """
        resposta = self._pendentes.pop(response_id, None)
        if resposta is None:
            return  # resposta velha, já substituída por um turno novo do dono
        if interrompida:
            self._esquecer_pergunta_nao_ouvida(resposta, texto_tocado)
        if not (texto_tocado or interrompida):
            return
        self.conversa.turnos.append(Mensagem("jarvis", texto_tocado, interrompida))
        if self.livro is not None:
            self.livro.gravar_turno(
                session_id=self.id_da_conversa or self.session_id,
                papel="jarvis",
                texto=texto_tocado,
                trust="system",
                played_ms=played_ms,
                interrompida=interrompida,
            )

    def _esquecer_pergunta_nao_ouvida(self, resposta: Resposta, texto_tocado: str) -> None:
        """O dono cortou a fala antes do fim da pergunta: ela não foi feita, e um "sim" dito por
        cima não pode autorizar o que ele não ouviu. A pendência cai."""
        aberta = self.pendencias.valida()
        if aberta is None:
            return
        for resultado in resposta.ferramentas:
            if resultado.call_id == aberta.id and resultado.aviso not in texto_tocado:
                self.pendencias.cancelar()
                return

    def _publicar(
        self,
        resposta: Resposta,
        pedaco: PedacoDeFala,
        publicar: Publicar,
        comeco: float,
        *,
        ultimo: bool,
        notif_ids: Sequence[str] = (),
    ) -> None:
        payload: dict[str, Any] = {
            "response_id": resposta.response_id,
            "turn_id": resposta.turn_id,
            "epoch": resposta.epoch,
            "seq": len(resposta.publicados),
            "text": pedaco.texto,
            "boundary": str(pedaco.corte),
            "last": ultimo,
        }
        if notif_ids:
            payload["notif_ids"] = list(notif_ids)
        if ultimo:
            # Nunca `cancelado`: resposta cancelada não publica o último pedaço (regra 9).
            payload["end_reason"] = str(resposta.fim)
        if resposta.ms_ate_primeiro_pedaco is None and pedaco.texto:
            resposta.ms_ate_primeiro_pedaco = _ms_desde(comeco)
        resposta.publicados.append(payload)
        publicar(payload)


def _tela(resposta: Resposta, mostrar: Mostrar | None) -> Callable[[], None]:
    """O que a tela mostra quando o texto da resposta cresce: tudo até agora, com espaço
    normalizado, e só quando mudou (delta só de espaço não redesenha a tela)."""
    visto = [""]

    def crescer() -> None:
        texto = " ".join(resposta.gerado.split())
        if mostrar is not None and texto and texto != visto[0]:
            visto[0] = texto
            mostrar(texto)

    return crescer


def envelope_do_pedaco(session_id: str, payload: dict[str, Any]) -> Envelope:
    """O `ResponseChunk` no envelope da §3.1, validado na borda como qualquer evento."""
    return validar(
        Envelope(
            session_id=session_id,
            epoch=int(payload["epoch"]),
            source="s2",
            trust=Trust.SYSTEM,
            priority=prioridade_canonica(Tipo.RESPONSE_CHUNK, payload),
            type=Tipo.RESPONSE_CHUNK,
            payload=payload,
        )
    )


def _ms_desde(comeco: float) -> float:
    return (time.monotonic() - comeco) * 1000.0
