# Foco de janelas num KWin 6 virtual com dois monitores

**Gerado por** `tools/harness_foco.py` (não editar à mão). **Data:** 2026-10-21. KWin `6.7.5`, kdotool `v0.3.0`, 1280×720 em cada saída virtual.

> KWin de verdade, mas **virtual**: janelas de teste em Qt, sem o painel nem a área de trabalho do Plasma, sem os monitores físicos e sem o Brave de verdade. Na sessão do dono, `tools/diagnostico_foco.py`.

## Conferências

| # | conferência | ok |
|---:|---|:---:|
| 1 | as três janelas de teste abriram no KWin virtual | sim |
| 2 | a leitura nova diz os dois monitores, o principal primeiro | sim |
| 3 | o Jarvis é a ativa (a do teclado), no segundo monitor | sim |
| 4 | o Brave (Wayland, classe brave-browser) é a da frente do monitor principal | sim |
| 5 | a janela XWayland do Brave tem a classe brave-browser e o monitor dela | sim |
| 6 | window.focused responde a ativa e o Brave na frente do principal | sim |
| 7 | ANTES: a leitura de antes só sabe a ativa — o Brave fica sem monitor e «atrás» | sim |
| 8 | o KWin aceita o pedido de foco | sim |
| 9 | o Brave ficou ativo pelo KWin (no Wayland o navegador não pega o foco sozinho) | sim |
| 10 | sem janela ativa, a leitura nova continua listando e diz que não há foco | sim |
| 11 | ANTES: sem janela ativa, a busca encadeada falha inteira (a lista voltava vazia) | sim |
| 12 | o kdotool cru, sem KDE_SESSION_VERSION, recusa rodar (o Jarvis completa a variável) | sim |
| 13 | o diagnóstico de 1 comando mostra a ativa e a da frente de cada monitor | sim |

## Tempo de uma leitura (30 vezes cada, intercaladas)

| leitura | p50 | p95 | o que traz |
|---|---:|---:|---|
| nova (`kdotool kwinscript`) | 4.7 ms | 5.7 ms | ativa, monitores, pilha, área de trabalho, minimizada |
| de antes (busca encadeada) | 5.6 ms | 6.5 ms | ativa (quebra sem ela), sem monitor nem pilha |
