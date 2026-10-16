# ADR-0015 — canal de áudio entre `audio-io` e `agentd`, fora do barramento

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** dono (emenda à SPEC §2 e §3)
**Aceita em:** 2026-10-15, pelo dono.
**Mede:** executor, cartão F1-10 (achado) · **Commit da medição:** `7272d0c`
**Emenda aplicada** na aceitação: §2 (a seta "frames + PlaybackProgress" do desenho) e §3.1 (o
alcance do "todo evento no barramento, sem exceção") passaram a citar esta ADR. É o que o
CONTRIBUTING manda: a SPEC manda, e só é emendada por ADR — aceitar esta sem tocar na SPEC
deixaria o código errado por definição.
**Gatilho de reabertura:** ver "Como invalidar".

## Contexto

A §2 desenha uma seta de `audio-io` para `agentd` com "frames + PlaybackProgress", e a §3 diz
que **todo evento** no barramento carrega o envelope comum (`event_id`, `session_id`, `epoch`,
`ts_mono_ns`, `ts_wall`, `source`, `trust`, `priority`, `type`, `payload`) e entra no log
encadeado por hash. As duas frases juntas, lidas ao pé da letra, mandam o PCM pelo barramento.

Isso não fecha. Um quadro de 20 ms a 16 kHz são **640 bytes** de amostras. O envelope da §3,
serializado em JSON com o payload em base64, passa de 1 kB; e cada evento é validado na borda e
**gravado no log append-only encadeado por hash**. São **50 quadros por segundo**, 3 000 por
minuto. O F0-04 mediu o custo de um evento no barramento: **0,384 ms p95** (ADR-0014). Mandar
áudio por ali seria 19 ms de CPU por segundo de áudio só de barramento, e um log de eventos que
cresce em PCM — para transportar algo que **não é decisão**: é sinal.

O que o barramento é bom em carregar é decisão auditável (`AudioActivity`, `Cancel`,
`PlaybackProgress`, `ToolResult`). O que o áudio precisa é de ritmo e de descarte: quadro velho
não vale nada, e quadro de **epoch morto** menos ainda (§3.3, ADR-0002).

Por isso este cartão abriu o canal **ao lado** do barramento e **mediu três candidatos**, com o
produtor em outro processo, no ritmo real de 20 ms. Medição publicada em
`docs/medicoes/f1-canal.{csv,md}`, harness em `tools/harness_canal.py`, commit `7272d0c`.

- hardware: AMD Ryzen 5 5600G (12 fios), 31 GiB de RAM, Linux 7.2.9 (Nobara 44), Python 3.12.14;
- `n` = 1500 quadros de 20 ms por execução (30 s de áudio), **3 execuções**, mesmo áudio
  determinístico nos três braços; latência pelo `CLOCK_MONOTONIC`, que os dois processos
  compartilham no Linux;
- capacidade: 64 quadros (1,28 s) nos três.

| canal | p50 | p95 | p99 | máximo | jitter p95 | descartados | tortos |
|---|---:|---:|---:|---:|---:|---:|---:|
| `anel` (`shared_memory` circular, selo duplo) | 22,3 µs | **47,1 µs** | 58,8 µs | 542,4 µs | 205,9 µs | 0 | 0 |
| `socket` (`AF_UNIX` + `SOCK_DGRAM` dedicado) | 27,9 µs | **50,2 µs** | 65,0 µs | 397,2 µs | 284,2 µs | 0 | 0 |
| `conexao` (`multiprocessing.Connection`) | 31,6 µs | **59,3 µs** | 68,1 µs | 281,6 µs | 298,3 µs | 0 | 0 |

Teto de vazão sem ritmo (não é o caso de uso, é sanidade): anel 141 k, `conexao` 124 k, socket
119 k quadros/s — contra os **50 quadros/s** que o produto precisa, 2 400× de folga no pior.

## Decisão proposta

**(1) O áudio sai do barramento.** `audio-io` → `agentd` ganha um canal dedicado, de amostras,
com **`epoch` no cabeçalho** (primeiro campo, antes de `seq`): descartar quadro de epoch morto
custa ler 4 bytes, sem desserializar o resto. O barramento continua sendo o **único** caminho de
evento e decisão, e o log encadeado continua sendo o que ele é — a §3 não perde nada, porque
**quadro de áudio não é evento**: não tem `type`, não tem `trust`, não vira log. O que entra no
log é o que o `agentd` **conclui** do áudio (`AudioActivity`, `PartialTranscript`, `Cancel`).

Cabeçalho (`struct "<IIQI"`, 20 bytes): `epoch` u32, `seq` u32, `ts_mono_ns` u64, `amostras`
u32; payload PCM16 *little endian*, 640 bytes por quadro. `descrever_formato()` imprime isso em
texto, porque a ADR-0014 deixou `audio-io` e `agentd` trocáveis por Rust e o canal precisa ser
reimplementável sem ler Python.

**(2) A implementação escolhida é `CanalDeConexao` (`multiprocessing.Connection`) — e a latência
não é o motivo.** É a parte honesta desta ADR: **o número não decide**. Os três candidatos
ficam entre 47 e 59 µs p95, **~340× abaixo** do período de 20 ms de um quadro e **0,015% do
orçamento de 80 ms do SLO-1**; os 12 µs que separam o melhor do pior são **0,01% do SLO-1**.
Escolher por isso seria fingir precisão. Quem decide é o critério que sobra, e ele é o **P11
(roda nos dois sistemas)**:

- `AF_UNIX` + `SOCK_DGRAM` **não existe** no Python para Windows (não há `AF_UNIX` em datagrama
  no `socket` do CPython para Windows): o braço `socket` morre no P11;
- `shared_memory` existe nos dois, mas com semântica de nome diferente e precisando do **selo
  duplo** para detectar escrita pela metade — é código nosso de concorrência em cada sistema;
- `multiprocessing.Connection` é portátil **e é o transporte que o barramento já usa** desde o
  F0-03 (`AF_UNIX` no Linux, `AF_PIPE` no Windows, `authkey` HMAC por sessão). O canal de áudio
  reaproveita `endereco()` e `ler_chave()` e só troca o nome do arquivo (`audio.sock`, ou sufixo
  `-audio` no *named pipe*): **canal novo não inventa autenticação**.

O `anel` **fica no repositório**, medido e testado, como alternativa pronta: é a opção de cópia
zero para o dia em que `audio-io` for Rust (gatilho da ADR-0014). Um teste afirma que
`canal_do_ambiente()` devolve `CanalDeConexao`, para a escolha não voltar por acidente.

**(3) Os dois processos passam a usar o canal de verdade.** `agentd --canal-de-audio` escuta (o
`accept` numa linha de execução de fundo, porque o laço do corretor não pode bloquear
esperando conexão) e drena os quadros descartando epoch morto; `audio-io --canal-de-audio`
conecta e envia cada quadro **já pela cadeia AEC → NR → AGC** (F1-04). Com isso o F1-10 deixa de
ser inteiramente simulado: `tests/integration/test_canal_entre_processos.py` mede o barge-in com
os **dois processos de verdade**, quadro → VAD → `Cancel` → fila esvaziada, pelos carimbos do log
encadeado.

## Alternativas descartadas

- **PCM no barramento (o que a §2 e a §3 dizem hoje, lidas ao pé da letra):** 0,384 ms p95 por
  evento × 50/s, validação de borda e log encadeado crescendo em áudio, para transportar sinal
  que não é decisão. É o problema que esta ADR abre.
- **Socket `AF_UNIX`/`SOCK_DGRAM` dedicado:** o melhor equilíbrio no Linux (50,2 µs p95, sem
  código de concorrência nosso), e **não** tem caminho no Python para Windows. Volta a ser
  candidato se o canal virar Rust nos dois lados.
- **Anel em memória compartilhada agora:** mais rápido (47,1 µs p95) e o único com caminho de
  cópia zero, mas paga concorrência escrita à mão (selo antes e depois de cada posição) em dois
  sistemas, por 12 µs num orçamento de 80 ms. Fica guardado para o `audio-io` em Rust.
- **Um canal por par de processos, genérico, no barramento:** generalizar antes de ter o segundo
  consumidor. Hoje há **um** produtor e **um** consumidor; o dia em que houver dois, o desenho
  muda (está em "lacunas").
- **Deixar o F1-10 simulado em processo:** o número de barge-in sem fronteira de processo não
  responde ao SLO-2, que é o que o dono vai ouvir.

## Consequências

- **Mais fácil:** o log de eventos volta a ser legível por gente; o custo de evento do F0-04
  deixa de multiplicar por 50/s; o canal descarta em vez de bloquear, então quadro atrasado não
  vira fila crescendo (§3.3 regra 5, "nada pendurado").
- **Mais caro:** passa a haver **duas** fronteiras entre `audio-io` e `agentd` (barramento e
  canal), e o epoch tem de ser coerente nas duas. Mitigado por o epoch ir no cabeçalho do canal e
  pelo descarte ser do lado do consumidor, que é o dono do epoch (ADR-0002).
- **O SLO-2 entre processos deixa de ser só simulado**, mas ainda não é número publicado:
  `tests/integration/test_canal_entre_processos.py` exige que o barge-in com os dois processos
  de verdade caiba nos 150 ms, com os carimbos do log encadeado. É teste de orçamento, com `n`
  de uma execução por rodada de CI — **não** é medição com p50/p95 e três execuções. O número
  publicado do SLO-2 com fila de driver é o cartão **F1-16**, na máquina do dono; se este teste
  começar a ficar perto do limite antes disso, o canal reabre pelo gatilho 2 abaixo.

## Lacunas, ditas antes de alguém perguntar

1. **Windows não foi medido.** A escolha é a portátil *por construção* (é o transporte do
   barramento, que o CI já roda nos dois sistemas), mas o número de latência do canal é de
   Linux. Enquanto não houver medição no Windows, o P11 vale para o **transporte**, não para o
   número.
2. **Máquina ociosa.** Com os sete processos e o ASR consumindo CPU, o jitter piora; é por isso
   que o canal descarta.
3. **Um consumidor só.** O anel é um produtor/um consumidor por desenho, e a `Connection` é
   ponto a ponto. Dois consumidores de áudio (p. ex. ASR e gravador) exigem um canal por
   consumidor.
4. **O `ts_mono_ns` atravessa a fronteira** e só é comparável porque Linux compartilha o
   `CLOCK_MONOTONIC` entre processos. No Windows isso precisa ser reconferido antes de usar o
   carimbo do produtor para medir latência.

## Como invalidar esta decisão — o gatilho é explícito

Esta decisão cai, e o `anel` (ou um canal em Rust) assume, quando **qualquer** destes aparecer
numa medição com os sete processos de pé na máquina do dono:

1. p95 do canal acima de **1 ms** (2 ordens de grandeza do medido, ainda 1,25% do SLO-1), ou
   descarte por canal cheio com o consumidor vivo;
2. p95 do barge-in **entre processos** acima de **150 ms** (SLO-2);
3. um segundo consumidor de áudio entrar no desenho — aí o canal ponto a ponto não serve e a
   escolha reabre por **requisito**, não por número.

Quem medir isso anexa o número aqui e abre a emenda, sem pedir autorização nova: o formato do
quadro está em dados (`descrever_formato()`), e as três implementações seguem no repositório com
o mesmo contrato e os mesmos testes.
