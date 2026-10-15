# ADR-0009 — Quatro níveis de acesso escolhidos pelo dono, elevação em interruptor separado, tudo aplicado por código

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** dono (os níveis), arquiteto (o enforcement)

## Contexto

O dono definiu o modelo: o alcance do Jarvis no disco é **escolha dele**, em quatro níveis — (1) só pastas padrão, (2) só a pasta do Jarvis, (3) pastas específicas concedidas, (4) PC inteiro — mais um **interruptor separado** que permite ou não elevação (admin no Windows, `sudo`/root no Linux). Isso é política determinística em código, nunca decisão do LLM (P1).

Dois detalhes técnicos forçam o desenho:

- A numeração do dono não é crescente em alcance: o nível 2 (só a pasta do Jarvis) é **mais estreito** que o nível 1 (pastas padrão). Os nomes do dono são preservados; o enforcement usa uma ordem de amplitude explícita, e a UI lista nessa ordem.
- Verificar caminho como **texto** e depois abrir é a receita clássica de TOCTOU: entre a checagem e a abertura, um link simbólico trocado leva a escrita para fora da raiz. A decisão tem de valer sobre o **descritor aberto**, não sobre a string. [SUPOSIÇÃO: nenhuma medição nossa ainda; a suíte de corrida da F0-06 é o que confirma que a implementação resiste.]

## Decisão

1. **Quatro modos, uma ordem de amplitude.** `jarvis` (nível 2) ⊂ `padrao` (nível 1) ⊂ `concedido` (nível 3) ⊂ `total` (nível 4). O modo materializa um `root_set`: lista de raízes canônicas com permissão por raiz (ler/escrever/lixeira).
2. **Lista de negação vence até no `total`.** Cofres de credencial e segredo (`~/.ssh`, `~/.gnupg`, chaveiros, perfis de navegador, gerenciador de senha, `.env`, caches de token, `/etc/shadow`; no Windows credenciais do DPAPI, hives do registro, LSASS) e carteiras de cripto nunca entram em raiz autorizada. "PC inteiro" não é "credenciais".
3. **Enforcement em dois lugares independentes:** o PDP decide sobre argumentos normalizados (nível, raiz, classe de risco, elevação) e o **executor** verifica de novo no momento da chamada de sistema. Uma falha sozinha não basta para sair da raiz.
4. **O executor recebe capacidade, não string.** No momento do grant, a raiz é aberta uma vez e o executor opera **relativo a esse descritor** (`openat2` com `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS` no Linux; handle com `FILE_FLAG_OPEN_REPARSE_POINT` + `GetFinalPathNameByHandle` no Windows), conferindo identidade do arquivo (device+inode / file id) contra o que foi autorizado. Nome fora da raiz deixa de ser expressável.
5. **Canonicalização é obrigatória e específica por SO:** normalização unicode, `..` resolvido antes de comparar, recusa de ADS (`:`), nomes 8.3, dispositivos reservados (`CON`, `NUL`, `COM1`…), UNC/`\\?\`, caminho relativo a unidade (`C:foo`), ponto/espaço no fim, e comparação com case-folding completo no Windows.
6. **Elevação é ortogonal ao nível, desligada por padrão.** `total` não implica elevação. Com o interruptor desligado, toda capacidade `requires_elevation: true` é **filtrada do catálogo antes do modelo ver** — o planejador não pode nem propor. Ligado, cada uso é por ação, confirmado na UI, com TTL curto, uma chamada por vez, registrado com o `argv` exato. O segredo é digitado pelo dono no prompt do SO (polkit/UAC); o Jarvis nunca captura, armazena ou reusa, nunca instala regra `NOPASSWD`, nunca mantém sessão root aberta e nunca roda como serviço privilegiado.
7. **O nível só muda pela UI, com o dono presente.** Não existe capacidade que mude nível ou elevação (verificado por teste que varre o catálogo); voz sozinha não muda; conteúdo `third_party` e servidor MCP não mudam. Mudança bump `policy_epoch`, invalida grants de amplitude maior, vale a partir da próxima fronteira de turno — **reduzir** vale na hora e cancela chamadas em voo; **ampliar** exige confirmação explícita na UI e é anunciado por voz.
8. **Nível amplia o alcance, nunca reduz o rigor.** Mesmo no `total`, continuam exigindo confirmação: destrutivo/irreversível, egress e representação, instalar ou executar baixado, mudar sistema/permissão/VPN/firewall, a própria elevação, lote acima do teto, e qualquer coisa fora do diretório do dono. Credencial continua barreira entregue ao dono (§5.3), não item confirmável.
9. **Auditoria encadeada por hash, à prova de edição silenciosa:** decisão registrada **antes** do efeito, resultado anexado depois, cada registro carrega o sha256 do anterior. Legível, filtrável e exportável na UI.

## Alternativas descartadas

- **Um único "modo seguro" com lista de pastas:** não é o que o dono pediu e não dá como explicar na UI o que o Jarvis alcança.
- **Elevação herdada do nível 4:** junta duas decisões de risco muito diferentes; o dono pediu interruptor separado e está certo.
- **Confiar na checagem de string (`startswith` da raiz):** quebra com link simbólico, `..`, ADS e corrida. É o bug que a F0-06 existe para provar que não temos.
- **Rodar o executor como root e "ter cuidado":** viola P1 e apaga a distinção entre pedir e poder.
- **Sandbox do SO (bwrap/AppContainer) como única defesa:** desejável como camada extra em fase posterior, mas não substitui o PDP nem o descritor confinado, e varia demais entre Linux e Windows para ser o alicerce da F0.

## Consequências

- Mais fácil: explicar ao dono em uma tela o que o Jarvis pode tocar, e provar por auditoria o que tocou.
- Mais caro: toda tool de arquivo passa a ser escrita contra descritor de raiz, não contra caminho; o SDK de tool tem de oferecer isso pronto, senão alguém vai usar `open()` direto.
- Passa a ser obrigatório testar: troca de link simbólico em corrida, hardlink, ponto de montagem, raiz apagada no meio da operação, ADS/8.3/UNC/dispositivo no Windows, grant revogado durante a chamada, e redução de nível com chamada em voo.
- O manifesto de capacidade ganha `access_level_min`, `roots` e `requires_elevation` (SPEC §4), e o CI recusa manifesto sem eles.

## Como invalidar esta decisão

Uma suíte de TOCTOU que a implementação não consiga passar com descritor confinado nos dois SOs — aí a resposta não é relaxar a regra, é reduzir o alcance das capacidades de escrita até que passe. Ou o dono mudar o modelo de níveis, que é prerrogativa dele.
