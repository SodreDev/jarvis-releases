"""policy — Policy Decision Point determinístico (SPEC §5, ADR-0003).

Responsabilidade: `permitir | confirmar | negar` a partir de `tool_id`,
argumentos normalizados, identidade, cenário, classe de dado e destino; grants
com TTL e escopo.

Proibições: não consulta o LLM; não aceita `allowed_tools` vindo de conteúdo.
"""
