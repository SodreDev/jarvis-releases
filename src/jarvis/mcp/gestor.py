"""O gestor dos servidores MCP (ADR-0052): abre os que o dono ligou, promove as tools a
manifestos nossos e roteia as chamadas. Cada tool promovida entra no catálogo em memória com o
tier que o dono deu; o executor a liga ao PDP e ao guarda de contexto (ADR-0049).

Conteúdo que volta do servidor é **dado** (`untrusted`): o gestor nunca o lê como instrução.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.manifesto.validador import ManifestoInvalido, validar_manifesto
from jarvis.mcp.cliente import ClienteMcp, ErroMcp, Transporte, TransporteStdio, identidade
from jarvis.mcp.config import ServidorMcp
from jarvis.mcp.promocao import McpProibida, promover
from jarvis.politica.catalogo import Capacidade, de_dados

FabricaDeTransporte = Callable[[ServidorMcp], Transporte]


def _stdio(servidor: ServidorMcp) -> Transporte:
    return TransporteStdio(comando=servidor.comando)


@dataclass(slots=True)
class _Ligado:
    servidor: ServidorMcp
    cliente: ClienteMcp
    pino: str
    tools: dict[str, str]  # tool_id do catálogo → nome remoto


@dataclass(slots=True)
class GestorMcp:
    """Os servidores ligados, as tools promovidas e o roteamento. Sem estado entre `descobrir`."""

    servidores: Sequence[ServidorMcp]
    fabrica: FabricaDeTransporte = _stdio
    aviso: Callable[[str], None] = lambda _m: None
    manifestos: dict[str, dict[str, Any]] = field(default_factory=dict)
    capacidades: dict[str, Capacidade] = field(default_factory=dict)
    _ligados: list[_Ligado] = field(default_factory=list)
    _por_tool: dict[str, _Ligado] = field(default_factory=dict)

    def descobrir(self) -> None:
        """Abre cada servidor ligado, lista e promove as tools. Um servidor que falha não derruba
        os outros; uma tool proibida ou inválida é pulada com aviso (nunca entra no catálogo)."""
        for servidor in self.servidores:
            if not servidor.ligado:
                continue
            try:
                cliente = ClienteMcp(transporte=self.fabrica(servidor))
                tools = cliente.listar_tools()
            except (ErroMcp, OSError) as erro:
                self.aviso(f"MCP {servidor.nome}: não abriu ({erro})")
                continue
            ligado = _Ligado(
                servidor=servidor, cliente=cliente, pino=identidade(servidor), tools={}
            )
            for tool in tools:
                self._promover(servidor, tool, ligado)
            self._ligados.append(ligado)

    def _promover(self, servidor: ServidorMcp, tool: Mapping[str, Any], ligado: _Ligado) -> None:
        nome = str(tool.get("name", ""))
        try:
            manifesto = promover(servidor, dict(tool))
            validar_manifesto(manifesto, origem=f"mcp:{servidor.nome}")
            capacidade = de_dados(manifesto, origem=f"mcp:{servidor.nome}")
        except (McpProibida, ManifestoInvalido) as erro:
            self.aviso(f"MCP {servidor.nome}: tool {nome!r} não entrou ({erro})")
            return
        tool_id = manifesto["id"]
        self.manifestos[tool_id] = manifesto
        self.capacidades[tool_id] = capacidade
        ligado.tools[tool_id] = nome
        self._por_tool[tool_id] = ligado

    def chamar(self, tool_id: str, argumentos: Mapping[str, Any]) -> dict[str, Any]:
        """Roteia a chamada ao servidor da tool e devolve o resultado **como dado**."""
        ligado = self._por_tool.get(tool_id)
        if ligado is None:
            raise ErroMcp(f"{tool_id} não é de um servidor MCP ligado")
        nome = ligado.tools[tool_id]
        resultado = ligado.cliente.chamar_tool(nome, argumentos)
        return {"servidor": ligado.servidor.nome, "tool": nome, "resultado": resultado}

    def fechar(self) -> None:
        for ligado in self._ligados:
            ligado.cliente.fechar()
        self._ligados.clear()
        self._por_tool.clear()
