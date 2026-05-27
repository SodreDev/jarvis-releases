"""plugins — Sistema de extensão dinâmica do JARVIS.

Cada plugin é uma pasta sob `plugins/` com:
  - manifest.json: {"name", "version", "entry", "permissions": [], "tools": [...]}
  - <entry>.py: módulo Python com funções registradas em manifest["tools"]

O loader importa o módulo e registra cada função no tool_registry do JARVIS.
"""
