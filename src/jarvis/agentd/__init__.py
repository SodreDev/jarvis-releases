"""agentd — percepção, S1, dono do epoch e do barramento (SPEC §2).

Responsabilidade: ASR incremental, detector semântico de fim de turno, S1
(ouvir | backchannel | ceder | falar | cancelar), emissão e validação de `epoch`,
event log, prioridades P0–P4, coalescing.

Proibições: não executa capacidade, não escreve memória durável.
"""
