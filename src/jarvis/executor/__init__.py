"""executor — chamada isolada de capacidade (SPEC §2, §5.5).

Responsabilidade: valida schema, injeta credencial de menor privilégio, roda em
sandbox, confere pós-condição sobre descritor (não sobre string), devolve
observação rotulada `untrusted`.

Proibições: não infere intenção, não eleva privilégio, **não tem shell genérico**.
"""
