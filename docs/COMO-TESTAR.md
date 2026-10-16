# Como abrir e testar o Jarvis

São duas formas do **mesmo** laço de voz: a **janela** (`jarvis`, ADR-0019) e o **terminal**
(`jarvis-voz`, ADR-0017/0018). A janela não substitui o terminal — ela usa o mesmo núcleo, o
mesmo epoch e a mesma configuração.

Não é o produto da SPEC §2 (os sete processos): é o laço de voz da F1 montado num processo só,
com um gerador de resposta provisório (ADR-0018).

---

## 0. Abrir a janela

```bash
cd /home/sodre/GranaFacil/J.A.R.V.I.S
uv sync --frozen --group dev --group gui --group voz --group asr --group dispositivo
uv run jarvis
```

Para abrir pelo **menu de aplicativos** (sem instalar pacote nenhum, sem sudo):

```bash
uv run jarvis --instalar-atalho     # escreve o .desktop e o ícone em ~/.local/share
```

O que a janela tem:

- **o núcleo no meio** diz em que pé o Jarvis está — parado, ouvindo você, pensando, falando.
  Os anéis **só giram quando há processamento**; parado é parado;
- **segurar para falar**: o botão "falar" ou a **barra de espaço**. Soltar fecha o turno na
  hora — é o PTT de verdade, que o terminal não tem como oferecer. Apertar também
  **interrompe** o Jarvis no meio da fala (o mesmo barge-in da barra no terminal);
- **escrever** na barra de baixo funciona a qualquer momento: a linha vira um turno no mesmo
  laço, com a mesma voz e a mesma interrupção;
- **`Esc`** interrompe, **`Ctrl+B`** fixa a barra lateral, **`1`/`2`/`3`** trocam de modo;
- **três modos**: *assistente* (núcleo grande, pouca coisa na tela), *pesquisa* (o núcleo
  encolhe e o conteúdo manda) e *execução* (várias visões ao mesmo tempo);
- **provedores e diagnóstico** abrem pela barra lateral, como módulos: lá você escolhe quem
  ouve e quem fala, liga (ou não) a nuvem, cola a chave de API — que vai para o **chaveiro do
  sistema**, nunca para um arquivo nosso — e roda o diagnóstico, o teste de microfone e o de
  voz.

**O que é demonstração, e está escrito na tela.** Não há busca na web, navegador nem terminal
ligados: os módulos dos modos *pesquisa* e *execução* são um roteiro com conteúdo deste
repositório, e cada um deles leva o selo **DEMONSTRAÇÃO** na moldura. O que é real: o estado
do laço, a transcrição, o PTT, o parar, o indicador de microfone, a configuração, o chaveiro,
o diagnóstico e os indicadores desta máquina (lidos de `/proc`).

**O que encosta na sua máquina pede confirmação.** Navegador, console, arquivos e captura de
tela existem no catálogo e **não entram sem você dizer que sim** — a faixa de confirmação
aparece acima da barra de conversa, com o motivo.

---

## 1. O terminal (`jarvis-voz`)

**O que é isto:** um aplicativo de **teste**, no terminal, para você falar com o Jarvis e
julgar de ouvido a voz, a latência e a interrupção.

**O que já funciona aqui e o que só funciona aí:** tudo o que não depende de placa de som foi
exercitado nesta máquina (síntese com a voz do piper, transcrição, epoch, cancelamento,
degradação, configuração). O **microfone e o alto-falante reais nunca foram abertos** — não há
placa de som na máquina onde isto foi escrito, nem o PortAudio instalado. Então o caminho de
dispositivo está **não verificado**, e a primeira vez que ele roda é a sua.

---

### 1.1 Instalar

```bash
cd /home/sodre/GranaFacil/J.A.R.V.I.S

# o básico + a janela + os extras do caminho local de voz
uv sync --frozen --group dev --group gui --group voz --group asr --group dispositivo

# a biblioteca de áudio do SISTEMA (o sounddevice não a traz no Linux)
sudo dnf install portaudio        # Nobara/Fedora
```

Extras opcionais, só se for testar esses caminhos:

```bash
uv sync --group edge     # TTS do Edge (LGPL, e barrado por padrão — ver §6)
sudo dnf install ffmpeg  # só o Edge precisa, porque o serviço dele só devolve MP3
```

A voz do piper (63,2 MB) fica em `~/.cache/jarvis/vozes/pt_BR-faber-medium/`. Se não estiver
aí, baixe com `uv run jarvis-voz --baixar-voz` (ou pelo botão na aba de diagnóstico da
janela): o tamanho é dito antes e o sha256 é conferido depois. Dá para testar o resto sem ela,
com `--tts tts-parametrico`.

### 1.2 Exportar as duas chaves (só se for usar nuvem)

```bash
export JARVIS_GROQ_API_KEY=...
export JARVIS_ELEVENLABS_API_KEY=...
```

Ponha isso no seu `~/.bashrc` se quiser que valha sempre.

**As chaves nunca entram no repositório, na configuração nem na linha de comando.** O
aplicativo *se recusa a subir* se achar o valor de uma delas em `argv`, e a tela de
configuração mostra apenas "definida" ou "AUSENTE" — ela não lê o valor. Sem nuvem ligada,
você não precisa de chave nenhuma: o caminho local funciona sozinho.

### 1.3 Ver o que está pronto antes de falar

```bash
uv run jarvis-voz --diagnostico
```

Ele lista os motores registrados (e quais são de nuvem e se estão ligados), se cada chave está
definida, os dispositivos de áudio do sistema, os extras instalados e **o que falta** para cada
motor rodar — com o motivo escrito.

### 1.4 Falar

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

### 1.5 Escolher provedores (a tela de configuração)

```bash
uv run jarvis-voz config
```

Você escolhe: quem ouve (ASR local ou Groq — e, na Groq, o modelo: `whisper-large-v3-turbo`
ou `whisper-large-v3`, com o preço ao lado), quem fala (piper+epitran, ElevenLabs ou Edge), a
voz local, a voz e o modelo da ElevenLabs (`10` e `11`; em `10`, `l` lista as vozes da sua
conta), o modelo do ASR local, quem responde (eco ou a CLI do Claude), microfone, alto-falante
e PTT × VAD. Grava em `~/.config/jarvis/jarvis-voz.toml`. Na janela é o mesmo: em
**provedores**, clicar no provedor abre os modelos dele, o aviso e o botão de ligar.

**Escolher um motor de nuvem não o liga.** A tela mostra, antes, o que sai da sua máquina,
para onde, qual a retenção declarada pelo serviço e quem é o dono do áudio — e pede um "sim"
digitado por extenso. Enquanto você não confirmar, o motor fica escolhido e **desligado**.

### 1.6 O que você precisa saber sobre cada motor de nuvem

| motor | o que sai daqui | o que o serviço declara (lido na origem em 2026-10-15) |
|---|---|---|
| Groq (`whisper-large-v3-turbo`) | **o seu áudio** | não retém por padrão para inferência, mas os endpoints de áudio ficam sob monitoração de abuso por **até 30 dias**; não treina com a entrada (§4.2); a saída é sua (§8.1). US$ 0,04/h, **mínimo de 10 s por requisição** — um turno de 2 s é cobrado como 10 s, e o diagnóstico conta quantas vezes isso aconteceu |
| ElevenLabs | **o texto que o Jarvis vai falar** | **retém por padrão** ("history preservation enabled"); o modo sem retenção é só Enterprise; a saída é sua (§4); o plano gratuito é **só para uso não comercial** |
| Edge (read-aloud) | **o texto que o Jarvis vai falar** | **não há termos publicados para este uso.** Por isso ele é barrado: o portão só o libera se você aceitar explicitamente, duas vezes, na tela. Não é local — o dono achava que fosse |

### 1.7 O que esperar

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

## 2. Instalar o aplicativo (AppImage, `.deb`, `.rpm`)

Os três saem do **mesmo** AppDir (ADR-0020), e nada é escrito no repositório — tudo vai para
`/tmp/jarvis-dist/`:

```bash
uv run --frozen python tools/empacotar.py tudo        # AppDir + AppImage + .deb + .rpm
uv run --frozen python tools/empacotar.py verificar   # roda os três em contêiner
```

Cada artefato leva junto: o Python 3.12 relocável, as rodas da trava (`uv.lock`), os dados do
produto (`licenses/`, `schemas/`, `tabelas/`, `catalogo/`), os textos das licenças obrigatórias
e o `.desktop` com o ícone. **O peso dos modelos não vai junto**: a voz do piper (63,2 MB) e o
modelo de ASR são baixados no primeiro uso, com o tamanho dito antes e o sha256 conferido
depois.

### 2.1 AppImage — um arquivo, qualquer distro

```bash
chmod +x /tmp/jarvis-dist/Jarvis-0.0.0-x86_64.AppImage
/tmp/jarvis-dist/Jarvis-0.0.0-x86_64.AppImage
```

Sem FUSE instalado (ou dentro de um contêiner), extraia e rode:

```bash
/tmp/jarvis-dist/Jarvis-0.0.0-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

**Requisito da máquina:** o AppImage traz o Python e o Qt, mas **não** traz as bibliotecas
gráficas do sistema — trazê-las desta máquina subiria o piso de glibc e quebraria a promessa
de rodar em distro antiga. Se o Qt reclamar de `libxcb-cursor` ou parecido:

```bash
# Fedora/Nobara
sudo dnf install glib2 krb5-libs mesa-libGL mesa-libEGL libxkbcommon libxkbcommon-x11 \
    xcb-util-cursor xcb-util-wm xcb-util-keysyms fontconfig freetype dbus-libs
# Debian/Ubuntu
sudo apt install libglib2.0-0t64 libgssapi-krb5-2 libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libfontconfig1 libfreetype6 \
    libdbus-1-3
```

### 2.2 `.deb` — Debian e Ubuntu

```bash
sudo apt install /tmp/jarvis-dist/jarvis_0.0.0_amd64.deb
jarvis            # ou pelo menu de aplicativos
sudo apt remove jarvis
```

As bibliotecas do Qt entram como **dependência declarada**: o `apt` resolve sozinho.

### 2.3 `.rpm` — Fedora e Nobara

```bash
sudo dnf install /tmp/jarvis-dist/jarvis-0.0.0-1.x86_64.rpm
jarvis
sudo dnf remove jarvis
```

### 2.4 Onde cada coisa é instalada

| caminho | o que é |
|---|---|
| `/usr/lib/jarvis/python/` | o Python relocável e as dependências (o Qt fica em `.so` separados, substituíveis — obrigação da LGPL) |
| `/usr/bin/jarvis` | o lançador |
| `/usr/share/jarvis/` | os dados do produto (`licenses/`, `schemas/`, `tabelas/`, `catalogo/`) |
| `/usr/share/licenses/jarvis/` | LGPL-3.0, GPL-3.0, BSD-3 do SecretStorage, Apache-2.0 e o `NOTICE` |
| `/usr/share/applications/` e `/usr/share/icons/hicolor/` | o `.desktop` e os ícones |
| `~/.cache/jarvis/vozes/` | os modelos baixados no primeiro uso (não vêm no pacote) |
| `~/.config/jarvis/jarvis-voz.toml` | a sua configuração |

---

## 3. O que ainda **não** foi verificado (e só você pode verificar)

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

## 4. Como reportar

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
