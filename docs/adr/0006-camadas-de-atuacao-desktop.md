# ADR-0006 — Atuar no desktop por camadas: API > protocolo > acessibilidade > DOM > pixels

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** arquiteto

## Contexto
Coordenadas de tela não têm semântica: quebram com DPI, idioma, foco, modal, multi-monitor e tema; e a tela é conteúdo não confiável, portanto canal de prompt injection (relatórios 02 e 04). Windows UI Automation expõe uma árvore de elementos e padrões de controle; no Linux, AT-SPI expõe a infraestrutura de acessibilidade por D-Bus. No Wayland, a rota legítima para entrada e captura é o portal `org.freedesktop.portal.RemoteDesktop`/`ScreenCast`, que pede consentimento do compositor e cria sessão explícita e revogável. No X11, XTEST sintetiza eventos sem esse consentimento — mais liberdade e mais risco.

## Decisão
Ordem obrigatória de tentativa: **(1)** API/integração oficial → **(2)** protocolo bem definido (D-Bus, MPRIS, xdg) → **(3)** árvore de acessibilidade (UIA / AT-SPI) → **(4)** navegador com DOM isolado → **(5)** tela + coordenadas. A camada 5 é fuga: no máximo 1–3 ações por vez, foco verificado antes de digitar, screenshot/observação registrados e parada imediata se a tela divergir do esperado. Wayland usa o portal; X11 roda em sessão dedicada, desligado quando ocioso, sem jamais elevar privilégio para contornar.

## Alternativas descartadas
- **Visão primeiro ("o agente vê a tela e clica"):** demonstra bem e falha em produção; é o anti-padrão identificado nos dois relatórios.
- **Shell genérico como atalho para UI:** uma injeção vira execução arbitrária.

## Consequências
- Cada capacidade de desktop declara `platforms` e tem teste por plataforma (F4).
- Sucesso é verificado por observação independente da ação (arquivo existe, elemento acessível mudou, API devolveu id) — não pela ausência de erro.
- Aplicativo sem API e sem acessibilidade decente é limitação declarada ao dono, não motivo para descer para pixels silenciosamente.

## Como invalidar
Uma camada melhor aparecer (p.ex. protocolo de automação padronizado no Wayland) — entra acima de pixels, nunca abaixo de confirmação.
