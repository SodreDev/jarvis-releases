"""A caixa de scripts isolada (ADR-0050): Python ou JS do Jarvis sem rede, sem os arquivos do
dono, com limites. Fica FORA do pacote `executor` de propósito — ela cria processo (bubblewrap ou
podman), e o `executor` tem a invariante de não ter caminho para shell (F0-03, test_sem_shell). O
executor só importa e chama `CaixaDeScript`; o processo nasce aqui, num componente à parte."""

from jarvis.caixa.scripts import CaixaDeScript, Limites, Linguagem, Resultado, backend_disponivel

__all__ = ["CaixaDeScript", "Limites", "Linguagem", "Resultado", "backend_disponivel"]
