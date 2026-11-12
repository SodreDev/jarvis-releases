"""Executar um envio no WhatsApp Web (ADR-0060, fatia D), só depois do «pode» do `Guardiao`.

O passo a passo (docs/redes-sociais-riscos.md §4):

1. o guardião decide (lista, ausente, teto, ritmo, conteúdo, pausa);
2. espera a reação (20 a 90 s, aleatório) — nunca instantâneo;
3. abre o chat do contato pelo nome exato (homônimo ou nenhum: recusa);
4. lê o cabeçalho e confere nome e telefone (`conferir_contato`);
5. digita por caractere, com o ritmo log-normal, pela entrada confiável (CDP) da extensão;
6. confere o cabeçalho de novo e só então aperta Enter;
7. solta o depurador **sempre** (`social.soltar`), deu certo ou não, e registra.

Qualquer recusa ou falha no meio: não envia, registra e devolve o motivo (quem chamou notifica o
dono). Nunca tenta de novo sozinho. O cancelamento (o «parar envios» do dono) é conferido entre
cada passo e corta antes do Enter."""

from __future__ import annotations

import contextlib
import random
import time
from collections.abc import Callable
from typing import Any, Protocol

from jarvis.social.envio import (
    Cabecalho,
    EnvioRecusado,
    Guardiao,
    PedidoDeEnvio,
    conferir_contato,
    em_pedacos,
    reacao,
    ritmo,
)

REDE: str = "whatsapp"


class PonteDeEnvio(Protocol):
    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]: ...


class EnvioCancelado(EnvioRecusado):
    def __init__(self) -> None:
        super().__init__("cancelado", "o dono parou os envios")


class Enviador:
    def __init__(
        self,
        ponte: PonteDeEnvio,
        guardiao: Guardiao,
        *,
        familia: Callable[[], str],
        aleatorio: random.Random | None = None,
        dormir: Callable[[float], None] = time.sleep,
        cancelado: Callable[[], bool] = lambda: False,
    ) -> None:
        self._ponte = ponte
        self._guardiao = guardiao
        self._familia = familia
        self._aleatorio = aleatorio or random.SystemRandom()
        self._dormir = dormir
        self._cancelado = cancelado

    def _conferir_cancelado(self) -> None:
        if self._cancelado():
            raise EnvioCancelado()

    def _esperar(self, segundos: float) -> None:
        """Dorme em fatias curtas, para o «parar» do dono valer no meio da espera."""
        restante = segundos
        while restante > 0:
            self._conferir_cancelado()
            passo = min(1.0, restante)
            self._dormir(passo)
            restante -= passo
        self._conferir_cancelado()

    def _cabecalho(self, familia: str) -> Cabecalho:
        dados = self._ponte.pedir("social.cabecalho", familia, rede=REDE)
        return Cabecalho(
            nome=str(dados.get("nome", "")),
            telefone=str(dados.get("telefone", "")),
            grupo=bool(dados.get("grupo", False)),
            ambiguo=bool(dados.get("ambiguo", False)),
        )

    def enviar(self, pedido: PedidoDeEnvio) -> str:
        """`enviado`, ou levanta `EnvioRecusado` com o motivo (já registrado no log)."""
        familia = self._familia()
        anexado = False
        try:
            contato = self._guardiao.decidir(pedido)
            self._esperar(reacao(self._aleatorio))
            contato = self._guardiao.decidir(pedido)  # o teto e o ritmo valem na hora do envio
            self._conferir_cancelado()
            anexado = True  # daqui em diante a extensão pode ter anexado: o fim sempre solta
            aberto = self._ponte.pedir(
                "social.abrirConversa", familia, rede=REDE, nome=contato.nome
            )
            if aberto.get("ambiguo"):
                raise EnvioRecusado("ambiguo", "há mais de uma conversa com este nome")
            conferir_contato(contato, self._cabecalho(familia))
            for pedaco in em_pedacos(ritmo(pedido.texto, self._aleatorio)):
                self._conferir_cancelado()
                self._ponte.pedir(
                    "social.digitar",
                    familia,
                    rede=REDE,
                    texto="".join(t.texto for t in pedaco),
                    atrasos=[t.atraso_ms for t in pedaco],
                )
            self._conferir_cancelado()
            conferir_contato(contato, self._cabecalho(familia))  # reconferir antes do Enter
            self._ponte.pedir("social.enviar", familia, rede=REDE)
        except EnvioRecusado as recusa:
            self._guardiao.anotar(pedido, f"recusado:{recusa.codigo}")
            raise
        except Exception as erro:
            self._guardiao.anotar(pedido, "recusado:falha")
            raise EnvioRecusado("falha", f"o envio falhou na página ({erro})") from None
        finally:
            if anexado:
                # A extensão também solta sozinha no prazo dela (120 s).
                with contextlib.suppress(Exception):
                    self._ponte.pedir("social.soltar", familia, rede=REDE)
        self._guardiao.anotar(pedido, "enviado")
        return "enviado"


__all__ = ["Enviador", "EnvioCancelado", "PonteDeEnvio"]
