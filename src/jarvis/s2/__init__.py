"""s2 — reasoner acordado por evento (SPEC §2).

Responsabilidade: atualiza o estado de trabalho (§3.4), planeja, escolhe
capacidade dentro da shortlist autorizada, redige resposta.

Proibições: não autoriza, não bloqueia mídia, não publica fala de epoch morto,
nunca roda em loop cego.
"""
