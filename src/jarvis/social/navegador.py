"""A ponte do monitor das redes com o host do navegador (ADR-0060).

Só dois pedidos passam por aqui, `social.abrir` e `social.estado`, e a assinatura de eventos. O
resto do vocabulário do navegador existe, mas o monitor não o usa: ele não age na página."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from jarvis.navegador.cliente import AssinaturaUnix, ClienteDoNavegador, TransporteUnix
from jarvis.navegador.protocolo import validar_estado_social

PEDIDOS_DO_MONITOR: Final = frozenset({"social.abrir", "social.estado"})


class PonteDoNavegador:
    """`assinar` e `pedir` sobre o socket do host (`TransporteUnix`)."""

    def __init__(self, transporte: TransporteUnix) -> None:
        self._transporte = transporte

    @classmethod
    def do_ambiente(cls, ambiente: Mapping[str, str]) -> PonteDoNavegador:
        """O socket em `$XDG_RUNTIME_DIR` deste ambiente. Só a janela de verdade monta esta ponte
        (`jarvis.gui.principal`): os testes passam uma falsa, nunca o navegador do dono."""
        return cls(TransporteUnix.do_ambiente(ambiente))

    def assinar(self, navegador: str = "") -> AssinaturaUnix:
        return self._transporte.assinar(navegador)

    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]:
        if metodo not in PEDIDOS_DO_MONITOR:
            raise ValueError(f"o monitor das redes só pede {sorted(PEDIDOS_DO_MONITOR)}")
        cliente = ClienteDoNavegador(self._transporte)
        cliente.navegador = navegador
        resultado = cliente.chamar(metodo, **params)
        if metodo == "social.estado":
            estado = validar_estado_social({"rede": params["rede"], **resultado})
            return {k: v for k, v in estado.items() if k not in ("evento", "rede")}
        return resultado


__all__ = ["PEDIDOS_DO_MONITOR", "PonteDoNavegador"]
