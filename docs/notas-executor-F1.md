# Notas de implementação da F1 (executor)

Decisões de implementação, divergências e **limites do que foi verificado** durante os cartões
da F1. O que muda contrato está marcado como **emenda proposta** — a SPEC só muda por ADR.

Regra desta fase, do próprio mapa de cartões: na ausência do dono, o cartão publica o **piso de
software**, com essa etiqueta, e segue. Número de hardware real não se estima.

**Autor:** executor · **Início:** 2026-10-15

---

## F1-01 — banco de teste de áudio sem microfone

### O tempo entra pela porta, não pelo `time.monotonic_ns()`

`src/jarvis/relogio.py` tem `Relogio` (protocolo), `RelogioDoSistema` e `RelogioFalso`. Quem
olha o tempo no caminho de áudio recebe um relógio; nada chama o relógio global direto. As duas
fontes de teste também **ritmam** a entrega por ele (`dormir(20 ms)` antes de cada quadro):

- com `RelogioDoSistema`, um WAV de 1,7 s leva 1,7 s para atravessar a cascata;
- com `RelogioFalso`, atravessa instantaneamente e **com os mesmos carimbos** em toda execução.

É isso que faz a asserção de latência ser exata em vez de "± o que o CI estava fazendo":
`tests/unit/audio_io/test_replay.py` afirma `instantes_ms == [20, 220, 820, 1120, 1520]` e que
todo instante é múltiplo de 20 ms, sem nenhum `sleep` real.

### Três implementações atrás da mesma interface

`FonteDeAudio` e `SumidouroDeAudio` são protocolos (`fontes.py`, `sumidouros.py`), com
implementação de `arquivo` (WAV PCM16 mono 16 kHz), `sintetico` (gerador por semente) e
`dispositivo` (real). A escolha vem de `JARVIS_AUDIO_BACKEND`; **valor desconhecido é erro**, não
silêncio com padrão, e o padrão de quem não disse nada é `sintetico` — ninguém abre a placa de
som do dono por omissão.

O WAV fora do formato do caminho de captura (8 kHz, estéreo, 8 bits) é **recusado na abertura**
com a lista do que estava errado, em vez de ser reamostrado por engano: reamostragem silenciosa
mudaria o número que a F0-04 mediu.

### A proibição do CI mora no código, não só na fixture

`proibir_dispositivo_em_ci` recusa com `CI` ligado (`1|true|yes|on|sim`), e a fixture *autouse*
de `tests/conftest.py` liga `CI=1` na suíte inteira. São duas camadas de propósito: a fixture
protege os testes que ainda nem foram escritos; a função protege o produto. Os dois caminhos
têm teste, inclusive o de fora do CI — onde a recusa **muda de motivo** (sem backend real
instalado, declarado no próprio erro).

### O detector desta cascata não é o VAD

Para a trilha ter uma decisão a registrar, existe `DetectorDeEnergia` (limiar em dBFS, sem
histerese). **Não é o VAD do projeto**: o `silero-vad` com histerese e janela de 512 amostras é
o cartão F1-05. Todo relatório que usar este detector diz o nome dele.

Armadilha que custou iteração: com o envelope silábico indo a zero entre sílabas, o detector sem
histerese oscilava a cada sílaba e a trilha virava 13 eventos de ida e volta. O remédio certo foi
**o gerador parecer com voz** (piso de 0,3 no envelope) e não dar histerese ao detector antes do
cartão dele — fala humana não cai para o silêncio digital entre sílabas. A trilha passou a ter
exatamente os 5 eventos do roteiro.

### A trilha guarda decisão, não ruído

`EventoDeTrilha` carrega `type`, `epoch`, `ts_mono_ns` e as chaves essenciais do payload; ficam
de fora `event_id` (uuid v7) e `ts_wall`, que mudam a cada execução sem significar nada. Float
vai arredondado a 3 casas, para formatação não virar divergência. `comparar` devolve a
**primeira** divergência com índice, chave e os dois valores — e trilha mais curta é divergência,
não empate.

### Determinismo é entre execuções na mesma máquina

O gerador é `random.Random(semente)` (Mersenne Twister, igual em toda plataforma) **mais**
`math.sin` (libm do sistema). Então o aceite comparado é "duas execuções na mesma máquina dão a
mesma trilha", que é o que o cartão pede; hash fixo entre sistemas operacionais **não** é
afirmado em nenhum teste, de propósito — seria um teste que quebra no Windows por motivo que não
é o nosso.

### Armadilha achada de fora do cartão: a suíte reescrevia medição publicada

`tests/unit/test_harness_captura.py` rodava o harness da F0-04 em amostra pequena e ele
publicava em `docs/medicoes/` — então **todo `pytest` substituía o CSV e o relatório de
n = 10 000 por um de n = 200**, e o repositório ficava sujo depois de qualquer execução. Como
este cartão é justamente o banco de teste, o conserto entrou aqui: `tools/harness_captura.py`
ganhou `--saida` (padrão `docs/medicoes`) e o teste de fumaça escreve em pasta temporária.
Medição publicada é dado comitado; teste não a reescreve.

### Não verificado (exige hardware real)

- **Jitter de captura, *xruns*, latência e período do driver (PipeWire/WASAPI) e deriva de
  relógio do dispositivo: nada disso foi medido.** Nenhum dispositivo de áudio real foi aberto
  por este código — `FonteDeDispositivo` e `SumidouroDeDispositivo` existem como adaptadores que
  **recusam com motivo** em vez de devolver silêncio e fingir captura. O backend real entra com o
  microfone do dono (F1-13/F1-16).
- A suíte roda em Linux. O job `windows-latest` do CI continua **nunca executado** (sem remoto;
  ver notas da F0): o que roda nos dois sistemas é afirmação de código (só `wave`, `array`,
  `math`, `pathlib` da biblioteca padrão), não de execução.
