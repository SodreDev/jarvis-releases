# ADR-0003 — Catálogo tipado de capacidades; o modelo propõe, o código autoriza

**Data:** 2026-10-15 · **Estado:** aceita (decisão do dono) · **Decide:** dono

## Contexto
O Jarvis antigo disparava ação por frase/keyword: cobertura explode, variação natural erra e a ação fica impossível de auditar (relatório 02, anti-padrões). No outro extremo, dar shell, navegador logado e arquivos pessoais a um LLM transforma uma injeção indireta em exfiltração. O contrato de function calling é um laço — modelo emite `tool_call`, executor valida e devolve `tool_result` — e não uma permissão de execução (relatório 04). Anotações MCP (`readOnlyHint`, `destructiveHint`) são declarações do servidor e podem mentir.

## Decisão
Toda ação passa por um **manifesto de capacidade versionado** (nome, descrição, JSON Schema estrito, pré-condição, pós-condição verificável, capability de ACL, classe de risco, reversibilidade, egress, confirmação, plataformas, testes). O LLM escolhe dentro de uma shortlist autorizada de 5–12; um **PDP determinístico fora do modelo** resolve `permitir | confirmar | negar` com os argumentos já normalizados; um executor isolado injeta credencial e verifica a pós-condição. Campos de política nunca vêm do LLM nem de servidor remoto.

## Alternativas descartadas
- **Roteador por palavra-chave:** o anti-padrão que estamos saindo.
- **Catálogo inteiro no prompt:** caro e confunde tools vizinhas; a orientação pública é <20 funções visíveis e <10 por namespace adiado.
- **Confiar nas anotações MCP:** dica de UX, não enforcement.

## Consequências
- Proibido `run_command`/`do_anything`/shell irrestrito — rejeitado em revisão.
- Toda tool de escrita precisa de `dry_run`, recibo antes/depois e desfazer.
- A matriz de confirmação (SPEC §5.3) é código, com teste de negação para cada classe.
- Custo: cada capacidade nova exige manifesto, teste de contrato e teste de pós-condição.

## Como invalidar
Não há condição prevista. Afrouxar isto significaria aceitar que uma página web possa agir na máquina do dono.
