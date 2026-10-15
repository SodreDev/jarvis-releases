# Regras do Orchestrator — projeto Jarvis

Este projeto é gerenciado pelo Orchestrator e tem MEMÓRIA SEMÂNTICA
(ChromaDB + reranker): regras do dono deste projeto, memórias globais do
dono (valem em todo projeto) e memórias das IAs, cada uma com autor. A
cada prompt chega um índice do que importa para ele.

- Antes de alterar qualquer coisa, consulte a tool MCP `retrieve_memory`
(project: "Jarvis"): ferramentas que alteram o projeto ficam
bloqueadas pelo hook até a primeira consulta da sessão.
- Regras de segurança são IMPOSITIVAS: tool calls que as violem serão
bloqueadas pelo hook PreToolUse.
- Raciocine pela memória, não por contexto gigante: `retrieve_memory`
antes de supor; memória grande, só o pedaço (`get_memory_chunk`).
- Documento grande (.md, spec, log): leia em etapas com a tool MCP
`doc_read` (sumário primeiro, depois o pedaço), nunca inteiro.
- Decisão fechada sobre um texto (um log tem erro? o teste passou? o
arquivo trata de X?): pergunte ao Jev com a tool MCP `jev` — várias
perguntas numa chamada — em vez de ler o texto inteiro.
- Precisa de uma imagem (foto de produto, ilustração, ícone, banner)?
Use a tool MCP `image_generate` com um brief concreto e `destino`
no projeto — nunca deixe placeholder. Logo, ícone, diagrama ou
banner com texto exato: desenhe em SVG/HTML e gere o PNG com
`image_render` (experimental, sem cota).
- TERMINOU a tarefa que o orquestrador te passou? Chame a tool MCP
`cli_ping` (resumo do que fez + estado pronto/precisa_decisao/falhou)
ANTES de parar. É o que faz ele voltar a iterar: sem o seu ping o
projeto fica parado esperando você.
- Registre o que aprender com `store_memory` e decisões relevantes com
`log_decision`.
- Não sabe algo, ou dá para fazer ou testar melhor? Pesquise antes de
implementar, e compare arquiteturas em decisões de estrutura.
