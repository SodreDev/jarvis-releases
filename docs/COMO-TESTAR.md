# Como testar o Jarvis de voz (`jarvis-voz`)

**O que é isto:** um aplicativo de **teste**, no terminal, para você falar com o Jarvis e
julgar de ouvido a voz, a latência e a interrupção. Não é o produto da SPEC §2 (os sete
processos) — é o laço de voz da F1 montado num processo só, com um gerador de resposta
provisório (ADR-0018).

**O que já funciona aqui e o que só funciona aí:** tudo o que não depende de placa de som foi
exercitado nesta máquina (síntese com a voz do piper, transcrição, epoch, cancelamento,
degradação, configuração). O **microfone e o alto-falante reais nunca foram abertos** — não há
placa de som na máquina onde isto foi escrito, nem o PortAudio instalado. Então o caminho de
dispositivo está **não verificado**, e a primeira vez que ele roda é a sua.

---

## 1. Instalar

```bash
cd /home/sodre/GranaFacil/J.A.R.V.I.S

# o básico + os extras do caminho local de voz
uv sync --frozen --group dev --group voz --group asr --group dispositivo

# a biblioteca de áudio do SISTEMA (o sounddevice não a traz no Linux)
sudo dnf install portaudio        # Nobara/Fedora
```

Extras opcionais, só se for testar esses caminhos:

```bash
uv sync --group edge     # TTS do Edge (LGPL, e barrado por padrão — ver §6)
sudo dnf install ffmpeg  # só o Edge precisa, porque o serviço dele só devolve MP3
```

A voz do piper (63 MB) fica em `~/.cache/jarvis/vozes/pt_BR-faber-medium/`. Se não estiver aí,
o aplicativo diz isso ao subir, e você pode testar o resto com `--tts tts-parametrico`.

## 2. Exportar as duas chaves (só se for usar nuvem)

```bash
export JARVIS_GROQ_API_KEY=...
export JARVIS_ELEVENLABS_API_KEY=...
```

Ponha isso no seu `~/.bashrc` se quiser que valha sempre.

**As chaves nunca entram no repositório, na configuração nem na linha de comando.** O
aplicativo *se recusa a subir* se achar o valor de uma delas em `argv`, e a tela de
configuração mostra apenas "definida" ou "AUSENTE" — ela não lê o valor. Sem nuvem ligada,
você não precisa de chave nenhuma: o caminho local funciona sozinho.

## 3. Ver o que está pronto antes de falar

```bash
uv run jarvis-voz --diagnostico
```

Ele lista os motores registrados (e quais são de nuvem e se estão ligados), se cada chave está
definida, os dispositivos de áudio do sistema, os extras instalados e **o que falta** para cada
motor rodar — com o motivo escrito.

## 4. Falar

```bash
uv run jarvis-voz            # o laço de voz (microfone e alto-falante)
uv run jarvis-voz --texto    # o mesmo laço, digitando — funciona sem placa de som
```

No laço de voz:

- **a barra de espaço interrompe o Jarvis** no meio da fala (é o barge-in: o epoch morre, a
  fila de playback esvazia e nada do resto é tocado);
- **`q` sai**;
- o turno fecha sozinho depois de ~0,7 s de silêncio.

**Limite honesto do terminal:** terminal não avisa quando você *solta* uma tecla. O PTT de
verdade (segurar para falar) é da interface gráfica, no `audio-io`. Aqui a barra **alterna**.

## 5. Escolher provedores (a tela de configuração)

```bash
uv run jarvis-voz config
```

Você escolhe: quem ouve (ASR local ou Groq), quem fala (piper+epitran, ElevenLabs ou Edge), a
voz, o modelo do ASR local, quem responde (eco ou a CLI do Claude), microfone, alto-falante e
PTT × VAD. Grava em `~/.config/jarvis/jarvis-voz.toml`.

**Escolher um motor de nuvem não o liga.** A tela mostra, antes, o que sai da sua máquina,
para onde, qual a retenção declarada pelo serviço e quem é o dono do áudio — e pede um "sim"
digitado por extenso. Enquanto você não confirmar, o motor fica escolhido e **desligado**.

## 6. O que você precisa saber sobre cada motor de nuvem

| motor | o que sai daqui | o que o serviço declara (lido na origem em 2026-10-15) |
|---|---|---|
| Groq (`whisper-large-v3-turbo`) | **o seu áudio** | não retém por padrão para inferência, mas os endpoints de áudio ficam sob monitoração de abuso por **até 30 dias**; não treina com a entrada (§4.2); a saída é sua (§8.1). US$ 0,04/h, **mínimo de 10 s por requisição** — um turno de 2 s é cobrado como 10 s, e o diagnóstico conta quantas vezes isso aconteceu |
| ElevenLabs | **o texto que o Jarvis vai falar** | **retém por padrão** ("history preservation enabled"); o modo sem retenção é só Enterprise; a saída é sua (§4); o plano gratuito é **só para uso não comercial** |
| Edge (read-aloud) | **o texto que o Jarvis vai falar** | **não há termos publicados para este uso.** Por isso ele é barrado: o portão só o libera se você aceitar explicitamente, duas vezes, na tela. Não é local — o dono achava que fosse |

## 7. O que esperar

- **primeira fala:** o aplicativo aquece a voz local ao subir, então o primeiro turno não paga
  o carregamento do modelo (sem o aquecimento, era ~1,8 s nesta máquina; com ele, ~70 ms até o
  primeiro pedaço de áudio). Esse número é **observação de uma execução**, não medição: a
  medição com hardware, n e três execuções é o cartão F1-16, na sua máquina;
- **sem rede:** o Jarvis avisa em uma frase, cai para o botão de falar e **não refaz** o pedido
  que caiu;
- **sem microfone:** ele diz o que falta (inclusive o comando para instalar o PortAudio) e
  oferece o `--texto`;
- **chave errada:** você lê "o serviço recusou o pedido (401) … confira a chave", não "estou
  sem internet".

## 8. O que ainda **não** foi verificado (e só você pode verificar)

1. **microfone e alto-falante reais.** Nenhum dispositivo foi aberto por este código; o
   PortAudio nem está instalado aqui;
2. **barge-in perceptível ao ouvido.** A nossa fila esvazia no mesmo tique, mas a fila do
   *driver* não é nossa: `limpar` aborta o fluxo sem conseguir dizer quantas amostras o
   sistema ainda tinha para tocar. Isso é o aceite do F1-16;
3. **qualidade da voz com `epitran`.** A fonemização passou a marcar tônica por regra (antes
   não marcava nenhuma) e cobre todo o inventário da voz — mas se **soa bem** é o seu ouvido
   que diz;
4. **WER do ASR em pt-BR**, local ou na Groq: nenhum model card publica, e ninguém mediu aqui;
5. **chamada real à nuvem.** Toda a suíte fala com um servidor falso em porta efêmera; sob
   `CI=1` o código **recusa** falar com serviço de verdade. A primeira chamada real é sua.

## 9. Como reportar

Rode e me mande, nesta ordem:

```bash
uv run jarvis-voz --diagnostico > /tmp/jarvis-diagnostico.txt 2>&1
uv run jarvis-voz --texto                    # se o áudio não subir
uv run jarvis-voz                            # o laço de voz
```

O que ajuda no relato: **o que você ouviu** (robótico? atropelado? tônica no lugar errado?), a
linha `[ouvi … · asr … · resposta … · 1º pedaço … · fala …]` que aparece depois de cada turno,
e o `/tmp/jarvis-diagnostico.txt`. Se travar, `Ctrl+C` e me diga em que parte da frase estava.

Áudio só se você quiser: nada é gravado por padrão.
