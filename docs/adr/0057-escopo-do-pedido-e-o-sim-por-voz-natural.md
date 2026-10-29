# ADR-0057 — Permissões com menos atrito: o escopo do pedido não pergunta, e o «sim» é dito do jeito natural

**Data:** 2026-10-29 · **Estado:** aceita (implementada e testada sem microfone; o uso real é do dono) · **Decide:** dono (o que é «parte do pedido», o que segue perguntando), arquiteto (onde a regra mora, a leitura da resposta)
**Pedido:** dono, 2026-10-29 — "(a) Aprovação por voz natural: quando precisar do 'sim', o Jarvis pergunta falando e o dono responde 'sim, pode seguir' / 'pode' / 'não'; a resposta passa pelo classificador (Jev) e pelas defesas da ADR-0043 (sinais de fala real) e vale sem clique; sem loop (ADR-0048). (b) AÇÃO CONTIDA NO PEDIDO NÃO PEDE PERMISSÃO: se o dono pediu 'abre a CNN no Brave', abrir a aba nova na CNN, trocar de aba, mantê-la, fechar a que ele mesmo abriu para esse pedido é parte do pedido — 1+1=2, sem pergunta. […] se sair do escopo ou for de risco (apagar dados, enviar mensagem/dinheiro, instalar/rodar código, ler credenciais, sair do domínio pedido), pergunta/barra como hoje. Mantenha todas as travas existentes (conteúdo lido = dado; sem PID 1/compositor/Jarvis; ordem do dono tem de vir do dono)." Emenda a ADR-0046 (a tabela do sim ganha a linha do escopo e a de fechar aba) e a ADR-0048 (a leitura da resposta).

## Contexto

1. **"Sim, pode seguir" cancelava a pergunta.** Sem o Jev (a configuração do dono: `enderecamento = ""`), só o literal curto valia («sim», «pode»…). A resposta natural virava "outro assunto": a pendência caía e o modelo respondia a outra coisa.
2. **A pergunta de uma tarefa por ação** (o que está sob o clique: enviar formulário, banco) **só aceitava o clique** (`Espera(so_clique=True)`); a voz dizia "confirme na tela".
3. **Não havia como fechar uma aba**: a extensão abria, mostrava e navegava abas, mas não fechava; o modelo caía no `window.close` (a janela inteira, que pede o sim por não ter sido citada). O trabalho do pedido já guardava as abas que ele abriu (`Trabalho.abertas`), e o objetivo já sabia o site citado (`Objetivo.citado`) e os alcançados (`Objetivo.dentro`) — faltava a regra explícita.
4. **A trilha do dono** (29/10): `browser.navigate` com `destino_externo` perguntou, e `browser.click` com `envia_formulario` também (24/10). O primeiro é o caso que o escopo resolve quando o site é o do pedido; o segundo continua perguntando (é risco).

## Decisão

1. **A resposta natural, lida sem rede** (`jarvis.s2.portao.resposta_literal`, a mesma no laço de voz e no cérebro): fala curta (até 8 palavras) só de afirmações e recheio é **sim** («sim, pode seguir», «pode sim, por favor», «vai em frente», «manda bala», «tá bom, pode», «prossiga», «autorizo»); fala que começa por negação e não volta atrás é **não** («não, não faz isso», «melhor não», «deixa pra lá», «nem pensar», «espera um pouco»); a misturada («não, pode seguir»), a com condição («pode, mas só amanhã») e a com outro pedido («sim, abre o Spotify») **não são resposta** — nunca viram sim. Com o Jev ligado, ele lê o que o código não leu. No laço de voz, o «sim» natural passa pelos **sinais de fala real** (ADR-0043: o ASR com certeza de ter ouvido) antes de chegar ao cérebro; o eco da própria pergunta não responde (ADR-0048). Sem loop: um «não» acaba a pendência e a tarefa não repropõe (ADR-0046, item 4).
2. **A pergunta por ação de uma tarefa é dita e respondida por voz** (sem `so_clique`): o Jarvis a fala ("Posso clicar em «Enviar»? Envia um formulário."), e o «sim» falado (com os sinais fortes) ou o clique a respondem. A que surge **no meio do primeiro passo do turno** (o risco dinâmico de um clique ou navegação antes de o trabalho ir para a tarefa) segue na faixa da janela — e, com o item 3, só existe para o que está fora do escopo.
3. **O escopo do pedido** (`jarvis.politica.escopo`): a ação de baixo risco e reversível sobre o mesmo alvo do pedido é **contida** e roda sem pergunta; o resto segue a regra de sempre. É do código, sobre o objetivo do turno (que nasce da fala do dono e cresce só com o que as ferramentas do objetivo devolvem — nunca com o que o modelo ou uma página dizem). A tabela atualizada:

   | ação | contida (roda sem pergunta) | fora (pergunta ou barra, como antes) |
   |---|---|---|
   | navegar, abrir site, ler, clicar, digitar, rolar, buscar, ler a web | o endereço é do site **citado** ou **alcançado** pelo caminho do objetivo, sem levar dado do dono | outro domínio depois de ler conteúdo de fora (`destino_externo`); URL com dado do dono para site não citado |
   | **fechar uma aba** (`browser.fechar_aba`, nova) | a aba que **este pedido abriu**, ou a do site que o dono citou («fecha a aba do YouTube») | qualquer outra aba (pode ter coisa não salva) |
   | abrir o navegador, abrir ou pôr em foco um app | o que o pedido pediu (lista de apps liberados e PDP como sempre) | app fora da lista liberada (ADR-0046) |
   | fechar a janela, encerrar o app | o app citado no pedido | alvo não citado; trabalho não salvo detectado; jogo aberto (ADR-0046) |
   | mostrar/fechar conteúdo na tela do Jarvis | sempre (ADR-0055) | — |
   | apagar, sobrescrever, enviar mensagem/e-mail/dinheiro, instalar ou rodar baixado, mudar o sistema, elevação, fora da pasta do dono | **nunca** (`RISCOS_FORA_DO_ESCOPO`: o PDP confirma ou nega) | sempre |
   | o que está sob o clique: formulário, banco, senha, pagamento, palavra de risco, ícone sem nome em mensageiro | **nunca** (risco dinâmico do navegador) | pergunta por ação |
   | ler credencial, PID 1/compositor/o próprio Jarvis, outro usuário | **nunca** (lista de negação, proteções da ADR-0042) | barrado |

   A regra entra por dois lugares: no **portão** (quando o Jev está ligado e pede permissão, o contido vira "fazer" — `cabe_no_objetivo` agora é o `escopo.julgar`, com a classe de risco do manifesto) e no corpo de **`browser.fechar_aba`** (o contido fecha; o resto pede o sim por ação, causa `fora_do_escopo`). O guarda da ADR-0049 continua julgando script, CDP, MCP e delegação contra o objetivo. **Travas mantidas**: conteúdo lido é dado (não amplia o escopo — o alcançado vem só dos endereços que as ferramentas do objetivo devolveram); PID 1, compositor e o próprio Jarvis seguem protegidos; a ordem tem de vir do dono (o objetivo nasce da fala dele).
4. **`browser.fechar_aba`** (moderado, aviso «Fechei a aba {dominio}.»): a extensão ganha `tabs.close` (fecha **uma** aba pelo id; quem decide se pode é o Jarvis) — o dono precisa **recarregar a extensão** (versão 0.1.1). Sem `tab_id`, fecha a aba em que o Jarvis trabalhou neste pedido. O namespace `browser` sobe o teto para 17 (justificado no esquema).

## Alternativas descartadas

- **Perguntar ao Jev se cada ação "cabe no pedido"**: ~0,6 s e rede por ação, e ele não está ligado na configuração do dono; a tabela do código é determinística, auditável e sem custo.
- **Contar o fechar aba pelo `window.close`**: fecha a janela inteira (as abas do dono vão junto).
- **Aceitar qualquer fala com «sim»** como sim: «sim, abre o Spotify» é outro pedido; «não, pode seguir» é ambíguo. Na dúvida, não autoriza.

## Consequências

- Testes: `tests/unit/politica/test_escopo.py` (cada linha da tabela, dos dois lados), `tests/unit/navegador/test_ferramentas_browser.py` (a aba do pedido fecha sem pergunta; a do dono pergunta, e o «não» a deixa; a do site citado fecha), `tests/unit/s2/test_resposta_natural.py` (o sim e o não naturais; o ambíguo nunca vira sim; a mesma leitura na voz) e `tests/unit/voz/test_confirmacao_por_voz.py` (de ponta a ponta com áudio sintético: «Sim, pode seguir.», «Vai em frente.», «Pode sim, por favor.» confirmam uma vez, sem reproposta; «Melhor não.» cancela; «Não, pode seguir.» não autoriza).
- Trilha: `fora_do_escopo` (a causa da pergunta de fechar aba), e o `portao` continua gravando `objetivo` quando o escopo soltou.

## Não provado em máquina real

- A sua voz dizendo as frases naturais com o ASR da Groq (os testes usam ASR falso com sinais fortes).
- A extensão recarregada com `tabs.close` no seu Brave.
- A pergunta que surge no meio do primeiro passo do turno ainda é só na faixa (item 2) — com o escopo, só para o que está fora dele.

## Como invalidar esta decisão

- Uma frase natural lida como «sim» que o dono não quis dizer: vira caso de teste e a lista encolhe.
- Uma ação contida que o dono queria que perguntasse: a linha sai da tabela (decisão dele).
