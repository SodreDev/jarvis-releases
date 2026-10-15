"""Fronteira de entrada: quem recebe do mundo é quem atribui `trust` (§3.1, P6).

Nenhum emissor remoto rotula a própria confiança. O `trust` que vier no evento cru é
**descartado** e substituído pelo da fronteira por onde o evento entrou; a tentativa fica
registrada para auditoria.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jarvis.barramento.contrato import validar_bruto
from jarvis.barramento.envelope import Envelope, Trust


class Fronteira(StrEnum):
    """Por onde o evento entrou. É o que decide o `trust` — não o conteúdo."""

    INTERNA = "interna"
    """Processo nosso, no mesmo computador, por IPC autenticado."""

    VOZ_DO_DONO = "voz_do_dono"
    MICROFONE = "microfone"
    UI_LOCAL = "ui_local"
    RETORNO_DE_TOOL = "retorno_de_tool"
    SERVIDOR_MCP = "servidor_mcp"
    TELA_OU_WEB = "tela_ou_web"


TRUST_DA_FRONTEIRA: dict[Fronteira, Trust] = {
    Fronteira.INTERNA: Trust.SYSTEM,
    Fronteira.VOZ_DO_DONO: Trust.USER_VOICE,
    Fronteira.MICROFONE: Trust.USER_VOICE,
    Fronteira.UI_LOCAL: Trust.USER_UI,
    Fronteira.RETORNO_DE_TOOL: Trust.TOOL_RESULT,
    Fronteira.SERVIDOR_MCP: Trust.THIRD_PARTY,
    Fronteira.TELA_OU_WEB: Trust.THIRD_PARTY,
}


@dataclass(frozen=True, slots=True)
class Recebido:
    """Evento aceito na borda, com o que foi corrigido no caminho."""

    envelope: Envelope
    fronteira: Fronteira
    trust_declarado: str | None
    """O que o emissor tentou declarar, se tentou algo diferente. Vai para o log."""

    @property
    def rebaixado(self) -> bool:
        return self.trust_declarado is not None


def receber(bruto: dict[str, Any], fronteira: Fronteira) -> Recebido:
    """Recebe um evento cru de fora e devolve um envelope validado e rotulado.

    O `trust` é sempre o da fronteira. Evento de servidor MCP continua `third_party`
    mesmo que o campo diga `system` (aceite F0-02 f).
    """
    copia = dict(bruto)
    declarado = copia.get("trust")
    trust = TRUST_DA_FRONTEIRA[fronteira]
    copia["trust"] = str(trust)

    validado = validar_bruto(copia)
    envelope = Envelope.de_dict(validado)
    tentou_outro = isinstance(declarado, str) and declarado != str(trust)
    return Recebido(
        envelope=envelope,
        fronteira=fronteira,
        trust_declarado=str(declarado) if tentou_outro else None,
    )
