"""JARVIS — pacote raiz da nova arquitetura modular.

Este pacote vive em paralelo com a estrutura plana legada (`main.py`,
`comandos/`, `core/`, etc.) e será preenchido gradualmente conforme
o roadmap em `planning/roadmap/`.

Princípios (ver `planning/roadmap/PRINCIPIOS.md`):
- Default OFF para toda feature opt-in.
- Não-interferência com o usuário (teclado/mouse).
- Identidades separadas: perfis `jarvis` (bot) e `user` (opt-in).
- Compatibilidade: nada da arquitetura legada é removido.
"""

__version__ = "0.1.0-modular"

__all__ = ["__version__"]
