# ADR-0023 — MCP nos dois sentidos: cliente por servidor isolado, servidor de capacidades atrás do PDP

**Data:** 2026-10-16 · **Estado:** proposta · **Decide:** dono (o que liga, quem conecta, os
tetos), arquiteto (o enforcement)
**Pedido:** ideia do dono de 2026-10-15 (memória `b63298d6`): o Jarvis é **cliente** MCP (usa
outros servidores e sabe quais estão conectados) e **servidor** MCP (o Orchestrator e outros apps
locais conversam com ele); e o produto traz só as ferramentas-base, com PDF, redes sociais,
WhatsApp e Discord como **apps com MCP** que o dono liga se quiser. Mais o requisito
`web.capturar` (memória `6bd041f5`). Emenda a ADR-0010, que já decidiu o lado cliente em linhas
gerais e não tratava o lado servidor.

## Contexto

### O que o MCP é hoje (fontes no fim, acesso em 2026-10-16)

- **Versão da especificação: 2026-07-28**, publicada em 2026-07-28, com mudanças que quebram
  compatibilidade com a 2025-11-25. O protocolo ficou **sem estado**: sai o handshake
  `initialize`/`initialized`, cada pedido leva versão, identidade e capacidades do cliente em
  `_meta`; o servidor **MUST** implementar `server/discover`; sai a sessão (`Mcp-Session-Id`) do
  Streamable HTTP; servidor que precisa de estado entre chamadas devolve um *handle* explícito
  como argumento comum.
- **Pedido do servidor ao cliente mudou de forma:** em vez de o servidor mandar `sampling`,
  `elicitation` ou `roots/list`, ele responde `resultType: "input_required"` com `inputRequests`, e
  o cliente repete o pedido com `inputResponses` (Multi Round-Trip Requests, SEP-2322).
- **Obsoletos com janela mínima de 12 meses:** Roots, Sampling e Logging; o transporte HTTP+SSE;
  o Dynamic Client Registration, em favor de Client ID Metadata Documents.
- **Tasks saiu do núcleo** e virou extensão oficial (`io.modelcontextprotocol/tasks`), tratada na
  ADR-0022.
- **Transportes:** `stdio` (JSON-RPC por linha nos fluxos padrão de um subprocesso que o cliente
  lança) e Streamable HTTP (um endpoint, um POST por mensagem). Transporte próprio é permitido; o
  que rodar sobre fluxo de bytes (socket Unix, TCP) **SHOULD** reusar o enquadramento do `stdio`.
  Streamable HTTP local: o servidor **MUST** validar `Origin` (DNS rebinding), **SHOULD** escutar
  só em 127.0.0.1 e **SHOULD** autenticar toda conexão.
- **Autorização é OPCIONAL.** Com HTTP, **SHOULD** seguir a especificação (OAuth 2.1, PKCE,
  Protected Resource Metadata RFC 9728 **MUST**, Resource Indicators RFC 8707 **MUST**, validação
  de audiência **MUST**, e o servidor **MUST NOT** aceitar ou repassar token que não foi emitido
  para ele). Com `stdio`, **SHOULD NOT** seguir a especificação e **pega a credencial do
  ambiente**. Novidades de 2026-07-28: o cliente **MUST** validar `iss` (RFC 9207) quando presente
  e **MUST** guardar credencial por emissor, sem reusar em outro servidor de autorização.
- **Como o servidor expõe ferramenta:** `tools/list` e `tools/call`; `inputSchema` e
  `outputSchema` em JSON Schema 2020-12; `structuredContent`; `isError` para erro de execução.
  A lista **MUST NOT** variar por conexão e **MAY** variar pela autorização do pedido. As
  anotações **MUST** ser tratadas como não confiáveis "unless they come from trusted servers". O
  cliente **SHOULD** confirmar operação sensível, mostrar os argumentos antes de chamar, validar
  o resultado, ter prazo e registrar o uso. Nome de ferramenta é único só dentro do servidor, e o
  `serverInfo.name` **SHOULD NOT** servir para desambiguar.
- **Como o servidor expõe recurso:** `resources/list`, `resources/read`, `resources/templates/list`;
  recurso é dado identificado por URI, "application-driven" (a aplicação decide quando entra no
  contexto), com anotações `audience` e `priority`.
- **Boas práticas de segurança da própria especificação**, as que valem aqui: servidor local é
  código rodando com o privilégio do cliente — consentimento mostrando o **comando exato** antes
  de executar, caixa de areia com o mínimo de acesso, `stdio` para servidor local; SSRF na
  descoberta de OAuth (bloquear faixas privadas, só HTTPS fora de loopback); URL de autorização só
  `http`/`https` e **nunca aberta por shell**; *handle* de estado não é autenticação.
- **SDK Python oficial:** pacote `mcp`, versão **2.3.0 de 2026-10-02**, licença **MIT**
  ("Copyright (c) 2024 Anthropic, PBC"), Python ≥ 3.10. A linha 2.x saiu com a especificação
  (2.0.0 em 2026-07-28); a 1.x segue com correções (1.30.0 em 2026-09-07). Servidor por
  `MCPServer` com decoradores sobre funções tipadas (o schema sai das anotações de tipo); cliente
  `Client` assíncrono; transportes `stdio`, Streamable HTTP e SSE.

### O que o projeto já tem

ADR-0010 (aceita): cliente é **adaptador do executor**, um filho isolado por servidor; tool remota
só existe **depois de promovida** a manifesto nosso; identidade pinada por hash e **suspensão** se
a lista mudar; saída sempre `third_party`; Orchestrator por allowlist estreita; contador de saltos
recusa Jarvis→Orchestrator→Jarvis. ADR-0009: quatro níveis, lista de negação, elevação separada,
P12 (nível só muda pela UI). O projeto já guarda chave no chaveiro do SO via `keyring`
(`pyproject.toml`, `src/jarvis/gui/chaveiro.py`) e já tem gerador de código a partir do manifesto
(`src/jarvis/manifesto/codegen.py`).

**Um fato que a ADR-0010 não tratou:** servidor MCP local é um processo do usuário. Ele lê
`~/.ssh` se quiser — os níveis da ADR-0009 prendem o **nosso** executor, não o processo de outro.
Sem caixa de areia, promover um servidor local é conceder `total` sem lista de negação.

## Lado cliente: dois desenhos

**C-A — um adaptador por servidor (ADR-0010).** Cada servidor tem um filho nosso com o `Client`
do SDK. Servidor `stdio` é neto, lançado pelo adaptador dentro da caixa de areia; servidor HTTP é
alcançado pelo adaptador, com egress só para o host declarado.

**C-B — um gateway único** que agrega todos os servidores num processo e expõe uma lista só.

| Critério | C-A | C-B |
|---|---|---|
| Um servidor travado | derruba o próprio adaptador | derruba todos |
| Credenciais | cada adaptador vê só a do seu servidor | o gateway vê todas: um ponto de vazamento |
| Caixa de areia | por servidor, com as raízes daquele manifesto | uma só para todos, a mais larga |
| Colisão de nomes | prefixo pelo id do registro, nunca pelo `serverInfo.name` | precisa da mesma regra, num lugar só |
| Código | supervisão de N filhos | um processo |

**Decisão do lado cliente: C-A.** O ganho do C-B é operacional; o custo é de segurança, e é
exatamente o custo que a §5.5 não aceita.

## Lado servidor: dois desenhos

**S-A — servidor de capacidades.** `jarvis mcp --cliente <id>` é um processo fino, lançado pelo
app que conecta (transporte `stdio`), que se autentica no `agentd` pelo IPC local já autenticado
da ADR-0014 e expõe como tools MCP **as capacidades que o dono marcou para fora**, geradas do
manifesto. Cada chamada vira `ToolCallRequested` com `source: mcp-in:<id>` e `trust: third_party`
— quem chama não é o dono — e passa pelo PDP com o **teto daquele cliente**.

**S-B — servidor de conversa.** Expõe `jarvis.perguntar(texto)` e `jarvis.delegar(objetivo)`:
o outro app escreve, o planejador do Jarvis decide o que fazer.

| Critério | S-A | S-B |
|---|---|---|
| Quem escolhe a ação | o app que chama, entre capacidades tipadas | o planejador do Jarvis, a partir de texto de terceiro |
| *Confused deputy* (o app ganha o alcance do Jarvis) | limitado pelo teto do cliente, por chamada | o texto do app dirige um planejador que tem o alcance do dono |
| Prompt injection | o argumento é validado por schema | o canal **é** texto livre para o LLM |
| O que o Orchestrator ganha | ler status, buscar e ler arquivo dentro do teto | "conversar" com o Jarvis |
| Depende de | ADR-0010 + codegen | S-A + ADR-0022 (a delegação é uma tarefa) |

**Decisão do lado servidor: S-A agora; S-B depois da ADR-0022, como tarefa delegada** com
allowlist = teto do cliente ∩ modelo de tarefa, todo efeito confirmado pelo dono na UI do Jarvis,
e o resultado devolvido pela extensão Tasks. O servidor **nunca** expõe: escrita de memória,
mudança de nível, elevação, confirmação, `tarefas.delegar` (até o S-B), e nenhuma capacidade com
`requires_elevation: true`.

## Decisão

**Cliente MCP por adaptador isolado por servidor (C-A) e servidor MCP de capacidades por `stdio`
(S-A), os dois atrás do mesmo PDP, com o SDK oficial `mcp` 2.x.** As regras abaixo valem para
os dois sentidos.

### Política de acesso nos quatro níveis

| Modo do dono | Servidor local de fora (cliente) | App que chama o Jarvis (servidor) |
|---|---|---|
| `jarvis` | caixa de areia sem disco do usuário; só a pasta do servidor | teto `jarvis` |
| `padrao` | pastas padrão montadas, cada uma só se o manifesto promovido a declarar, com a permissão declarada | teto ≤ `padrao` |
| `concedido` | + raízes concedidas, uma a uma, pelo manifesto | teto ≤ `concedido` |
| `total` | + o resto da árvore, **menos a lista de negação**, que nunca é montada | teto ≤ `concedido`; `total` por MCP só se o dono decidir (**DECISÃO DO DONO**) |

- O teto efetivo de um cliente de entrada é **mín(teto do registro, modo atual do dono)**;
  reduzir o modo reduz o teto na hora (§5.5).
- O mesmo `access_level_min` e as mesmas `roots` do manifesto valem nos dois sentidos: o que é
  invisível ao planejador num modo é invisível ao cliente de entrada no mesmo modo.
- Elevação e mudança de nível **não existem** por MCP (P12, ADR-0009 item 7).
- **Servidor local sem caixa de areia** só é promovível se o manifesto declarar `roots: []` e
  `data_egress: none` **e** o dono aceitar aquele servidor pelo nome, sabendo que nada o prende
  (**DECISÃO DO DONO**, por servidor). A ferramenta de caixa de areia por sistema (bubblewrap no
  Linux; AppContainer ou Job Object no Windows) **[SUPOSIÇÃO: confirma ou derruba a fatia mínima,
  que mede se o servidor de teste roda dentro dela no Wayland, no X11 e no Windows]**.

### Confirmação

- A matriz da §5.3 vale igual para tool remota e para chamada de entrada; `risk_class` e
  `confirmation` são **nossos** (ADR-0010 item 5).
- **Confirma só o dono, só na UI do Jarvis.** O app de entrada nunca confirma por ele. Chamada de
  entrada que exige confirmação com o dono ausente volta `isError` com "precisa da confirmação do
  dono na janela do Jarvis" — sem fila, na fatia mínima.
- **`input_required` de servidor remoto** (o antigo *elicitation*): o formulário é mostrado na UI
  como pedido de terceiro, e nada é preenchido sozinho. Modo URL: só `http`/`https`, aberto por
  API do sistema e nunca por shell, com o host em destaque (boa prática da especificação).
- O Jarvis cliente **não declara** Sampling (obsoleto, e é o caminho para um servidor usar o
  nosso LLM) nem Roots (obsoleto; raiz é argumento de tool, como a especificação sugere).

### Isolamento de segredos

1. Credencial de servidor fica no **chaveiro do SO** (o `keyring` que o projeto já usa), uma
   entrada por servidor; credencial OAuth é guardada **por emissor** e não é reusada com outro
   (SEP-2352).
2. **`stdio`:** o filho nasce com **ambiente vazio** mais as variáveis que o manifesto do servidor
   declara — nada do ambiente do Jarvis vaza (nem chave de provedor, nem `HOME` real se a caixa
   de areia o substituir). **HTTP:** o adaptador põe `Authorization: Bearer` com `resource` =
   URI canônica do servidor (RFC 8707).
3. Segredo **nunca** em `argv` (legível em `/proc/<pid>/cmdline`, a mesma regra da ADR-0018), nunca
   no log de eventos, nunca no contexto do LLM, nunca em argumento que o modelo preenche.
4. **Lado servidor:** cada app de entrada recebe um token gerado pelo dono na UI, guardado na
   configuração **do app**, apresentado pelo `jarvis mcp` ao `agentd` e revogável. Sem token
   válido, nada é listado. O Jarvis **não repassa** token de entrada a servidor nenhum (proibição
   de *token passthrough* da especificação).
5. Saltos: o contador da ADR-0010 item 8 viaja numa chave própria em `_meta` de cada pedido, já
   que o protocolo deixou de ter sessão para carregá-lo.

### Licença

- `mcp` é **MIT** — permissiva e compatível com o Apache-2.0 do produto. Ao entrar na trava, o
  pacote vai para `docs/licencas.md` e o portão de licença confere a árvore de dependências que
  ele puxa **[SUPOSIÇÃO: nenhuma dependência transitiva copyleft; confirma o portão
  (`tools/license_gate.py`, ADR-0011 e ADR-0012) no commit que adicionar o pacote]**. Faixa proposta: `mcp>=2.3,<3`.
- Servidor de terceiro que o dono instala roda como processo separado e **não é distribuído por
  nós**; servidor que **nós** distribuirmos (ex.: o de PDF) passa pelo portão como qualquer
  dependência.

### Apps como MCP

- **Regra de produto:** o Jarvis traz as famílias-base da §5.6; app de fora é servidor MCP que o
  dono configura, e cada tool dele passa pela promoção. Ler mensagem de terceiro é `third_party`
  e marca a sessão como contaminada; enviar, postar ou responder é `egress_representacao` e
  confirma no envio.
- **PDF** é o primeiro: leitura local, sem egress, sem conta.
- **Discord:** a via oficial é conta de bot pelo portal de desenvolvedor; automatizar conta de
  usuário é contra os termos **[SUPOSIÇÃO: vem de fonte secundária; confirma ou derruba a leitura
  do artigo de suporte do Discord antes da fatia que liga o app]**.
- **WhatsApp:** a via oficial é a WhatsApp Business Platform (Cloud API), com opt-in e janela de
  24 h; clientes não oficiais (whatsapp-web.js, Baileys) automatizam o app de consumidor e arriscam
  banimento **[SUPOSIÇÃO: vem de fonte secundária; confirma ou derruba a leitura dos termos da Meta
  antes da fatia]**. Proposta: o Jarvis não promove servidor baseado em cliente não oficial;
  que conta usar é **DECISÃO DO DONO**.
- **Redes sociais:** a API oficial de cada rede, com o termo de cada uma conferido na hora de
  ligar.
- **`web.capturar`** (memória `6bd041f5`): navegador pelo SDK/CLI, nunca embutido. Só `http`/
  `https`, perfil novo e efêmero (sem cookie, sem login, sem formulário, sem clique em entrar);
  bloqueio de IP privado e loopback, como a especificação manda para a descoberta de OAuth; o PNG
  sai com um arquivo ao lado contendo `fonte` (URL final depois dos redirecionamentos, título),
  `capturado_em` (UTC e fuso do dono) e o `sha256` do PNG. `data_egress: network` (o GET da
  página), sessão marcada como contaminada. Qual navegador/servidor faz isso é **DECISÃO DO DONO**
  depois de medir duas opções; a licença da escolhida entra no portão.

## Alternativas descartadas

- **Gateway único (C-B)** — ver tabela. Volta se o número de servidores passar do que a supervisão
  aguenta, medido.
- **Servidor de conversa primeiro (S-B)** — ver tabela; depende da ADR-0022 e herda as regras dela.
- **Streamable HTTP local primeiro** — abre DNS rebinding e qualquer processo da máquina como
  cliente em potencial; `stdio` limita o acesso a quem lançou, e é o que a especificação recomenda
  para servidor local. HTTP local entra depois, com `Origin`, 127.0.0.1 e token, se o dono quiser
  (**DECISÃO DO DONO**).
- **Confiar nas anotações do servidor** — a especificação diz que são não confiáveis; a ADR-0010
  já tinha decidido o mesmo.
- **SDK 1.x** — mantido, mas fala o protocolo de antes da 2026-07-28; começar nele é migrar logo.

## Consequências

- Fica mais fácil: app novo entra sem código nosso, só com promoção de manifesto.
- Fica mais caro: caixa de areia por sistema, tela de registro de servidores e de apps de
  entrada, promoção de cada tool.
- Passa a ser obrigatório testar: ambiente do filho, segredo fora de `argv`/log/contexto,
  rug-pull, teto do cliente de entrada, contador de saltos, e a suíte de prompt injection da F2
  com saída de MCP.

## Riscos

| Risco | Controle |
|---|---|
| Rug-pull (lista de tools muda depois da promoção) | identidade pinada e suspensão (ADR-0010 item 6) |
| Descrição de tool envenenada | o planejador vê a **nossa** descrição do manifesto promovido; a do servidor é comentário |
| Servidor local lê o que quiser | caixa de areia; sem ela, só servidor sem disco e com aceite nominal do dono |
| App de entrada usa o alcance do Jarvis | teto por cliente, por chamada; efeito confirmado pelo dono |
| SSRF na descoberta de OAuth | bloquear faixas privadas, HTTPS fora de loopback |
| Mudança de protocolo | SDK e versão de protocolo fixados; servidor 2025-11-25 testado na fatia **[SUPOSIÇÃO: o SDK 2.x conversa com servidor da 2025-11-25 pela regra de compatibilidade da especificação; confirma ou derruba o teste (i)]** |
| Termos de app (WhatsApp, Discord) | só via oficial; conta é decisão do dono |

## Fatia mínima (implementar primeiro)

**Cliente:** um servidor `stdio` de teste nosso (em `tests/`), sem rede e sem disco, mais um
servidor real de leitura escolhido pelo dono. Caminho inteiro: registro com consentimento que
mostra o comando exato → adaptador → `server/discover` e `tools/list` → rascunho de manifesto →
promoção por commit → PDP → chamada → saída `third_party` truncada → troca da lista → suspensão.

**Servidor:** `jarvis mcp --cliente orchestrator` por `stdio`, expondo `system.read.status` e
`files.search_in_roots`, com teto `jarvis` e token do dono.

## Teste de aceite

- **(a)** Tool remota sem promoção não aparece na allowlist do turno em nenhum turno do corpus.
- **(b)** Lista de tools alterada: suspensão em 100% dos casos e pedido de reaprovação na UI.
- **(c)** Saída de MCP com texto que imita chamada de ferramenta ou instrução: 0 casos em que
  amplia `allowed_tools`, cria grant, muda cenário, vira memória ou muda nível (aceite (d) da F2).
- **(d)** O ambiente do filho (lido de `/proc/<pid>/environ`) contém só as variáveis declaradas;
  varredura de `argv`, log de eventos e contexto do LLM não acha o segredo de teste.
- **(e)** Entrada sem token: recusada. Com token e teto `jarvis`, buscar em Documentos: negado e
  auditado com `source: mcp-in:orchestrator`.
- **(f)** Jarvis→Orchestrator→Jarvis: recusado pelo contador de saltos.
- **(g)** Varredura do que o servidor lista: 0 capacidades com `requires_elevation`, de mudança de
  nível, de confirmação ou de escrita de memória.
- **(h)** Portão de licença verde com `mcp` na trava.
- **(i)** O cliente conversa com um servidor da revisão 2025-11-25 ou falha dizendo por quê.

## Como invalidar esta decisão

- A caixa de areia não roda em algum dos sistemas da P11: o lado cliente fica restrito a
  servidores sem disco naquele sistema até haver alternativa, e esta ADR é emendada.
- A extensão Tasks fica estável e o dono quer o Orchestrator conversando com o Jarvis antes da
  ADR-0022: o S-B é reavaliado, com as mesmas regras de teto e confirmação.
- O SDK 2.x deixa de ser mantido ou muda de licença: a decisão de usar o SDK oficial reabre.

## Fontes (acesso em 2026-10-16)

- Changelog da revisão 2026-07-28: <https://modelcontextprotocol.io/specification/2026-07-28/changelog>
- Anúncio da revisão 2026-07-28 (SDKs Tier 1 atualizados no dia):
  <https://blog.modelcontextprotocol.io/posts/2026-07-28/>
- Autorização: <https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization>
- Transportes: <https://modelcontextprotocol.io/specification/2026-07-28/basic/transports> e
  <https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http>
- Tools: <https://modelcontextprotocol.io/specification/2026-07-28/server/tools>
- Resources: <https://modelcontextprotocol.io/specification/2026-07-28/server/resources>
- Boas práticas de segurança:
  <https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices>
- SDK Python `mcp` no PyPI (2.3.0, 2026-10-02): <https://pypi.org/project/mcp/>; licença:
  <https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE>
- WhatsApp, via oficial e risco de cliente não oficial (fonte secundária):
  <https://www.dragapp.com/blog/whatsapp-mcp-server/>
- Discord, automação de conta de usuário (fonte secundária, cita o artigo de suporte):
  <https://github.com/rigwild/discord-self-bot-console>
