# ADR-0010 — Catálogo do v1 (arquivos, mídia, calendário, abrir apps) e MCP como cliente de saída não confiável

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** dono (escopo do v1), arquiteto (desenho do porto MCP)

## Contexto

Pendência Q3 fechada pelo dono: o v1 cobre **arquivos + mídia + calendário em rascunho**, e o escopo **cresce por níveis** — cada família nova entra com manifesto, testes e classe de risco, não por extensão informal de uma tool existente. O dono também quer que o Jarvis "atue como Jarvis de verdade": **abrir apps** e, depois, **falar com o Orchestrator (MCP)** e conectar a outros MCPs.

O relatório 04 já estabeleceu que anotação de servidor MCP (`readOnlyHint`, `destructiveHint`) é **dica, não enforcement**, e que o catálogo visível por turno deve ficar em 5–12 capacidades. O Orchestrator é um caso especialmente perigoso de servidor: ele tem `shell_exec`, `ssh_exec` e controle de CLIs — exatamente o tipo de "canivete suíço" proibido pela §4.

## Decisão

1. **Catálogo v1 por famílias tipadas:** núcleo de conversa (`status`, `ask_user`, `search_catalog`, `read_notification`, `cancel`), `files.*`, `apps.*`, `media.*`, `calendar.*` (leitura e rascunho), `system.read.*`. Nada de tool genérica; nada de shell.
2. **Abrir app é capacidade tipada, não linha de comando.** `apps.launch` resolve um `app_id` de um registro versionado derivado do índice do SO (`.desktop` no Linux, Menu Iniciar/AppX no Windows). Sem shell, sem `argv` livre, ambiente saneado, sem elevação. O único argumento opcional é um caminho que já passou pela checagem de raiz (ADR-0009). Abrir app que renderiza conteúdo de terceiro (navegador, e-mail) marca a sessão como contaminada e sobe o rigor.
3. **Calendário no v1 é leitura + rascunho local.** Criar rascunho não envia convite; qualquer envio é `egress_representacao` e confirma no momento do envio. O contrato é agnóstico de provedor — qual backend (ICS local, Evolution Data Server, API de nuvem) fica como decisão aberta **D2**, decidida quando a família entrar em F4.
4. **Cliente MCP é adaptador do executor, não processo novo nem atalho.** Um filho isolado por servidor, sem rede a menos que o servidor declare e o dono conceda.
5. **Tool de MCP não é capacidade até ser promovida.** Cada tool remota gera um **rascunho** de manifesto (§4) que o dono aprova na UI ou o arquiteto comita no repositório. Antes disso é invisível ao planejador. `risk_class`, `confirmation`, `data_egress` e `access_level_min` são **nossos**; a anotação do servidor entra como comentário.
6. **Identidade do servidor é pinada:** comando/URL + hash do binário ou imagem + hash da lista de tools. Lista de tools mudou (rug-pull), capacidades promovidas daquele servidor ficam **suspensas** até reaprovação.
7. **Saída de MCP é `trust: third_party`, sempre.** Validada por schema, truncada por orçamento, entregue ao S2 em envelope de dado. Não amplia `allowed_tools`, não cria grant, não muda cenário, não vira memória durável sozinha, e conteúdo que imita chamada de ferramenta é neutralizado (P6).
8. **Orchestrator entra por allowlist estreita** (`retrieve_memory`, `get_memory_chunk`, `store_memory`, `log_decision`, `ask_owner`, `cli_ping`, `jev`). `shell_exec`, `ssh_exec`, `cli_send` e afins são **proibidos de promoção** — a proibição de canivete suíço não se contorna chamando por MCP. Chamada carrega contador de salto: Jarvis→Orchestrator→Jarvis é recusado.
9. **Egress por MCP remoto** é tratado como qualquer egress da §5.3: o dono vê destino, resumo e o que sai, no momento de sair.

## Alternativas descartadas

- **Importar o catálogo do servidor MCP direto para `allowed_tools`:** é delegar política a terceiro; contraria P1 e P6.
- **Confiar em `readOnlyHint`/`destructiveHint`:** dica sem garantia (relatório 04); um servidor comprometido mentiria exatamente nesse campo.
- **`apps.run_command` com string:** é o canivete suíço proibido pela §4, por mais conveniente que pareça para "abrir qualquer coisa".
- **Calendário com escrita completa no v1:** convite enviado é irreversível socialmente; rascunho dá o valor sem o risco, e o dono pediu rascunho.
- **Proxy MCP único para todos os servidores:** um comprometimento contamina todos; um filho por servidor isola o estrago.

## Consequências

- Mais fácil: crescer por níveis — família nova é manifesto + testes, sem mexer no núcleo.
- Mais caro: cada tool de MCP útil exige um passo de promoção; isso é atrito proposital.
- Passa a ser obrigatório testar: suíte de injeção vinda de servidor MCP, rug-pull (lista de tools mudada entre sessões), recusa de promoção de tool genérica, e recursão Jarvis→Orchestrator→Jarvis.

## Como invalidar esta decisão

Se a promoção manual travar o uso real a ponto de o dono desligar o porto MCP, revisamos **o fluxo de aprovação** (lote, assinatura de catálogo, confiança por servidor), não a regra de que a política é nossa.
