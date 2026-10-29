# ADR-0050 — Executor de scripts isolado: Python ou JS do Jarvis numa caixa sem rede, sem os arquivos do dono e com limites

**Data:** 2026-10-29 · **Estado:** aceita (pedido do dono) · **Decide:** dono (existir, sem rede por padrão, não tocar nos arquivos dele), arquiteto (a caixa, os limites, o contrato do resultado)
**Pedido:** dono, 2026-10-29 — "EXECUTOR DE SCRIPTS isolado: Python/JS escritos pelo Jarvis, em contêiner (podman) ou bubblewrap, sem rede por padrão, timeout, limites de CPU/RAM/saída, pasta temporária descartável, sem tocar nos arquivos do dono; resultado volta como DADO." Camada B da ADR-0049; o guarda de contexto (ADR-0049) decide cada chamada antes do PDP.

## Contexto

Depurar e automatizar às vezes pede uma conta, uma transformação de texto, um trecho de lógica — coisa que o modelo escreve melhor como script do que como sequência de ferramentas. Rodar esse script é, pela SPEC §4, o canivete suíço que o lint recusa: o efeito depende do texto que o modelo escreve. O que o torna aceitável é a **caixa**: o script não vê a rede, não vê os arquivos do dono, não demora nem gasta sem limite, e **só** devolve o que imprimiu, como dado. A máquina do dono tem `bubblewrap 0.12` e `podman 5.8` (medido em 2026-10-29).

## Decisão

### 1. A caixa (`jarvis.executor.scripts.CaixaDeScript`)

Backend padrão **bubblewrap** (rápido, sem daemon; ~24 ms para subir e rodar «somar 0..9» na máquina do dono, medido em 2026-10-29); `podman` fica como alternativa declarada para quem não tem bwrap (o backend é um parâmetro). Em sistema sem nenhum dos dois, a ferramenta degrada honesto (`sem_suporte`), não finge.

Cada execução sobe uma caixa nova:

- **sem rede**: `--unshare-all` (inclui a rede); o `script.rodar` com rede só existe com o sim do dono (o guarda pede), e aí a caixa compartilha só a rede, nada mais;
- **sem os arquivos do dono**: `/usr` montado **só leitura** (o interpretador e a biblioteca padrão), `/proc` e `/dev` mínimos, e uma **pasta de trabalho em tmpfs** (`/caixa`), que nasce e morre com a caixa; a casa do dono, `/home`, `/etc` sensível e os descritores do Jarvis **não são montados**;
- **o script não vira arquivo no disco**: entra por um descritor (`--ro-bind-data`), não por um caminho que fique;
- **ambiente limpo**: `--clearenv`, só `PATH`, `HOME=/caixa` e o que o dono passar como entrada; nenhuma chave, nenhum segredo (as chaves nunca são lidas, regra do dono);
- **identidade mínima**: `--cap-drop ALL`, `--new-session`, `--die-with-parent`, `--unshare-user`.

### 2. Os limites

Impostos por `prlimit` **em volta** do bwrap (os limites são herdados pelo processo do script):

| limite | padrão | como |
|---|---|---|
| tempo de parede | 10 s | `subprocess` com prazo; estourou → mata o grupo todo e devolve `estouro_de_tempo` |
| CPU | 10 s | `RLIMIT_CPU` |
| memória | 256 MiB | `RLIMIT_AS` |
| tamanho de arquivo | 16 MiB | `RLIMIT_FSIZE` |
| processos | 64 | `RLIMIT_NPROC` |
| saída lida | 64 KiB | corta a leitura e marca `saida_cortada` |

Os números são o padrão; o pedido pode apertar, nunca afrouxar além do teto do código.

### 3. O resultado é dado

`Resultado(saida, erro, codigo_de_saida, estouro_de_tempo, saida_cortada, ms)`. A saída e o erro são **texto de terceiros** (`trust_input: untrusted`): vão ao modelo como resultado, nunca como instrução, e passam pelo `redigir` do projeto antes de qualquer registro. O `script.rodar` tem `pii_touch: content` e `data_egress: local`.

### 4. A capacidade `script.rodar`

`tier: moderado`, `confirmation: never`, `risk_class: transitorio_reversivel`, `side_effect: ephemeral` (a caixa some), `access_level_min: jarvis`, `roots: []`, `executor: local-caixa`. O manifesto declara `windows` por causa da P11 (toda capacidade cobre Linux e Windows), mas o backend é Linux (bwrap/podman); no Windows a ferramenta degrada honesto (`sem_suporte`) até haver um backend (AppContainer/Job Object, não feito) — como a `browser.tela` sem motor de imagem. Argumentos: `linguagem` (`python` ou `js`), `codigo` (o texto), `entrada` (texto opcional no stdin), `rede` (bool, padrão falso). O guarda (ADR-0049) decide antes do PDP: sem rede e sem categoria de risco, passa; com rede, pede o sim; baixar/executar, credenciais, sair da pasta → barra com a instrução de volta. A caixa é a cerca mesmo quando o guarda permite.

### 5. O que a caixa **não** faz

Não é terminal nem subagente: não roda comando do sistema do dono (isso é `tarefa.iniciar` com subagente, ADR-0038), não instala pacote (`system.install_package`, perigoso), não escreve nos arquivos do dono. O script que tenta `subprocess`, `pip install`, abrir `~/`, ou rede sem o sim é barrado pelo guarda antes de entrar na caixa; se algo passar, a caixa não tem como alcançar nada disso.

## Alternativas descartadas

- **Contêiner podman em toda chamada**: mais lento para subir e exige o daemon/o armazenamento de imagem; fica como alternativa para quem não tem bwrap.
- **`seccomp` fino à mão**: o `--cap-drop ALL` + `--unshare-all` + rlimits já fecham a rede, o privilégio e o gasto; um filtro de syscalls é um ganho marginal com custo de manutenção alto. Reavaliar se um cenário concreto pedir.
- **Rodar sem caixa, confiando no guarda**: o guarda classifica e pode errar (ADR-0004); a caixa é a cerca que vale mesmo com "permitir".

## Consequências

- O modelo ganha um bloco de notas executável que não alcança nada do dono; o resultado é dado, auditável e cortado.
- Uma conta ou transformação deixa de virar dez ferramentas e idas ao motor.
- Sem bwrap nem podman, a ferramenta não aparece — como as `browser.*` sem a extensão.

## Riscos

- **Fuga da caixa**: bug do bubblewrap/kernel. Mitigação: `--cap-drop ALL`, usuário sem privilégio, sem rede, e os rlimits; acompanhar os avisos de segurança do bubblewrap.
- **Esgotar a máquina**: mitigado pelos rlimits e pelo prazo de parede, que mata o grupo.
- **tmpfs em RAM**: a pasta de trabalho é pequena (`RLIMIT_FSIZE`) e some com a caixa.

## Como invalidar esta decisão

- A caixa deixa o script alcançar a rede, a casa do dono ou um processo do sistema num teste de `tests/unit/executor/test_scripts.py` (os cenários de fuga).
- O custo de subir a caixa passa a pesar no uso real (a medição do guarda já cobre a latência da decisão; a da caixa é o tempo do bwrap, ~24 ms medido).

## Fontes (acesso em 2026-10-29)

- bubblewrap(1), opções `--unshare-all`, `--ro-bind-data`, `--cap-drop`, `--die-with-parent` — página de manual da versão 0.12 instalada.
- `prlimit(1)` e `getrlimit(2)` (RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NPROC).
