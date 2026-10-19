"""Mouse e teclado virtuais do Jarvis (ADR-0027, fatia 4): entrada sintetizada pelo sistema.

Servem onde o DOM não serve — sites que proíbem automação (Instagram, WhatsApp Web) e qualquer
janela fora do navegador. É o recurso mais poderoso do catálogo, e por isso o mais cercado:

- **consentimento do dono no sistema**: o caminho padrão é o portal `RemoteDesktop`, em que o
  compositor mostra um diálogo e o dono pode revogar; o `uinput` é só reserva, e só ligado por ele;
- **foco conferido antes de cada ação**: terminal, gerenciador de senhas, banco, mensageiro, janela
  de autenticação ou foco desconhecido tornam a ação *perigosa* (o sim do dono, uma vez por ação);
- **limite de taxa** e **interruptor de parada** global, que o dono aciona e só o dono desfaz;
- vocabulário **fechado**: mover, clicar, digitar texto, apertar teclas de uma lista — sem `super`,
  sem `ctrl+alt`, sem atalho de sistema.
"""
