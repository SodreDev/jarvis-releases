"""Responder no WhatsApp quando o dono está ausente (ADR-0060, fatia D).

O monitor informa quem tem mensagem não lida; para cada conversa de um contato da lista
permitida, com o envio automático e o «ausente» ligados, este fio:

1. confere no guardião o que dá para conferir sem texto (lista, ausente, teto, ritmo, pausa);
2. pede ao motor o texto (`redator`), instruído pelas memórias fixas;
3. entrega ao `Enviador`, que confere tudo de novo e envia — um por vez, nunca em rajada.

Qualquer «não» vira notificação ao dono («o Jarvis não respondeu a Ana: …»). Cada conversa é
respondida uma vez por rodada de não lidas: enquanto a contagem dela não zerar (o dono, ou o
contato, leu), não há segunda resposta."""

from __future__ import annotations

import queue
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.social.enviar import Enviador
from jarvis.social.envio import EnvioRecusado, Guardiao, PedidoDeEnvio, Permitido
from jarvis.social.monitor import EstadoDaPagina

REDE = "whatsapp"
TEXTO_DE_CONFERENCIA = "Oi! Ele está ausente agora e responde assim que puder."
"""Só para o guardião conferir lista, teto e ritmo antes de gastar o motor; nunca é enviado."""


def _normal(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).split())


@dataclass(frozen=True, slots=True)
class Resultado:
    nome: str
    enviado: bool
    motivo: str = ""


class RespostaAusente:
    def __init__(
        self,
        *,
        guardiao: Guardiao,
        enviador: Enviador,
        redator: Callable[[str], str | None] | None,
        permitidos: Callable[[], tuple[Permitido, ...]],
        ao_resultado: Callable[[Resultado], None],
    ) -> None:
        self._guardiao = guardiao
        self._enviador = enviador
        self._redator = redator
        """Da conversa aberta (o motor do Jarvis). Sem ela, `None`: o Jarvis só notifica."""
        self._permitidos = permitidos
        self._ao_resultado = ao_resultado
        self._respondidas: set[str] = set()
        self._fila: queue.Queue[tuple[str, Permitido] | None] = queue.Queue()
        self._fio: threading.Thread | None = None
        self._trava = threading.Lock()

    def trocar_redator(self, redator: Callable[[str], str | None] | None) -> None:
        self._redator = redator

    def ao_estado(self, pagina: EstadoDaPagina) -> None:
        """Do fio do monitor: quem tem não lida agora. Só enfileira; o trabalho é no fio próprio."""
        if pagina.rede != REDE or not pagina.logado or pagina.alerta:
            return
        com_nao_lidas = {_normal(c.nome) for c in pagina.conversas if c.nao_lidas > 0}
        with self._trava:
            self._respondidas &= com_nao_lidas  # leu: a próxima mensagem pode ser respondida
        lista = self._permitidos()
        for conversa in pagina.conversas:
            chave = _normal(conversa.nome)
            if conversa.nao_lidas <= 0:
                continue
            with self._trava:
                if chave in self._respondidas:
                    continue
            candidatos = [p for p in lista if _normal(p.nome) == chave]
            if len(candidatos) != 1:
                continue  # fora da lista (ou homônimo): o monitor já notificou o dono
            with self._trava:
                self._respondidas.add(chave)
            self._fila.put((conversa.nome, candidatos[0]))
        self._garantir_o_fio()

    def _garantir_o_fio(self) -> None:
        if self._fio is None or not self._fio.is_alive():
            self._fio = threading.Thread(target=self._rodar, name="jarvis-ausente", daemon=True)
            self._fio.start()

    def parar(self) -> None:
        self._fila.put(None)

    def _rodar(self) -> None:
        while True:
            item = self._fila.get()
            if item is None:
                return
            nome, contato = item
            self._ao_resultado(self._responder(nome, contato))

    def _pedido(self, contato: Permitido, texto: str) -> PedidoDeEnvio:
        return PedidoDeEnvio(
            rede=REDE,
            nome=contato.nome,
            telefone=contato.telefone,
            texto=texto,
            escreveu_primeiro=True,
        )

    def _responder(self, nome: str, contato: Permitido) -> Resultado:
        try:
            self._guardiao.decidir(self._pedido(contato, TEXTO_DE_CONFERENCIA))
        except EnvioRecusado as recusa:
            return Resultado(nome, False, recusa.frase)
        redator = self._redator
        if redator is None:
            return Resultado(nome, False, "a conversa do Jarvis está fechada: sem quem redija")
        texto = redator(contato.nome)
        if texto is None:
            return Resultado(nome, False, "a conversa do Jarvis está fechada: sem quem redija")
        if not texto:
            return Resultado(nome, False, "o Jarvis não soube o que responder com as suas memórias")
        try:
            self._enviador.enviar(self._pedido(contato, texto))
        except EnvioRecusado as recusa:
            return Resultado(nome, False, recusa.frase)
        return Resultado(nome, True)


__all__ = ["RespostaAusente", "Resultado"]
