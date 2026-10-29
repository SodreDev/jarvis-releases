# ADR-0053 — Interagir com o Claude in Chrome e outras extensões: viabilidade, o que é permitido e o que depende do dono

**Data:** 2026-10-29 · **Estado:** aceita pelo dono — caminho A (emenda de 2026-10-29 abaixo; implementado na ADR-0054) · **Decide:** dono (se quer seguir e por qual caminho), arquiteto (a leitura técnica e dos termos)
**Pedido:** dono, 2026-10-29 — "o dono quer que o Jarvis possa interagir com o Claude in Chrome quando ele mesmo não conseguir algo. PESQUISE com cuidado (docs oficiais, cite fontes) se e como isso é viável e permitido: extensões do Chrome não controlam outras extensões diretamente; avalie caminhos (usar o MCP/native messaging que o Claude in Chrome expõe ao Claude Code, side panel, acionar via UI com mouse virtual, ou delegar tarefa ao Claude Code com a integração Chrome) e os termos de uso. NÃO implemente nada que viole termos ou contorne proteções; entregue só viabilidade + recomendação + o que depende do dono. Mesmo princípio para outras extensões."

## Emenda — decisão do dono (2026-10-29)

O dono decidiu **seguir a recomendação**: caminho A, delegar ao Claude Code. Palavras dele: "DECISÃO DO DONO: seguir a recomendação (e manter a licença Apache-2.0 do repo, não mexa em LICENSE)." A implementação está na **ADR-0054** (`delegar.claude_code`), com estas diferenças em relação ao que esta ADR esboçou:

- **tier:** `moderado` (o mínimo que o dono pediu), com o sim pedido pelo código em toda delegação (uma por pedido) — não `perigoso`; o efeito para o dono é o mesmo, e a ADR-0054 diz a troca no manifesto se ele preferir `perigoso`;
- **sem caminho configurado à mão:** o padrão é o `claude` do PATH; a chave é `~/.config/jarvis/delegar.toml` (`ligado = true`), desligada por padrão;
- **só o caminho documentado:** `claude -p --chrome --output-format json --permission-mode dontAsk --tools "" --allowedTools "mcp__claude-in-chrome__*"` e o resto que a ADR-0054 lista, com fontes em code.claude.com/docs — as fontes de comunidade desta ADR não foram usadas na implementação;
- **custo:** cada delegação consome o limite de uso da conta do dono, inclusive o semanal.

A licença do repositório (Apache-2.0, `LICENSE`) não mudou. Os caminhos B, C e D continuam descartados.

## O fato técnico que decide quase tudo

Uma extensão do Chrome **não controla** outra extensão. Cada extensão roda em contexto de execução próprio; os content scripts de duas extensões compartilham o **DOM** da página, mas não as variáveis nem as mensagens uma da outra. Mandar mensagem a outra extensão (`chrome.runtime.sendMessage` com o id dela) só funciona se a **outra** extensão declarar `externally_connectable` e tratar a mensagem — é um opt-in dela, não um direito de quem chama. A permissão `management` só deixa **listar/ativar/desativar/desinstalar** extensões, não dirigi-las. O `chrome.debugger` anexa a **páginas**, não a outras extensões (anexar a páginas internas de extensão é barrado). **Conclusão:** o Jarvis não tem como, pela extensão dele, "pilotar" o Claude in Chrome. Qualquer caminho que seja é por fora da fronteira entre extensões.

## O que o Claude in Chrome realmente é (fontes no fim)

O Claude in Chrome é uma extensão que fala com o **Claude Code** (ou o app de desktop) por **native messaging**: o Claude Code registra um host nativo (`com.anthropic.claude_code_browser_extension`) na pasta de `NativeMessagingHosts`, e a extensão chama `connectNative`; as ferramentas de navegador aparecem no Claude Code como `mcp__claude-in-chrome__*`. Só há **um** host nativo por id de extensão (o último instalado vence) — por isso o erro comum é o app de desktop e o Claude Code disputarem a mesma extensão. Ou seja: a "integração Chrome" é do **Claude Code**, não algo que uma extensão qualquer consome.

## Os caminhos avaliados

| caminho | viável? | permitido? | veredito |
|---|---|---|---|
| **A. Jarvis delega ao Claude Code**, que tem a integração Chrome (`mcp__claude-in-chrome__*`) | Sim. O Jarvis já abre subagentes de shell (ADR-0038/tarefa.iniciar) e o Claude Code é uma CLI. O Jarvis pede ao Claude Code "faça X no navegador"; o Claude Code usa a extensão dele. | Sim — é o uso pretendido do Claude Code. Não toca a extensão de ninguém. | **Recomendado.** É o único caminho que não cruza a fronteira entre extensões nem contorna nada. |
| **B. Jarvis consome o MCP que o Claude in Chrome expõe** | Parcial. O `mcp__claude-in-chrome__*` é exposto **ao cliente MCP do Claude Code**, pelo host nativo da Anthropic, não como um servidor MCP genérico na rede. O cliente MCP do Jarvis (ADR-0052) consumiria um servidor MCP de terceiros (Chrome DevTools MCP, Playwright MCP), **não** o canal privado da Anthropic. | Depende dos termos da Anthropic; o canal não é documentado como aberto a outros clientes. | **Não.** Reusar o host nativo da Anthropic para outro cliente é contornar o desenho; se a Anthropic publicar um servidor MCP aberto, reavaliar. |
| **C. Jarvis aciona o Claude in Chrome pela UI (mouse/teclado virtual, side panel)** | Tecnicamente possível (clicar no ícone, digitar no side panel com a entrada virtual da ADR-0027). | É dirigir a extensão de outro por automação de UI — frágil, e o oposto do "não controlar outra extensão". Pode esbarrar nos termos e quebra a cada atualização da UI. | **Não.** Contorna a fronteira por fora; frágil e de intenção duvidosa. |
| **D. Jarvis controla a extensão da Anthropic por mensagem/`management`** | Não. `externally_connectable` é opt-in da Anthropic (não há); `management` não dirige. | — | **Impossível.** |

## Recomendação

**Caminho A: delegar ao Claude Code.** Quando o Jarvis não conseguir algo no navegador pela extensão própria (camada A, ADR-0051), ele abre uma **tarefa de subagente** (ADR-0038) que chama o `claude` (Claude Code) com a instrução do que fazer no navegador, e o Claude Code usa a integração Chrome dele. Isso:

- respeita a fronteira entre extensões (o Jarvis não toca a extensão da Anthropic);
- passa pelo mesmo **guarda de contexto** (ADR-0049) e PDP: delegar é uma ação guardada, comparada com o objetivo, e o resultado do Claude Code é **dado**, nunca ordem;
- é opt-in e explícito: o dono configura o caminho do `claude`, e a delegação só acontece quando o método do pedido (ADR-0035) diz que a extensão própria não dá conta.

Para **outras extensões**, o mesmo princípio: o Jarvis não dirige a extensão de ninguém; se há valor, é por um servidor MCP que a ferramenta exponha (ADR-0052) ou por delegação a uma CLI que já a integre. Nunca por automação de UI que simule o dono dirigindo a extensão de outro, nem por reuso de canal privado.

## O que depende do dono

1. **Querer o caminho A.** É uma capacidade nova (`claude_code.delegar` ou similar), tier **perigoso** (roda outra IA com acesso ao navegador): só com o sim e com o `claude` configurado.
2. **Aceitar que a delegação manda contexto ao Claude Code**, que é outro agente — o D20 e o `redigir` valem, mas o dono decide se quer isso.
3. **Os termos.** Confirmar que o uso do Claude Code pelo Jarvis cabe nos termos da conta do dono (uso pessoal, uma pessoa). Nada aqui contorna proteção; se a Anthropic disser que não quer CLIs de terceiros chamando o `claude`, o caminho A cai.

## O que esta ADR **não** faz

Nada de implementação. Não há código que toque a extensão da Anthropic, reuse o host nativo dela, ou automatize a UI dela. A entrega é esta leitura: viabilidade, recomendação (caminho A), e as decisões do dono. A implementação do caminho A, se o dono quiser, é uma ADR própria com a capacidade, o tier e o teste.

## Fontes (acesso em 2026-10-29)

- Chrome Extensions — isolação de contexto e DOM compartilhado (content scripts), mensagens entre extensões por `externally_connectable`, permissão `management` (developer.chrome.com/docs/extensions).
- `chrome.debugger` — anexa a páginas, não a extensões (developer.chrome.com/docs/extensions/reference/api/debugger).
- Claude in Chrome — host nativo `com.anthropic.claude_code_browser_extension`, `connectNative`, tools `mcp__claude-in-chrome__*`, um host por id (relatos e projetos da comunidade: github.com/anthropics/claude-code, github.com/mimimiku778/claude-in-chrome-local-mcp). **Observação:** fontes da comunidade, não documentação oficial da Anthropic; a decisão de seguir o caminho A não depende desses detalhes, só da existência da integração no Claude Code.
