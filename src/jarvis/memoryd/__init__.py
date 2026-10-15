"""memoryd — ledger e índice trocável (SPEC §6, ADR-0005).

Responsabilidade: ledger SQLite como fonte de verdade, outbox de indexação,
recuperação atrás de interface trocável, consolidação em segundo plano.

Proibições: não indexa no caminho crítico da voz, não promove procedimento a
`approved`.
"""
