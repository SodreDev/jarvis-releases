"""Cliente MCP (ADR-0052): o Jarvis consome servidores MCP que o dono listar.

Fica FORA dos pacotes `executor` e `policy` de propósito — o cliente abre um processo filho (o
servidor MCP por stdio), e aqueles pacotes mantêm a invariante de não ter caminho para shell
(F0-03, `tests/unit/processos/test_sem_shell.py`). Cada ferramenta de um servidor só existe depois
de **promovida** a um manifesto nosso (ADR-0010): `risk_class`, `confirmation`, `data_egress`,
`access_level_min` e o `tier` são do repositório e da configuração do dono, nunca do servidor. A
saída é sempre `third_party`/`untrusted`: dado, nunca ordem.
"""

from jarvis.mcp.config import ServidorMcp, carregar_mcp
from jarvis.mcp.promocao import McpProibida, promover

__all__ = ["McpProibida", "ServidorMcp", "carregar_mcp", "promover"]
