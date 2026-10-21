# Handoff — trilha de diagnóstico do turno (telemetria local, só metadados)

Pedido do dono (2026-10-20, Lote B item 1): para melhorar o Jarvis é preciso ver o que ele fez no
turno — ferramentas e duração, decisões do PDP/Jev/pendência, motivo de cada confirmação e os
erros de ferramenta e de seletor — **sem nunca** gravar segredo, credencial, texto ou DOM de
página, fala/áudio da conversa, valor de argumento ou URL inteira com dado privado.

## Formato

JSONL, uma linha por evento, em UTF-8. Cabeçalho de toda linha: `t` (epoch, 3 casas), `turno`
(`t-<uuid7>`) e `evento`. Tipos de evento e o que cada um carrega (`EVENTOS` em
`src/jarvis/trilha.py`):

- `turno.inicio` — `motor`, `epoch`, `caracteres_do_pedido`.
- `ferramenta.inicio` — `tool_id`, `argumentos` (só os **nomes**), `pdp`, `fase`.
- `ferramenta` — `tool_id`, `argumentos`, `status`, `pdp`, `ms`, `motivo`, `codigo`, `aviso`,
  `fase`.
- `portao` — `tool_id`, `pdp`, `jev`, `decisao`, `ms`.
- `permissao` — `tool_id`, `origem`, `motivo`, `resposta`.
- `metodo` — `metodo`, `motivo`, `de_fora`.
- `turno.fim` — `fim`, `cancelado`, `objetivo`, `erro`; os tempos `ms_primeiro_token`,
  `ms_primeira_fala`, `ms_primeiro_audio` e `ms_total`; as contagens `ferramentas`,
  `caracteres_falados`, `caracteres_de_raciocinio`, `raciocinio_descartado`, `narracao_retida` e
  `resultados_podados`.

## Allowlist, não blacklist

Dois níveis, ambos fechados:

1. `EVENTOS` — que campos aquele evento pode ter. Campo de fora **não é gravado**; só o nome dele
   vai para `campos_fora` (para a omissão aparecer em vez de ficar escondida). Evento de tipo
   desconhecido grava só o cabeçalho e os nomes dos campos: nenhum valor entra.
2. `CAMPOS` — a forma de cada nome de campo, igual em qualquer evento: `NUMERO`, `BOOLEANO`,
   `CODIGO` (slug curto do nosso código), `ROTULO` (48 car.), `MOTIVO` (160 car.), `CAUSA` e
   `CHAVES` (nomes de argumento). Valor que não cabe na forma vira `[fora_da_forma]`.

O `motivo` (de `ferramenta`, `permissao` e `metodo`) tem a forma `CAUSA`: só um **código** da
allowlist `CAUSAS` — `palavra_de_risco`, `envia_formulario`, `elemento_sem_nome`,
`categoria_do_site`, `destino_externo`, `dado_do_dono_para_fora`, `confirmacao_do_pdp`,
`acao_recusada`, `erro_da_ferramenta`, os motivos do método… — ou vários unidos por `+` (a janela
em foco da entrada virtual: `enter_envia+turno_contaminado`). Qualquer outra coisa vira
`[fora_da_forma]`: a frase da pergunta ao dono cita o rótulo que a página dá ao elemento e **não
entra**, nem cortada (auditoria dos Lotes B e C, achado 2). Quem escolhe o código é o caminho que o
código tomou (`Avaliacao.causa` do risco, `Confirmacao.causa`, `ResultadoDeFerramenta.causa`), nunca
a frase; resultado sem causa grava `sem_codigo`. A frase continua na janela, na resposta ao modelo e
na auditoria. O `codigo` do evento `ferramenta` é o da extensão (`alvo_ausente`) e só é lido do
**começo** do motivo («a página não deixou (…)»): um "(algo)" no rótulo do elemento não vira código.

Nos campos de texto que sobram (`jev`, `erro`, `pdp` — frases que o **nosso** código escreve, nunca
o dono nem a página) ainda passa `redigir` do projeto, a URL fica em `esquema://host/…`, o caminho
em `/…` e o resto é cortado. Para registrar um campo novo é preciso declará-lo nas duas tabelas —
o teste `test_todo_campo_de_todo_evento_tem_forma_declarada` não deixa um evento permitir campo sem
forma.

## Localização, permissões, rotação e retenção

- Arquivo: `$XDG_STATE_HOME/jarvis/voz/diagnostico/turnos.jsonl` (padrão
  `~/.local/state/jarvis/voz/diagnostico/`) — o diretório de estado que o app já usa; sem rede.
- Permissões: pasta `0700`, arquivo `0600`. Uma trilha antiga com permissão frouxa é corrigida no
  primeiro evento da sessão.
- Rotação: 512 KiB por arquivo, 3 cópias (`.1`, `.2`, `.3`) → ~2 MB no total, teto fixo.
- Retenção: 7 dias. Arquivo sem toque há mais que isso é apagado — no primeiro evento da sessão e
  a cada volta do arquivo.
- Falha de disco não derruba o turno: a trilha é ajuda, não requisito (`OSError` é engolido).

## `jarvis-voz --diagnostico`

A seção «último turno» mostra os limites acima (onde mora, quanto gira, quanto dura) e o resumo do
último turno: tempos e etapas, decisões do portão e do PDP, motivo de cada permissão e o código de
erro — sem conteúdo privado. Honesto por construção:

- sem turno → «nenhum turno registrado (a trilha nasce no primeiro pedido; o que passa de 7 dias é
  apagado)»;
- turno sem `turno.fim` → «sem linha de fim: o turno foi interrompido ou o app saiu antes»;
- `ferramenta.inicio` sem o `ferramenta` correspondente → «começou e não terminou».

## Onde mexer

- `src/jarvis/trilha.py` — tabelas, formas, rotação/retenção/permissões, resumo e `limites`.
- `src/jarvis/executor/ferramentas.py` — `ferramenta.inicio`/`ferramenta` e `permissao`.
- `src/jarvis/s2/fluxo_de_acao.py` — `portao` e a `permissao` da pendência.
- `src/jarvis/voz/app.py` — `turno.inicio`/`turno.fim` e a pasta da trilha (`PASTA_DA_TRILHA`).
- `src/jarvis/navegador/risco.py` e `src/jarvis/entrada/controle.py` — a causa de cada pergunta
  do risco dinâmico.
- Testes: `tests/unit/test_trilha.py`, `tests/unit/voz/test_trilha_do_app.py`,
  `tests/unit/voz/test_cli.py`; o rótulo sentinela da página fora da trilha em
  `tests/unit/navegador/test_ferramentas_browser.py` e `tests/unit/s2/test_portao_de_acao.py`.
  COMO-TESTAR §0.10.

## Limites conhecidos

- A retenção é por **arquivo** (mtime), não por linha: numa sessão longa o arquivo vivo pode ter
  linha mais velha que 7 dias. O teto de tamanho é que segura o volume.
- O `motivo` é um código da allowlist `CAUSAS`: causa nova precisa entrar lá, senão a trilha grava
  `[fora_da_forma]` no lugar dela (a causa se perde, a frase nunca vaza). O `jev` e o `erro` ainda
  são frases do nosso código: a redação e o encurtamento protegem, mas quem escrever uma nova
  precisa continuar não colando nelas dado do dono nem texto de página.
- `resumo_do_ultimo_turno` lê o arquivo vivo e o `.1`; um turno que caia inteiro no `.2` não
  aparece no `--diagnostico`.
