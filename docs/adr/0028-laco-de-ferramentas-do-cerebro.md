# ADR-0028 — Laço de ferramentas do cérebro: o modelo propõe tool tipada, o código dispõe

**Data:** 2026-10-17 · **Estado:** aceita para implementar a fatia 6 — pelo diretor, em
2026-10-17, em nome do dono; **o dono pode revisar** · **Decide:** dono (o alcance, os apps e os
sites que ele autoriza), planejador (o desenho)
**Pedido:** fatia 6 do roteiro da F2 — o dono quer testar o Jarvis executando comandos — com o
ajuste dele (2026-10-17): **execução não é o modelo montando comando**; são tools tipadas com
parâmetro nomeado, resolvidas pelo código. Detalha a SPEC §4, §5.3, §5.5 e §5.6 e as ADRs 0003,
0009, 0010 e 0025.

## Contexto

O cérebro (ADR-0025) já fala em stream e cancela no epoch, mas não tinha como **agir**: o
`PedidoDeTool` existia no contrato do motor e era ignorado. O catálogo tinha manifestos sem
corpo, e o PDP decidia sem que ninguém pudesse confirmar na tela. O motor provisório (`claude -p`,
ADR-0018) roda **sem ferramenta nenhuma** de propósito.

## Decisão

1. **O laço.** Cada rodada do motor devolve texto (que já sai falado) e pedidos de ferramenta.
   O cérebro executa os pedidos pelo executor; o resultado volta ao **contexto da vez** como
   `Mensagem("ferramenta", …)` — dado de terceiros, nunca instrução, e o motor continua sem
   estado (ADR-0025, regra 2). Teto: 4 rodadas e 3 chamadas por rodada. Interromper cancela a
   ferramenta cancelável e encerra o laço; o motor não é chamado de novo.
2. **A cadeia de uma chamada** (`jarvis.executor.ferramentas`): tool no catálogo **ligado**
   (manifesto + corpo) e na allowlist do modo → `input_schema` inteiro do manifesto → PDP →
   confirmação na janela quando a política manda → corpo sobre a raiz aberta no grant →
   auditoria (decisão antes, resultado depois).
3. **Confirmação só pelo dono.** `Pdp.decidir(…, confirmado_pelo_dono=True)` troca `confirm` por
   `allow` (nunca `deny` por nada); só o executor o passa, e só depois do "sim" na janela. A
   pergunta aparece na mesma faixa das pendências do Workspace (permitir/não, texto puro), com
   **prazo de 30 s que nega**; interromper o turno com a pergunta aberta também é não. Enquanto
   espera, o núcleo mostra a vez do dono.
4. **Catálogo v1 ligado nesta fatia:** `files.list_dir`, `files.read_text`,
   `files.search_in_roots` (leitura, em qualquer modo, sobre as raízes que o modo libera —
   `roots: []` no manifesto quer dizer "as do modo ativo"; o PDP resolve a raiz pelo caminho);
   `files.write_draft` e `calendar.create_draft_event` (escrita **só** na pasta do Jarvis, com
   confirmação por ação, sem sobrescrever — o modelo não passa caminho); `apps.launch(nome)` e
   `sites.open(url)` (pedido do dono). Memória (ADR-0026) e lixeira têm manifesto e ainda não
   têm corpo aqui: não aparecem para o modelo.
5. **Alcance padrão = nenhuma pasta do dono.** `acesso = "jarvis"` na configuração: só a área do
   Jarvis (`<estado>/area`, que contém só os rascunhos — não o cofre nem os dados). O dono sobe
   para `padrao`/`concedido`/`total` editando a configuração (P12). A lista de negação da §5.5
   vale em todo modo, inclusive na listagem (o que ela cobre nem aparece).
6. **`apps.launch(nome)`**: o nome é resolvido contra um **registro** montado dos `.desktop` do
   sistema e filtrado por `apps_autorizados` do dono; nome fora dele é negado com os parecidos.
   Roda o `Exec` do `.desktop` (códigos de campo retirados), por `os.posix_spawn` com `argv` em
   lista, sem shell, com ambiente saneado e sessão própria; `Exec` que começa por shell ou por
   elevação é recusado ao montar o registro. A regra de política dá `allow` só ao app do
   registro (grant estreito da §5.3).
7. **`sites.open(url)`**: só `http`/`https` com host e sem credencial embutida; abre pelo portal
   `org.freedesktop.portal.OpenURI` (D-Bus, sem processo filho; Windows: `os.startfile`). É
   `egress` e confirma, **exceto** nos domínios que o dono liberou (`sites_sem_confirmar`, com
   subdomínios). Não lê nem controla a página — isso é a ADR-0027.
8. **Sem shell, por varredura.** A varredura do executor (`test_sem_shell.py`) passou a pegar
   `fork`, `exec*`, `spawn*`, `posix_spawn` e `startfile`, além do que já pegava; as duas únicas
   exceções são nomeadas no teste (`lancador.py`: `posix_spawn`; `sites.py`: `startfile`) e o
   teste cobra que elas não tenham nada além disso.
9. **Proposta do `claude -p` provisório por protocolo de texto.** Como a CLI roda sem tools, o
   prompt de sistema leva o **catálogo fixo do modo** (braço C0 da ADR-0024, sem Jev) e a regra:
   propor é uma linha `<<ferramenta>> {"tool_id": …, "args": {…}}`. O adaptador separa essas
   linhas da fala ainda no stream; JSON inválido vira pedido malformado, que o executor recusa
   e o motor fica sabendo. Linha com a marca **dentro de um resultado** (arquivo, página) não é
   proposta: só o que o motor gera passa pelo leitor.

## Alternativas descartadas

- **Shell com allowlist de comandos** — é o canivete-suíço que a §4 proíbe: o poder depende do
  texto. O pedido do dono fecha isso.
- **Ferramentas nativas da CLI do Claude (MCP para a CLI)** — tiraria o PDP do caminho e
  amarraria o laço a um motor; o motor definitivo (D18) ainda vai ser escolhido.
- **Confirmar por voz** — a §5.3 aceita voz para `escrita_recuperavel`, mas o ASR ainda não é
  medido em pt-BR na máquina do dono; nesta fatia, confirmação é só na tela.

## Consequências

- O dono testa pedidos reais na janela (passo a passo em `docs/COMO-TESTAR.md`, seção 0.1).
- Com o motor provisório, o texto da conversa vai para a nuvem; com `eco` (padrão), nenhuma
  ferramenta é proposta.
- Passa a ser obrigatório testar: nada sem a decisão do PDP; confirmação vencida nega; interromper
  cancela; conteúdo de arquivo não vira chamada; o segredo não chega ao modelo.

## Emenda de 2026-10-20 (ADR-0031): pensar não é falar

O status curto entre passos (7096c1a) saiu: o dono não acompanha passo a passo. O cérebro fala
no máximo um aviso curto antes da primeira ferramenta e o resultado; a narração das rodadas
seguintes e o que o modelo diz depois de propor vão para o raciocínio do turno, que volta ao
motor na rodada seguinte com o que o dono já ouviu. Os passos de navegação (`browser.navigate`,
`click`, `type`, `scroll`) não falam o aviso (`aviso_silencioso`); a frase fica na auditoria.

## Como invalidar esta decisão

- O `claude -p` real não seguir o protocolo de texto com confiabilidade (teste do dono): o
  protocolo é refeito ou o laço espera o motor com `tool_use` estruturado (D18).
- O dono quiser confirmar por voz: entra quando o ASR em pt-BR estiver medido, com a mesma regra
  de "só o dono".
- Uma ferramenta precisar de caminho de escrita fora da pasta do Jarvis: é tool nova, com
  manifesto e confirmação próprios, nunca esticando `files.write_draft`.
