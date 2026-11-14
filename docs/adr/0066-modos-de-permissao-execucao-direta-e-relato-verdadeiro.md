# ADR-0066 — Modos de permissão (automático e bypass), execução direta e relato verdadeiro

**Data:** 2026-11-14 · **Estado:** aceita (implementada e testada com fakes; o uso real é do dono) · **Decide:** dono (acabar com os pedidos de permissão, aceitando os riscos; o que ainda pergunta; o envio direto), arquiteto (onde cada regra mora)
**Pedido:** decisão do dono de 2026-11-14 (memória `dbb1c726`). Emenda: ADR-0046 (tabela de permissões), ADR-0048 (sim por voz), ADR-0049 (guarda de contexto), ADR-0057 (escopo do pedido), ADR-0060 (envio social), ADR-0065 (injeção). Relaciona: ADR-0038 (ciclo do objetivo), ADR-0051 (CDP), ADR-0053/0054 (delegar).

## Contexto

- O dono pediu «abre o contato da minha mãe e diz eu te amo». O Jarvis pediu permissão para rodar JavaScript na página, não executou, e mesmo assim **disse** que tinha aberto o contato e perguntou se mandava a mensagem. Três defeitos de uma vez: pergunta que não devia existir, parada antes do objetivo, e relato falso.
- As perguntas vinham de vários lugares: o `confirm` do PDP (tier `perigoso`, `exige_o_sim` do alvo, o guarda de contexto da ADR-0049 na zona cinza), o «pedir permissão» do Jev no portão, o risco dinâmico do navegador (enviar em mensageiro) e a própria persona, que mandava o modelo esperar o sim para «enviar mensagem em nome dele».
- O dono decidiu: acabar com os pedidos. Pedido direto dele é para executar.

## Decisão

### 1. Dois modos de permissão, salvos e trocáveis no painel e pela voz

- **Automático** (o padrão): o Jarvis decide sozinho. Só pedem o sim as ações **destrutivas** — `apps.quit`, `window.close`, `jarvis.encerrar`, `files.move_to_trash`, `memoria.apagar` (`jarvis.politica.permissao.DESTRUTIVAS`) —, e mesmo nelas só quando a regra de sempre já pedia (trabalho não salvo, tarefa no ar, lixeira).
- **Bypass**: nada pede o sim.
- **Onde mora:** num lugar só, no `Pdp._registrar`: o `confirm` que o modo dispensa vira `allow`, com o motivo «modo automático: sem pedir o sim — <o porquê que pediria>» na auditoria. Assim valem de uma vez o tier, o `exige_o_sim`, o guarda (`pedir_confirmacao` vira `exige_o_sim`) e o risco dinâmico do navegador e da entrada virtual (o segundo pedido ao PDP). No portão (`FluxoDeAcao`), o «pedir permissão» do Jev vira «fazer» no modo que dispensa; o «não fazer» continua vetando.
- **O que não muda (não é pedido de permissão):** `deny` do PDP (lista de negação: chaves, cofres, perfis de navegador — nunca lidos, logo nunca impressos nem exfiltrados; catálogo; nível de acesso a pastas), o «barrar» do guarda (script que lê cookie/senha), o «não fazer» do portão, e a auditoria de toda decisão.
- **Injeção (emenda à ADR-0065):** ação com efeito num fluxo que leu conteúdo que tenta dar ordens **não é pedido direto do dono**: no automático continua pedindo o sim (é o invariante de não exfiltrar); no bypass, não.
- **Salvo:** `permissao = "automatico" | "bypass"` no `jarvis-voz.toml`; o painel (Acesso → pastas → «permissões») grava no clique; vale no próximo passo, sem reiniciar.
- **Pela voz:** «ativa o modo bypass», «volta pro modo automático», «modo bypass». Quem lê é o **código** (`comando_de_permissao`), antes do motor, só na fala ou digitação do dono (`TRUST_DO_DONO`). Nenhuma ferramenta troca o modo: texto de página ou de mensagem que diga «modo bypass» não chega lá. O PDP solto (testes) usa `MATRIZ`, a matriz inteira da §5.5; o aplicativo sempre passa o modo do dono.
- **Persona:** «pedido direto é para executar»; quem pede o sim é o sistema, só no destrutivo; se um caminho travar, tente outro antes de desistir.

## Alternativas descartadas

- **Desligar as regras uma a uma (guarda, escopo, portão, risco do navegador):** seis lugares, e o sétimo esquecido voltaria a perguntar. O modo age no ponto por onde todo `confirm` passa.
- **Uma ferramenta `permissao.modo` para o modelo:** o texto de uma página poderia pedir «modo bypass». Comando lido pelo código na fala do dono, não.
- **Bypass também sem o «não fazer» do Jev e sem a lista de negação:** o dono pediu o fim das perguntas, não o fim dos invariantes.

## Consequências

- O escopo do pedido (ADR-0057) e a autorização explícita do portão deixam de ser necessários nos dois modos (não há pergunta a evitar); seguem no código para o modo `MATRIZ`.
- A confirmação por voz (ADR-0046/0048) só aparece no destrutivo (automático) e na injeção.
- O dono aceita o risco: no bypass, uma ação errada do modelo roda sem pergunta. A trilha e a auditoria dizem o modo e o porquê que teria perguntado.

## Como testar

`docs/COMO-TESTAR.md`, «Modos de permissão (ADR-0066)». Testes: `tests/unit/politica/test_permissao.py`, `tests/unit/s2/test_portao_de_acao.py` (os do fim).
