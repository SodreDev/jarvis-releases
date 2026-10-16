"""Corretor do barramento: vive no `agentd`, que é o dono do epoch e do log (SPEC §2).

O que ele faz, nesta ordem, para cada quadro que chega: valida na borda, grava no log,
pergunta ao epoch o que fazer e só então entrega a quem assinou o tipo. Quem reconecta pede
pelo cursor e recebe o que perdeu — é assim que reiniciar um processo não perde log.

Ele **não** decide política, não executa capacidade e não fala com LLM: roteia e registra.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from multiprocessing.connection import wait
from pathlib import Path
from typing import Any, Final

from jarvis.barramento.contrato import ErroDeContrato, validar_bruto
from jarvis.barramento.entrada import Fronteira, receber
from jarvis.barramento.envelope import Envelope, Tipo
from jarvis.barramento.epoch import TIPOS_DE_AUDITORIA, DonoDoEpoch, Veredito
from jarvis.barramento.fila import FilaCheia, FilaDePrioridade
from jarvis.barramento.ipc import Canal, ServidorDoBarramento
from jarvis.barramento.log import LogDeEventos
from jarvis.dados import caminho

ARQUIVO_ROTEAMENTO: Final = caminho("schemas/roteamento.v1.json")


def _carregar_roteamento() -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    dados: dict[str, Any] = json.loads(ARQUIVO_ROTEAMENTO.read_text(encoding="utf-8"))
    assinaturas = {tipo: tuple(nomes) for tipo, nomes in dados["x-assinaturas"].items()}
    return assinaturas, tuple(dados["x-processos"])


ASSINATURAS, PROCESSOS = _carregar_roteamento()

FRONTEIRA_DO_PROCESSO: Final[dict[str, Fronteira]] = {
    "audio-io": Fronteira.MICROFONE,
    "ui": Fronteira.UI_LOCAL,
    "executor": Fronteira.RETORNO_DE_TOOL,
}
"""Por onde o que cada processo publica entra no mundo (§3.1): o resto é interno.

`audio-io` fala pelo microfone, `ui` pelo dono, `executor` traz retorno de ferramenta. O
`trust` vem daqui, nunca do quadro — processo comprometido não se promove a `system`.
"""


@dataclass(slots=True)
class Assinante:
    nome: str
    canal: Canal
    cursor: int = 0
    cursor_pedido: int | None = None
    """O `desde_seq` que o cliente pediu no handshake, **antes** da conferência.

    `None` quando veio ilegível. A conferência contra o log acontece na admissão, não aqui:
    a thread de aceitação não pode tocar o SQLite (conexão de SQLite não atravessa thread).
    """


def _cursor_pedido(primeiro: dict[str, Any]) -> int | None:
    """`desde_seq` do handshake, sem confiar e sem levantar.

    `int(...)` direto aqui derrubava a **thread de aceitação** quando o campo não era número,
    e thread de aceitação morta significa que nenhum processo conecta mais ao barramento pelo
    resto da sessão — o sintoma aparecia como "ninguém conecta", não como handshake inválido.
    """
    bruto = primeiro.get("desde_seq", 0)
    if isinstance(bruto, bool) or not isinstance(bruto, int | float | str):
        return None
    try:
        pedido = int(bruto)
    except (TypeError, ValueError):
        return None
    return max(pedido, 0)


@dataclass(slots=True)
class Corretor:
    """Barramento em processo: aceita, valida, registra, classifica e entrega."""

    raiz: Path
    session_id: str
    log: LogDeEventos
    dono: DonoDoEpoch
    percepcao: Callable[[Envelope, int], list[Envelope]] | None = None
    """Reação local do `agentd` (percepção e S1) — a única que roda dentro do corretor."""

    fila: FilaDePrioridade = field(default_factory=FilaDePrioridade)
    assinantes: list[Assinante] = field(default_factory=list)
    recusados: list[str] = field(default_factory=list)
    _seqs: dict[str, int] = field(default_factory=dict, init=False)
    _novos: queue.Queue[Assinante] = field(default_factory=queue.Queue, init=False)
    _servidor: ServidorDoBarramento | None = field(default=None, init=False)
    _parar: threading.Event = field(default_factory=threading.Event, init=False)

    # --- ciclo de vida ------------------------------------------------------------
    def abrir(self) -> None:
        self._servidor = ServidorDoBarramento(self.raiz)
        threading.Thread(target=self._aceitar_sempre, name="aceitar", daemon=True).start()

    def fechar(self) -> None:
        self._parar.set()
        for assinante in self.assinantes:
            assinante.canal.fechar()
        if self._servidor is not None:
            self._servidor.fechar()

    def _aceitar_sempre(self) -> None:
        servidor = self._servidor
        if servidor is None:
            return
        while not self._parar.is_set():
            try:
                canal = servidor.aceitar()
            except OSError:
                return
            primeiro = canal.receber(timeout=5.0)
            if primeiro is None or primeiro.get("registro") not in PROCESSOS:
                canal.fechar()
                continue
            nome = str(primeiro["registro"])
            canal.nome = nome
            canal.enviar(
                {"ack": nome, "session_id": self.session_id, "epoch": self.dono.epoch_atual}
            )
            # A conexão nasce aqui, mas entra em serviço na thread principal: o log é
            # SQLite e conexão de SQLite não atravessa thread.
            self._novos.put(
                Assinante(nome=nome, canal=canal, cursor_pedido=_cursor_pedido(primeiro))
            )

    def _conferir_cursor(self, assinante: Assinante) -> None:
        """Confere o `desde_seq` do handshake contra o log **desta** sessão (§3.1, F0-03 b).

        O cursor vinha do cliente e era usado como verdade. `_repor` filtra
        `registro.seq <= cursor`, então um cursor acima de tudo que existe fazia a reposição
        entregar **nada**, sem erro em lugar nenhum: o `PolicyDecision` que esperava consumo
        nunca chegava e o `ToolCall` ficava em voo para sempre. Pior no adversário: bastava
        pedir alto para ficar cego a um tipo específico e estragar a auditoria de quem observa.

        Cursor que não cabe no log é tratado como **pedido do começo** — repor demais é
        idempotente do lado de quem recebe (o `executor` tem idempotência por `call_id`),
        repor de menos é evento perdido.
        """
        teto = self.log.maior_seq(session_id=self.session_id)
        pedido = assinante.cursor_pedido
        if pedido is None:
            self.recusados.append(
                f"{assinante.nome}: desde_seq ilegível no handshake; reposição do começo"
            )
            assinante.cursor = 0
            return
        if pedido > teto:
            self.recusados.append(
                f"{assinante.nome}: desde_seq {pedido} passa do maior seq da sessão "
                f"({teto}); reposição do começo"
            )
            assinante.cursor = 0
            return
        assinante.cursor = pedido

    def _repor(self, assinante: Assinante) -> None:
        """Reenvia do log o que o processo perdeu enquanto estava fora (aceite F0-03 b)."""
        for registro in self.log.ler(session_id=self.session_id):
            if registro.seq <= assinante.cursor:
                continue
            if assinante.nome not in ASSINATURAS.get(str(registro.envelope.type), ()):
                continue
            self._entregar(assinante, registro.envelope, registro.seq, Veredito.ACEITAR)

    # --- laço principal -----------------------------------------------------------
    def passo(self, timeout: float = 0.05) -> int:
        """Um giro: admite quem chegou, lê o que veio, roteia o que a fila tiver."""
        self._admitir_novos()
        canais = {a.canal.conexao: a for a in self.assinantes}
        if canais:
            for conexao in wait(list(canais), timeout=timeout):
                assinante = canais[conexao]  # type: ignore[index]
                quadro = assinante.canal.receber()
                if quadro is None:
                    self.assinantes.remove(assinante)
                    assinante.canal.fechar()
                    continue
                self._receber_publicacao(assinante, quadro)
        return self._drenar()

    def _admitir_novos(self) -> None:
        while True:
            try:
                assinante = self._novos.get_nowait()
            except queue.Empty:
                return
            self.assinantes.append(assinante)
            self._conferir_cursor(assinante)
            self._repor(assinante)

    def _receber_publicacao(self, assinante: Assinante, quadro: dict[str, Any]) -> None:
        bruto = quadro.get("publicar")
        if not isinstance(bruto, dict):
            self.recusados.append(f"{assinante.nome}: quadro sem 'publicar'")
            return
        fronteira = FRONTEIRA_DO_PROCESSO.get(assinante.nome, Fronteira.INTERNA)
        try:
            envelope = receber(bruto, fronteira).envelope
        except ErroDeContrato as erro:
            # Recusar, nunca ignorar: fica registrado com o nome de quem tentou.
            self.recusados.append(f"{assinante.nome}: {erro}")
            return
        if envelope.source != assinante.nome and not envelope.source.startswith("mcp:"):
            self.recusados.append(f"{assinante.nome} tentou publicar como {envelope.source!r}")
            return
        self.publicar(envelope)

    def publicar(self, envelope: Envelope) -> None:
        """Grava no log e enfileira. O log recebe tudo, inclusive o que será descartado."""
        registro = self.log.anexar(envelope)
        self._seqs[envelope.event_id] = registro.seq
        try:
            self.fila.publicar(envelope)
        except FilaCheia as erro:
            self.recusados.append(f"fila cheia: {erro}")

    def _drenar(self) -> int:
        entregues = 0
        while (envelope := self.fila.retirar()) is not None:
            veredito = self.dono.classificar(envelope)
            if envelope.type is Tipo.CANCEL:
                self.fila.descartar_epoch(
                    int(envelope.payload["epoch_invalidado"]), manter=TIPOS_DE_AUDITORIA
                )
            if veredito is Veredito.DESCARTAR:
                continue
            seq = self._seq_de(envelope)
            for assinante in list(self.assinantes):
                if assinante.nome in ASSINATURAS.get(str(envelope.type), ()):
                    self._entregar(assinante, envelope, seq, veredito)
                    entregues += 1
            if self.percepcao is not None and veredito is not Veredito.SO_AUDITORIA:
                for resposta in self.percepcao(envelope, seq):
                    self.publicar(resposta)
        return entregues

    def _seq_de(self, envelope: Envelope) -> int:
        return self._seqs.get(envelope.event_id, 0)

    def _entregar(self, assinante: Assinante, envelope: Envelope, seq: int, v: Veredito) -> None:
        try:
            assinante.canal.enviar({"evento": envelope.para_dict(), "seq": seq, "veredito": str(v)})
        except OSError:
            self.assinantes.remove(assinante)
            assinante.canal.fechar()
            return
        assinante.cursor = max(assinante.cursor, seq)

    # --- utilidades ---------------------------------------------------------------
    def validar_publicacao(self, bruto: dict[str, Any]) -> Envelope:
        return Envelope.de_dict(validar_bruto(bruto))
