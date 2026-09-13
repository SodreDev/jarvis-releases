# Plano 08 — MCP, Conectores & Plugins

## Estado Atual

- Tools registradas via decorator `@register` em [comandos/tool_registry.py](../../comandos/tool_registry.py).
- Nenhuma integração MCP (Model Context Protocol).
- Sem sistema de plugin externo (terceiros não podem adicionar tool sem editar o repo).

## Problema

- Para o JARVIS virar infra extensível, precisa aceitar plugins/conectores sem recompilar.
- MCP é padrão emergente (Anthropic, Microsoft) — preparar a arquitetura.

## Plano

### Conceito de conector

```python
# connectors/base.py
class Connector(Protocol):
    name: str
    version: str
    requires: list[str]                # permissões
    config_schema: dict                # JSON schema para config
    def setup(self, vault, config): ...
    def tools(self) -> list[ToolSpec]: ...
    def teardown(self): ...
```

Cada conector externo: pasta `plugins/<nome>/` com:
```
plugins/notion/
├── __init__.py
├── manifest.json
├── connector.py
└── README.md
```

### Discovery

- Boot: scan `plugins/` → carrega manifests → instancia conectores ativos (toggle por plugin).
- Tools expostas via `tool_registry` automaticamente.

### MCP — duas pontes

1. **MCP Server**: JARVIS expõe suas tools via MCP (stdio/SSE) — IDEs (VS Code, Cursor) podem usar JARVIS como tool provider.
2. **MCP Client**: JARVIS consome MCP servers de terceiros (Notion, GitHub, Slack via MCP).

### Arquitetura

```
mcp/
├── server.py          ← expõe tools internas via MCP protocol
├── client.py          ← consome MCP servers externos
├── registry.py        ← lista MCPs configurados
└── transports/
    ├── stdio.py
    └── sse.py
```

### Mapeamento tool ↔ MCP

- Tool interna → wrapper que segue MCP tool schema (name, description, parameters, returns).
- MCP tool externa → registrada dinamicamente no `tool_registry` ao conectar.

### Plugins de terceiros

- Manifesto declara permissões pedidas; engine de segurança (plano 09) valida na ativação.
- Sandboxing inicial: import isolado em subprocess (opcional, para plugins não-confiáveis).

### Conectores prioritários (ordem sugerida)

1. **GitHub** (issues, PRs, commits)
2. **Notion** (databases, pages)
3. **Google Calendar** (eventos, lembretes)
4. **Spotify** (já temos, virar conector formal)
5. **Steam** (status, biblioteca)
6. **Obsidian** (vault local)
7. **VSCode** (já tem `vscode_extension/` — formalizar via MCP)

## Decisões pendentes

1. **SDK MCP em Python**: usar `mcp` oficial (Anthropic) — recomendação sim.
2. **Plugin lifecycle**: hot-reload ou reboot? Recomendação: reboot inicial, hot-reload futuro.
3. **Plugins escritos em outras linguagens**: via MCP (linguagem-agnóstico) — caminho preferido.

## Riscos

- MCP é jovem — APIs podem mudar. Encapsular numa camada interna estável.
- Plugin maligno pode acessar vault. Mitigar: permissões + audit + sandbox.

## Referências de código

- [comandos/tool_registry.py](../../comandos/tool_registry.py) — base de extensão

## Histórico

- 2026-05-25 — Plano criado.
