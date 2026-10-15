"""J.A.R.V.I.S — assistente pessoal desktop (SPEC v0.1).

Sete áreas com fronteira de processo em torno de um barramento tipado
(ADR-0007): `audio_io`, `agentd`, `s2`, `policy`, `executor`, `memoryd`, `ui`.
A fronteira é o contrato de evento da §3, versionado em `schemas/`, não uma
biblioteca compartilhada.
"""

__all__ = ["__version__"]

__version__ = "0.0.0"
