# ADR-0047 — A persona em seções, as regras do dono num arquivo dele, e o catálogo do turno gerado do registro

**Data:** 2026-10-25 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o tom e as regras), arquiteto (onde as regras moram, o formato do catálogo, o teto do prompt)
**Pedido:** dono, 2026-10-25 — um system prompt e regras estruturadas para o Jarvis agir como o Jarvis agiria (conciso, direto, proativo, que faz em vez de pedir, que resolve a dúvida pelo contexto) e o catálogo de ferramentas sempre no contexto, com quando usar e exemplos de pedidos naturais — gerado do registro real e enxuto, para não pesar a latência (ADR-0045). Commit `f103936`. Emenda a ADR-0028 (o que vai ao motor em todo turno).

## Contexto

O prompt de sistema de um turno tinha 30 550 caracteres (~10,1 mil tokens pelo tokenizador do e5; `docs/medicoes/prompt-do-turno.md`): a persona v14 (7 915) com o procedimento de cada ferramenta escrito nela, e o catálogo com o esquema JSON de 61 ferramentas (22 635). O primeiro token do `claude -p` é a etapa cara do pedido (ADR-0045), e cada caractere do prompt é pago em todo turno. Regras de comportamento do dono não tinham lugar: ou iam na persona (do repositório), ou não iam.

## Decisão

1. **Persona v15 em seções** (`src/jarvis/s2/persona.md`): identidade e tom, princípios de ação, o que fazer sem perguntar, quando perguntar, voz e tela, memória e nomes, segurança. O procedimento de cada ferramenta saiu dela para o manifesto da ferramenta. 7 915 → 4 580 caracteres.
2. **As regras do dono** (`jarvis.s2.regras`): `~/.config/jarvis/regras.toml` (a pasta do `jarvis-voz.toml`); sem ele, o padrão `src/jarvis/s2/regras.toml`; exemplo em `docs/exemplos/regras.toml`. Até 12 regras de até 220 caracteres; `ligada = false` desliga sem apagar; arquivo torto vale o padrão, com aviso. Vão ao motor em todo turno, **depois** da persona, sob o cabeçalho «REGRAS DO DONO (valem em todo pedido; na dúvida, vencem o resto)». O `--diagnostico` diz de onde vieram, quantas e o tamanho — nunca o texto. A suíte nunca lê a pasta do dono.
3. **O catálogo é gerado do registro** (`jarvis.s2.motor_claude_cli`): os manifestos ganham `quando` e `exemplos` (esquema v1); cada ferramenta vira **uma linha** — o nome com os argumentos (`url*, segundo_plano:bool, acao*=tocar|pausar`), quando usar, o que só esta sessão sabe (`agora`) e até três pedidos naturais («fecha o Discord todo») — no lugar do esquema JSON. A ordem é a do registro (estável: o começo do prompt se repete entre turnos). 22 635 → 9 234 caracteres.
4. **O teto**: o prompt de sistema de um turno caiu para 14 530 caracteres (~4,3 mil tokens e5); `tools/medir_prompt.py` mede e um teste segura o teto de 16 mil.

## Alternativas descartadas

- **Regras dentro da persona**: a persona é do repositório e muda por versão; a regra do dono é dele e tem de sobreviver à atualização.
- **Esquema JSON completo no prompt** (o de antes): o `claude -p` recebe as ferramentas pelo nosso protocolo de proposta, não por tool use nativo; o esquema só pesava. O código valida os argumentos depois, contra o esquema do manifesto.
- **Catálogo filtrado pelo método do pedido** (só as ferramentas do roteador): a ADR-0035 já tira as proibidas no turno; um catálogo variável quebraria o começo estável do prompt e confundiria o modelo entre turnos.

## Consequências

- Mudar o tom ou uma regra não pede release: o dono edita `regras.toml` e abre a sessão de novo.
- Ferramenta nova precisa de `quando` e `exemplos` no manifesto para aparecer bem no catálogo; o teste do teto pega o catálogo que cresceu demais.

## O que não foi provado

O efeito no comportamento do modelo com o dono (conciso, faz em vez de pedir) — só a forma do prompt foi medida; os tokens são do e5, uma aproximação do tokenizador do Claude, que não é público.

## Como invalidar esta decisão

Se o motor passar a chamar a ferramenta errada ou com argumento torto com frequência maior que antes (a trilha conta `argumento_recusado`), o catálogo de uma linha perdeu informação: volte o campo que faltou ao formato da linha, não o esquema inteiro.

## Emenda de 2026-10-30 — ensinar as ferramentas: receitas por família, só no turno do assunto

**Pedido:** dono, 2026-10-30 — o Jarvis «não sabe mais usar a extensão» (na trilha de 30/10, um
pedido de navegador começou por `memoria.buscar_historico` e levou 12 s até a 1ª ferramenta). O
catálogo diz **o que** cada ferramenta faz; faltava **quando** usar cada família, em que ordem e
como encadear.

**Decisão** (`jarvis.s2.receitas`): uma receita curta por família — navegador (abrir, achar e
clicar, buscar no site, estudar com console/rede/avaliar, um exemplo do YouTube), web, apps e
janelas, mouse e teclado, memória, sistema, script, delegar, presets, vocabulário, MCP — e a linha
de recuperar de falha (ADR-0038, emenda desta data). Vai ao prompt **só no turno daquele assunto**:
o roteador de método (ADR-0035, as regras locais de sempre) e palavras do pedido escolhem até duas
famílias; linha que cita ferramenta desligada sai. O turno de conversa custa o mesmo de antes, e o
prompt-base (persona + regras + catálogo, 15 971 caracteres em 30/10) não muda — o teto da emenda
anterior continua valendo para ele. `Cerebro.classificador_de_receitas` aceita um classificador de
decisão (ADR-0024/0029) para o pedido com verbo de ação que as regras não reconhecem; o app **não**
o liga por padrão (uma pergunta ao Jev de nuvem custa ~0,5 s no turno — ligar depois de medir).

**Medido** (`tools/medir_receitas.py` → `docs/medicoes/receitas-sob-demanda.md`): +74 a +269 tokens
(e5) nos turnos com receita, média 161; 0 na conversa; escolher e montar ≤ 0,2 ms. A persona não
foi mexida (outra CLI trabalhava nela).

**Testes:** `tests/unit/s2/test_selecao_de_ferramentas.py` (16 pedidos-tipo → família, receita e
ferramentas que existem no catálogo; conversa sem receita; linha desligada sai; classificador falso
escolhe, inseguro e quebrado não; a receita chega ao prompt do turno certo). O Jev de verdade é
remoto e sem cache local: o teste dele é pulado com o motivo.

**Não provado:** que o `claude -p` de verdade escolhe melhor com as receitas (o efeito no modelo só
a trilha do dono vai mostrar: `ms_primeira_ferramenta` e a 1ª ferramenta dos pedidos de navegador).
