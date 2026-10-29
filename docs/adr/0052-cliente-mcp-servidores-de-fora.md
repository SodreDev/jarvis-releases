# ADR-0052 — Cliente MCP: o Jarvis consome servidores MCP que o dono listar, cada tool atrás do mesmo PDP e do mesmo guarda

**Data:** 2026-10-29 · **Estado:** aceita (implementada; pendente da decisão do dono de usar no app) · **Decide:** dono (quais servidores, padrão desligado, tier de cada tool), arquiteto (o transporte, a promoção a manifesto, o isolamento, o guarda)
**Pedido:** dono, 2026-10-29 — "integrar TAMBÉM servidores MCP (consumir MCPs de fora, como Chrome DevTools MCP e Playwright MCP). […] CLIENTE MCP: o Jarvis consome servidores MCP configurados pelo dono (lista em ~/.config/jarvis/, padrão vazio/desligado), cada tool MCP entra no catálogo com tier no PDP e passa pelo MESMO guarda; conteúdo vindo do MCP é dado, nunca ordem." Camada C da ADR-0049; realiza o lado cliente da ADR-0023 (MCP nos dois sentidos) e segue a ADR-0010 (promoção com política nossa).

## Contexto

A ADR-0023 decidiu o cliente MCP como **adaptador do executor**, um filho isolado por servidor, com a tool remota só existindo **depois de promovida** a um manifesto nosso, identidade pinada por hash, saída sempre `third_party`, e os quatro níveis de acesso da ADR-0009. Nada disso foi implementado ainda. O dono agora pede o caso concreto: consumir servidores como o **Chrome DevTools MCP** e o **Playwright MCP** (ambos rodam por stdio, `npx`, e expõem tools como `evaluate_script`, `list_console_messages`, `take_snapshot`, `click`, `fill`, `navigate` — fontes no fim).

## Decisão

### 1. A configuração do dono (`~/.config/jarvis/mcp.toml`)

Padrão **vazio/desligado**: sem o arquivo, nenhum servidor, nenhuma tool MCP. Cada servidor é uma entrada:

```toml
[servidor.devtools]
transporte = "stdio"
comando = ["npx", "chrome-devtools-mcp@latest"]
ligado = false            # o dono liga explicitamente, como a nuvem (ADR-0029)
tier_padrao = "moderado"  # o tier das tools deste servidor, se a tool não disser
[servidor.devtools.tools]       # o tier POR tool, decidido pelo DONO (nunca pelo servidor)
list_console_messages = "leitura"
evaluate_script = "moderado"
```

Nunca se lê chave nem segredo do arquivo (a regra das chaves vale aqui também); um arquivo com cara de segredo é recusado inteiro, como no portão (ADR-0029).

### 2. A promoção a manifesto nosso (ADR-0010)

O cliente abre o servidor, pede `tools/list`, e **promove** cada tool a um manifesto `mcp.<servidor>.<tool>` no catálogo em memória: `risk_class`, `confirmation`, `data_egress`, `access_level_min` e o **tier** são **nossos** (vêm da configuração do dono e dos padrões, nunca da anotação do servidor, que entra só como comentário — o lint já recusa `campo de política` vindo do servidor). `trust_input` é sempre `untrusted`. A identidade do servidor é pinada por hash (comando + versão); mudou, suspende até o dono reconfirmar. As tools proibidas de promover (`shell_exec`, `ssh_exec`, `run`, `bash`… — ADR-0010 item 8) continuam proibidas, inclusive por nome parecido.

### 3. O isolamento

Cada servidor roda como processo filho isolado. Em stdio local, o servidor é um processo do usuário e pode ler o disco — então, como a ADR-0023 decidiu, um servidor local sem caixa de areia só é promovível se declarar que não sai da pasta dele e não egressa, **ou** o dono aceitar aquele servidor pelo nome sabendo que nada o prende. Quando der, o servidor roda na **mesma caixa** do executor de scripts (ADR-0050, bubblewrap): sem rede por padrão (o servidor que precisa de rede — um que chama uma API — é um `data_egress: network:<host>` declarado e o dono decide), sem a casa do dono.

### 4. O mesmo PDP e o mesmo guarda

Cada `mcp.<servidor>.<tool>` passa pelo **PDP** (o tier que o dono deu decide allow/confirm/deny) e, por ser guardada (ADR-0049, toda `mcp.*` é guardada), pelo **guarda de contexto**: `leitura` passa; `perigoso` pede o sim; o resto vai pelas regras e pelo Jev, que compara o destino/efeito da chamada com o objetivo. Uma tool MCP que navega para fora do objetivo, ou que roda script numa página sensível, é barrada ou pede o sim como qualquer ação nossa — o guarda já trata `Tipo.MCP` e tem teste (`tests/unit/politica/test_guarda.py`). O resultado do servidor é **dado** (`untrusted`): nunca vira instrução nem autoriza nada.

### 5. Saltos e limites

O contador de saltos recusa Jarvis→Orchestrator→Jarvis (ADR-0010). O resultado do servidor passa pelo `redigir` antes de qualquer registro; o D20 vale (o que vai a um motor de nuvem é filtrado). Os tetos de catálogo (§4) contam as `mcp.*` promovidas: um servidor com dezenas de tools não estoura o catálogo do turno porque o roteador de método (ADR-0035) só mostra as relevantes ao pedido.

## Estado da implementação (2026-10-29)

**Feito e provado com um servidor MCP falso por stdio.** `jarvis.mcp` (fora de `executor`/`policy`, porque abre processo filho): `config.py` lê `~/.config/jarvis/mcp.toml` (padrão vazio/desligado; recusa arquivo com cara de segredo); `cliente.py` é o adaptador stdio JSON-RPC (`initialize` → `notifications/initialized` → `tools/list` → `tools/call`, com prazo e identidade pinada por hash do comando); `promocao.py` promove cada tool a `mcp.<servidor>.<tool>` com a política **nossa** (tier do dono; `risk_class`/`data_egress`/`confirmation` derivados; `trust_input: untrusted`; `input_schema` fechado), recusando as proibidas (ADR-0010); `gestor.py` descobre, promove e roteia. O executor liga em `preparar()`: as tools entram no catálogo e no PDP, `_ligada`/`_corpo` roteiam, e passam pelo guarda (`Tipo.MCP`: leitura passa, perigoso e destino fora do objetivo pedem o sim). **Provas:** `tests/unit/mcp/` com o servidor falso `servidor_falso.py` ponta a ponta pelo executor/PDP/guarda (padrão desligado, promoção com o tier do dono, `shell_exec` recusada, resultado como dado, destino fora do objetivo pedindo o sim).

**Falta (pendente do dono).** Ligar no app real: `voz/app.py._montar_ferramentas` passa a montar o `GestorMcp(carregar_mcp())` e dá ao executor — a coordenação com a CLI que edita `voz/app.py` (ver o handoff). **Não provado em máquina real:** um servidor MCP de verdade (Chrome DevTools MCP, Playwright MCP) com o `npx` do dono — o teste usa um servidor falso em processo, sem rede.

## Alternativas descartadas

- **Tool remota direto no catálogo, sem promoção**: a ADR-0010 já recusou — política é nossa, não do servidor.
- **Servidor MCP com acesso total sem caixa**: só com o dono aceitando pelo nome; o padrão é a caixa.
- **Confiar no conteúdo do MCP como instrução**: é injeção; conteúdo é dado.

## Como invalidar esta decisão

- Um servidor MCP consegue pôr um campo de política (tier, egress) que o Jarvis respeite — a promoção estaria furada.
- O teste com o servidor falso mostra uma tool MCP rodando fora do PDP ou do guarda.

## Fontes (acesso em 2026-10-29)

- Model Context Protocol — transporte stdio e `tools/list` (especificação do MCP).
- Chrome DevTools MCP — github.com/ChromeDevTools/chrome-devtools-mcp (stdio via `npx`; tools `evaluate_script`, `list_console_messages`, `take_snapshot`, `take_screenshot`, e as de interação).
- Playwright MCP (Microsoft) — servidor MCP oficial por stdio, capacidades opcionais por flag (`vision`, `pdf`, `devtools`); Chromium, Firefox e WebKit.
- ADR-0010 e ADR-0023 (as decisões de MCP que esta realiza).
