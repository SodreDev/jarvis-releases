"""Ferramental do corpus: rótulo de pausa, vozes de licença verificada e gerador sintético.

Mora em `src/` pelo mesmo motivo que `jarvis.memoryd.importacao`: é lógica com teste, e as
ferramentas de `tools/` são só a linha de comando. **Não** está no caminho crítico dos sete
processos da §2 — nada em `audio-io`, `agentd` ou `s2` importa este pacote em produção.
"""
