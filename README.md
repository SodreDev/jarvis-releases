<div align="center">

# J.A.R.V.I.S

**Just A Rather Very Intelligent System**

Assistente pessoal de IA desktop para Windows — controlado por voz, texto ou gestos.

[![Versão](https://img.shields.io/badge/versão-2.7.0-blue?style=flat-square)](https://github.com/NinjaZinS2/jarvis-releases/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D4?style=flat-square&logo=windows&logoColor=white)](https://github.com/NinjaZinS2/jarvis-releases/releases/latest)
[![Auto-update](https://img.shields.io/badge/auto--update-ativo-brightgreen?style=flat-square)](#atualizações-automáticas)

</div>

---

> Inspirado no mordomo da Stark Industries. Britânico, direto, sem enrolação.

O JARVIS é um assistente de IA desktop completo que roda localmente no Windows. Ele conecta múltiplos LLMs (OpenAI, Groq, Google Gemini) a um conjunto extenso de ferramentas — controle do sistema, automação, mensageria, mídia, biblioteca de jogos e muito mais — tudo acessível por voz, chat ou gestos.

---

## Funcionalidades

### 🤖 Inteligência e Linguagem
- **Multi-LLM** — OpenAI GPT-4o, Groq (LLaMA 3), Google Gemini; troca em tempo real
- **Memória persistente** — contexto salvo entre sessões; memória de contatos e preferências
- **Motor proativo** — detecta presença, monitora sistema e emite alertas sem ser acionado
- **Modo jogo** — reduz interrupções ao detectar jogo em tela cheia automaticamente

### 🎙️ Voz
- **TTS multi-engine** — Kokoro (local/offline), Edge TTS (Microsoft), ElevenLabs, Gemini TTS
- **STT** — reconhecimento de fala contínuo com filtro VAD
- **Wake word** — ouve "Jarvis" em background sem consumo perceptível de CPU
- **Normalizador TTS** — converte siglas, moedas e símbolos para fala natural (`R$ 150` → "cento e cinquenta reais")

### 🖥️ Automação do Sistema
- Abrir/fechar/mover/redimensionar janelas
- Controle de volume e mídia global
- Macros gravados e atalhos de teclado
- Gerenciamento de arquivos e pastas
- Terminal integrado (PowerShell)
- Histórico de área de transferência

### 🎮 Jogos
- Detecção automática de biblioteca em **Steam, Epic Games, EA Desktop, Xbox Game Pass, Battle.net, Ubisoft Connect**
- Suporte a múltiplas pastas de instalação por plataforma (ex: SteamLibrary em drives diferentes)
- Abrir jogos por voz: *"abre o Rust"*, *"quero jogar Counter-Strike"*
- Cache com TTL de 24 h; atualiza automaticamente ao instalar novos jogos

### 🔍 Pesquisa e Informação
- Busca na web (DuckDuckGo), Wikipedia, notícias
- Cotações de ações e criptomoedas
- Tradução de texto e dicionário
- Fetch de URLs com extração de conteúdo

### 🎵 Mídia
- Controle do Spotify (play, pause, próxima, volume, busca)
- YouTube (busca e reprodução)
- OCR em tela — lê texto de qualquer janela
- Geração de imagens (DALL·E / Stable Diffusion)
- Análise de tela com IA visual (GPT-4o Vision / Gemini)

### 💬 Mensageria
- **WhatsApp Web** — envia mensagens e arquivos
- **Discord** — envia mensagens em canais e DMs
- **Instagram** — envia mensagens diretas
- **E-mail** — lê e envia via Gmail

### 📅 Produtividade
- Agenda e lembretes com disparo por horário
- Alarmes, timers e Pomodoro
- Notas e memória de contexto
- Geração de documentos (PDF, DOCX, XLSX, PPTX)
- Rotinas automatizadas e condicionais programáveis
- Exportação de histórico de conversa
- Modo desenvolvedor com bridge para VS Code

### 🖐️ Interface de Gestos
- Controle de mouse por gestos de mão (MediaPipe)
- Workspace 3D e canvas 2D controlados por gestos
- Treinamento de gestos customizados

### 🔄 Auto-atualização
- Verifica atualizações no GitHub Releases na inicialização
- Aplica payload incremental (`.zip` com arquivos `.py`) sem reinstalar
- Reinicia automaticamente após update

---

## Instalação

### Opção 1 — Instalador (recomendado, sem Python necessário)

1. Baixe `JARVIS_Setup_vX.X.X.exe` em [Releases](https://github.com/NinjaZinS2/jarvis-releases/releases/latest)
2. Execute o instalador e siga os passos
3. Edite `credentials\.env` com suas chaves de API (template em `.env.example`)
4. Inicie pelo atalho no Menu Iniciar

O instalador já vem com Python 3.12 embutido — nenhuma instalação adicional necessária.

### Opção 2 — Código-fonte (desenvolvimento)

```powershell
# Clone o repositório
git clone https://github.com/NinjaZinS2/jarvis.git
cd jarvis

# Crie o ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Instale as dependências
pip install -r requirements.txt

# Configure as credenciais
Copy-Item credentials\.env.example credentials\.env
# Edite credentials\.env com suas chaves

# Execute
python main.py
```

---

## Configuração

Todas as credenciais ficam em `credentials/.env` (nunca versionado):

```env
# LLM (ao menos uma obrigatória)
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
GOOGLE_API_KEY=AIza...

# TTS (opcional — Kokoro funciona sem chave, offline)
ELEVENLABS_API_KEY=...

# Spotify (opcional)
SPOTIPY_CLIENT_ID=...
SPOTIPY_CLIENT_SECRET=...
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback

# Discord (opcional)
DISCORD_BOT_TOKEN=...

# Instagram (opcional)
INSTAGRAM_USERNAME=...
INSTAGRAM_PASSWORD=...
```

**Mínimo para funcionar:** apenas `GROQ_API_KEY`. Sem nenhuma chave, use LM Studio rodando local na porta 1234.

### APIs disponíveis

| Serviço | Variável | Para que serve | Onde obter |
|---|---|---|---|
| **Groq** *(recomendado)* | `GROQ_API_KEY` | LLM + STT (Whisper) | [console.groq.com/keys](https://console.groq.com/keys) |
| OpenAI | `OPENAI_API_KEY` | GPT-4o + Vision + DALL·E | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Google | `GOOGLE_API_KEY` | Gemini + Gemini TTS | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| ElevenLabs | `ELEVENLABS_API_KEY` | TTS premium | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) |
| Spotify | `SPOTIPY_CLIENT_ID` + `_SECRET` | Controle do player | [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) |
| LM Studio | — | LLM 100% local/offline | [lmstudio.ai](https://lmstudio.ai) — porta 1234 |

---

## Como usar

### Wake word (voz)

Diga **"Jarvis"** seguido do comando:

```
"Jarvis, que horas são?"
"Ei Jarvis, abre o Spotify"
"Jarvis, traduz essa frase pra inglês"
"Jarvis, quero jogar Counter-Strike 2"
```

### Interface gráfica

Três temas disponíveis: **Stark Classic**, **macOS** e **Minimal**.
Digite o comando diretamente se preferir não usar voz.

---

## Comandos disponíveis

### Sistema e apps

| Comando de exemplo | O que faz |
|---|---|
| `"abre o Discord"` | Abre qualquer app instalado |
| `"fecha o Spotify"` | Fecha o processo |
| `"desliga o PC"` / `"reinicia"` / `"hiberna"` | Controle de energia |
| `"bloqueia a tela"` | Bloqueia a sessão Windows |
| `"captura a tela"` | Screenshot + salva em disco |
| `"volume em 50%"` | Controla volume do sistema |
| `"executa [comando] no terminal"` | PowerShell integrado |

### Jogos

| Comando de exemplo | O que faz |
|---|---|
| `"quais jogos eu tenho?"` | Lista toda a biblioteca (Steam, Epic, EA, Xbox...) |
| `"abre o Rust"` / `"quero jogar Counter-Strike"` | Abre o jogo pela plataforma correta |
| `"instala [jogo]"` | Abre a loja da plataforma no jogo |
| `"modo jogo"` | Otimiza sistema para gaming |

### Música e entretenimento

| Comando de exemplo | O que faz |
|---|---|
| `"toca [música/artista/playlist]"` | Spotify |
| `"pausa"` / `"próxima música"` | Controle de playback |
| `"reproduz [vídeo] no YouTube"` | Abre e toca no YouTube |

### Mensagens

| Comando de exemplo | O que faz |
|---|---|
| `"manda mensagem pro [contato] no WhatsApp: [texto]"` | WhatsApp |
| `"manda pro [contato] no Instagram: [texto]"` | Instagram DM |
| `"envia pro [nome] no Discord: [texto]"` | Discord |
| `"manda email pro [contato]: [assunto] — [texto]"` | Gmail |

### Pesquisa e informação

| Comando de exemplo | O que faz |
|---|---|
| `"que horas são?"` / `"que dia é hoje?"` | Hora e data |
| `"como está o tempo em [cidade]?"` | Clima e previsão |
| `"qual a cotação do dólar?"` | Cotação em tempo real |
| `"pesquisa [assunto]"` | Busca na web + resume |
| `"o que é [termo]?"` | Wikipedia |
| `"traduz [frase] pra [idioma]"` | Tradução |

### Produtividade

| Comando de exemplo | O que faz |
|---|---|
| `"cria um timer de 25 minutos"` | Timer com alerta sonoro |
| `"cria um alarme para [hora]"` | Alarme com voz |
| `"anota: [texto]"` | Salva nota na memória |
| `"agenda [evento] para [data/hora]"` | Adiciona à agenda |
| `"modo Pomodoro"` | Inicia ciclo 25/5 min |

### Visão e análise

| Comando de exemplo | O que faz |
|---|---|
| `"o que tem na minha tela?"` | Analisa screenshot com IA visual |
| `"lê o texto da tela"` | OCR da tela atual |

### Modos de operação

| Modo | Ativação | Efeito |
|---|---|---|
| **Jogo** | `"modo jogo"` | Silencia notificações, libera VRAM |
| **Foco** | `"modo foco"` | Bloqueia distrações, respostas curtas |
| **Descanso** | `"modo descanso"` | Tom mais casual |
| **Silencioso** | `"modo silencioso"` | TTS desativado, só texto |
| **Trabalho** | `"modo trabalho"` | Perfil produtividade ativo |

---

## Atualizações automáticas

30 segundos após o startup, JARVIS verifica se há nova versão no GitHub. Se houver, aplica o payload incremental (arquivos `.py`) e reinicia automaticamente — sem interação do usuário.

Para forçar manualmente:

```powershell
python -m updater.check_update --check    # apenas verifica
python -m updater.check_update --apply    # baixa e aplica
```

O payload incremental atualiza apenas os arquivos `.py`. Uma atualização completa via instalador só é necessária quando há mudanças no executável PyInstaller.

---

## Estrutura de pastas

> Para a visão técnica completa (arquitetura, fluxo de build/release, camadas de
> configuração), veja [ARCHITECTURE.md](ARCHITECTURE.md).

```
J.A.R.V.I.S/
├── main.py              # Entry point, JarvisApp, roteador principal
├── config.py            # Configurações e constantes globais
├── launcher.py          # Launcher do executável (.exe)
├── version.py           # Detecção automática de versão
├── VERSION              # Número de versão atual
│
├── comandos/            # Ferramentas do assistente (~40 módulos)
│   ├── games_ctrl.py    # Biblioteca de jogos multi-plataforma
│   ├── spotify_ctrl.py  # Controle do Spotify
│   ├── browser_ctrl.py  # Automação web (Playwright)
│   ├── msg_sender.py    # Roteador de mensagens
│   ├── tool_registry.py # Registro de ferramentas para o LLM
│   └── ...
│
├── core/                # Serviços de infraestrutura
│   ├── game_platform_detector.py  # Detectores por plataforma
│   ├── game_library.py  # Cache agregado da biblioteca de jogos
│   ├── proactive_engine.py        # Alertas proativos
│   ├── ambient_listener.py        # Wake word em background
│   ├── event_bus.py     # Barramento de eventos interno
│   └── ...
│
├── VozIa/               # Engines de TTS
│   ├── kokoro_tts_engine.py  # TTS local (offline)
│   ├── elevenlabs_tts.py
│   └── gemini_tts.py
│
├── updater/             # Sistema de auto-atualização
│   └── check_update.py
│
├── gesture_interface/   # Controle por gestos (MediaPipe)
├── ui/                  # Frontend HTML/CSS/JS (webview)
├── installer/           # Script Inno Setup + ícone
├── security/            # Sanitização e permissões
├── credentials/         # Chaves e preferências (gitignored)
└── tools/               # Pipeline de build e release
```

---

## Build e Release

```powershell
# Rebuild completo + instalador + publicar no GitHub
.venv\Scripts\python.exe tools\make_release.py 2.2.5

# Apenas payload (sem rebuild do .exe — muito mais rápido)
.venv\Scripts\python.exe tools\make_release.py 2.2.5 --skip-build
```

Gera em `installer/output/`:
- `JARVIS_Setup_vX.X.X.exe` — instalador completo com Python embutido
- `update_payload_vX.X.X.zip` — payload incremental (só `.py`)
- `SHA256SUMS.txt` — checksums de verificação

---

## Requisitos

| Componente | Mínimo |
|---|---|
| Sistema | Windows 10 64-bit (build 1903+) |
| RAM | 4 GB (8 GB recomendado) |
| Python | 3.12 (incluso no instalador) |
| Espaço em disco | ~2 GB (incluindo modelos Kokoro) |
| Microfone | Para wake word e comandos de voz |
| GPU | Opcional — recomendada para LM Studio local (≥4 GB VRAM) |

---

## Changelog

### v2.7.0 — Cérebro agêntico + Suíte de documentos

**🧠 Cérebro & tool-calling (acerto com modelos baratos)**
- **OpenRouter** como provedor (drop-in OpenAI-compatible) com **Auto Router** (`openrouter/auto`) e **cadeia de fallback robusta**: modelo específico → Auto Router → Groq → LM Studio → chat, sem travar.
- **Modo "Cérebro total"**: o LLM **sempre raciocina sobre o contexto** com todas as ferramentas + histórico (não dispara comando exato fora de contexto).
- Seleção de ferramentas por **camadas** + **schema estrito** opcional; **chamadas paralelas** de ferramentas; **histórico/contexto adaptativo** ao limite do modelo (4 → 200k-1M).
- **Modelos grátis/baratos por tarefa** (pensar / arquivos / imagem) e **seleção visual** de provedor, modelos e toggles na aba **Modelos**.

**📄 Suíte de documentos (geração via IA)**
- **Apresentações (.pptx)** — `spec→render` com **25 layouts** + composição livre por blocos (grid 12 colunas), design tokens, imagens e gráficos.
- **Relatórios (.pdf)** — HTML/CSS→PDF via Chromium: capa, seções, KPIs, **gráficos**, tabelas, callouts, sumário, headers/footers; estilos por tipo (executivo/financeiro/técnico).
- **Planilhas (.xlsx)** — formatos por coluna (moeda/percent/data), **formatação condicional** (escala/data bars/ícones), **gráficos nativos**, painel de KPIs, freeze panes.
- **Exportar para PDF** — converte `.docx/.xlsx/.pptx`→PDF com alta fidelidade (MS Office / LibreOffice).
- **Gerador de imagem** roteado (OpenRouter pago/grátis → Pollinations com backoff), proporção por layout.

**🐛 Correções**
- Transcrição de voz (Whisper) e visão voltam a usar o **Groq real** mesmo com OpenRouter selecionado (corrige erro 400 de content-type).
- Corrigido crash ao trocar de tema (`set_ui_pref`) e a aplicação **ao vivo** da troca de provedor.

**🔭 Planejado (em projeto — `planning/roadmap/`)**
- Memória **semântica/vetorial em RAM** + **orquestrador semântico** leve (decisor/roteador instantâneo).
- **Cognição humana**: personalidade persistente, reflexão e aprendizado contínuo de conteúdo novo.
- Execução por **código** (programmatic tool calling), ícones embutidos, DOCX no mesmo padrão, e refino visual contínuo.

> Recursos novos do cérebro saem **desligados por padrão** (toggles na aba Modelos) — ative conforme preferir.

### v2.2.6
- **BrowserPool**: corrige "contexto morto" após fechar o Chromium — listener do evento `close` + health-check recriam o contexto a partir dos cookies em disco, sem exigir novo login
- **`#jarvis` em DMs**: resposta automática via LLM em **todas as plataformas** (WhatsApp, Instagram, Discord, Telegram, Gmail) pelo roteador Chromium, sem depender de pyautogui
- **Instagram**: envio de DMs via Chromium (roteador), com fallback para pyautogui só se o backend não estiver disponível
- **Steam**: descoberta de múltiplas bibliotecas via `libraryfolders.vdf` (jogos em drives secundários, ex.: `F:\SteamLibrary`)

### v2.2.5
- **YouTube**: corrige crash "Cannot switch to a different thread" (greenlet) ao buscar/reproduzir vídeos por voz
- **Steam**: jogos instalados fora do disco C: (ex.: `F:\SteamLibrary`, `B:\SteamLibrary`) agora são detectados (lê `libraryfolders.vdf`)
- **EA App**: melhor descoberta de diretórios de instalação (leitura de arquivos `.ini`)
- **Release**: `make_release.py` poda `node_modules` e outros diretórios grandes no scan (build mais rápido)

### v2.2.4
- Jogos EA Desktop detectados via `ProgramData\EA Desktop\InstallData\` — funciona independente do drive de instalação
- Xbox Game Pass: detecção por `gamelaunchhelper.exe` no AppxManifest (4 jogos reais, zero falsos positivos)
- Steam: filtro de redistributables (Steamworks Common Redistributables, DirectX, VCRedist, .NET)
- Xbox: DisplayName correto extraído do AppxManifest.xml

### v2.2.3
- Correção do caminho do Chromium (Playwright) no app frozen pelo PyInstaller

### v2.2.2
- Auto-update: aplica payload e reinicia automaticamente sem interação manual

### v2.2.1
- Playwright: instalação automática do Chromium na primeira execução

### v2.2.0
- Biblioteca de jogos multi-plataforma (Steam, Epic, EA, Xbox, Battle.net, Ubisoft)
- Comandos `listar_jogos`, `abrir_jogo`, `instalar_jogo` registrados no LLM

---

## Licença

Distribuído sob a **Apache License 2.0** — veja [LICENSE](LICENSE) para os termos completos e [NOTICE](NOTICE) para as atribuições.

Este projeto redistribui modelos pré-treinados do **Google MediaPipe** (`hand_landmarker.task`, `face_landmarker.task`, `blaze_face_short_range.tflite`, em `gesture_interface/gesture_data/`), também sob Apache-2.0 e de propriedade do Google LLC / MediaPipe Authors. Consulte o [NOTICE](NOTICE).

---

## Autor

**NinjaZinS2** — [github.com/NinjaZinS2](https://github.com/NinjaZinS2)

---

<div align="center">
Feito com Python 3.12 · pywebview · Kokoro TTS · Playwright · PyInstaller
</div>


1. Baixe `JARVIS_Setup_vX.Y.Z.exe` em [Releases](https://github.com/NinjaZinS2/jarvis-releases/releases)
2. Execute o instalador e siga os passos
3. Opcional: marque **"Inicializar JARVIS com o Windows"** para aparecer no Gerenciador de Tarefas → Inicialização
4. Ao finalizar, clique em **"Iniciar JARVIS agora"**

O instalador já vem com Python 3.12 embutido — o usuário não precisa instalar nada além do instalador.

---

### Opção 2 — Código-fonte (desenvolvimento)

**Pré-requisitos:** Python 3.12, Git

```powershell
# 1. Clone
git clone https://github.com/NinjaZinS2/jarvis-releases.git
cd jarvis-releases

# 2. Crie o ambiente virtual
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as credenciais (veja seção abaixo)
Copy-Item credentials\.env.example credentials\.env

# 5. Execute
python main.py
```

---

## Configuração

Todas as credenciais ficam em `credentials/.env`. Edite o arquivo e preencha apenas os serviços que for usar — tudo é opcional exceto ao menos uma chave de LLM.

### APIs disponíveis

| Serviço | Variável | Para que serve | Onde obter |
|---|---|---|---|
| **Groq** *(recomendado)* | `GROQ_API_KEY` | LLM (chat + Whisper) | [console.groq.com/keys](https://console.groq.com/keys) |
| LM Studio | — | LLM local (sem internet) | [lmstudio.ai](https://lmstudio.ai) — rode o servidor na porta 1234 |
| ElevenLabs | `ELEVENLABS_API_KEY` | Voz sintética premium | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) |
| Spotify | `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` | Controle do player | [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) |
| Discord bot | `DISCORD_BOT_TOKEN` | Leitura de canais/membros | [discord.com/developers/applications](https://discord.com/developers/applications) |
| Discord user | `DISCORD_USER_TOKEN` | Envio silencioso de mensagens | F12 no Discord → Application → Local Storage → `token` |
| Instagram | `INSTAGRAM_USERNAME` + `INSTAGRAM_PASSWORD` | Envio de DMs | Sua conta normal |

> **Mínimo para funcionar:** só `GROQ_API_KEY`. Sem ela, use LM Studio rodando local.

### Modelo de LLM

Em **Configurações → Modelos** dentro da interface:
- **Groq** — recomendado para a maioria dos usuários (gratuito, rápido)
- **LM Studio** — para rodar 100% offline com GPU local

---

## Como usar

### Wake word (voz)

Diga **"Jarvis"** (ou "Ei Jarvis", "Hey Jarvis") seguido do comando.

```
"Jarvis, que horas são?"
"Ei Jarvis, abre o Spotify"
"Jarvis, traduz essa frase pra inglês"
```

### Interface gráfica

Três temas disponíveis na barra superior: **Stark Classic**, **macOS** e **Minimal**.  
Digite o comando diretamente no campo de texto se preferir não usar voz.

### Botão `?`

Clique no `?` em qualquer tema para abrir o guia de configuração de APIs com links diretos.

---

## Comandos disponíveis

### Sistema e apps

| Comando de exemplo | O que faz |
|---|---|
| `"abre o Discord"` | Abre o Discord (ou qualquer app instalado) |
| `"abre minha DM com [nome] no Discord"` | Navega até a conversa privada no Discord |
| `"abre o YouTube"` | Abre no navegador padrão |
| `"fecha o Spotify"` | Fecha o processo do app |
| `"desliga o PC"` / `"reinicia"` / `"hiberna"` | Controle de energia |
| `"bloqueia a tela"` | Bloqueia a sessão Windows |
| `"captura a tela"` / `"print"` | Screenshot + salva em disco |
| `"volume em 50%"` / `"muda o volume"` | Controla volume do sistema |
| `"brilho em 70%"` | Controla brilho (notebooks) |

### Navegador

| Comando de exemplo | O que faz |
|---|---|
| `"abre google.com"` | Abre URL no navegador padrão |
| `"pesquisa [assunto]"` / `"googla [assunto]"` | Busca no Google |
| `"nova aba"` / `"fecha aba"` | Atalhos no Chrome/Edge/Firefox |
| `"rola a página pra baixo"` | Scroll via automação |
| `"clica em [elemento]"` | Clique via visão computacional |
| `"preenche [campo] com [valor]"` | Preenchimento de formulários |

### Música e entretenimento

| Comando de exemplo | O que faz |
|---|---|
| `"toca [música/artista/playlist]"` | Busca e toca no Spotify |
| `"pausa a música"` / `"continua"` | Play/pausa Spotify |
| `"próxima música"` / `"volta a música"` | Pular faixas |
| `"volume do Spotify em 80%"` | Volume do player |
| `"reproduz [vídeo] no YouTube"` | Abre e toca no YouTube |

### Mensagens e comunicação

| Comando de exemplo | O que faz |
|---|---|
| `"manda mensagem pro [contato] no WhatsApp: [texto]"` | Envia mensagem no WhatsApp |
| `"manda pro [contato] no Instagram: [texto]"` | Envia DM no Instagram |
| `"envia pro [nome] no Discord: [texto]"` | Envia mensagem no Discord |
| `"abre a DM com [nome] no Discord"` | Abre conversa privada |
| `"manda email pro [contato]: [assunto] — [texto]"` | Envia e-mail |
| `"lê minhas notificações"` | Lê notificações recentes |

### Informações e pesquisa

| Comando de exemplo | O que faz |
|---|---|
| `"que horas são?"` / `"que dia é hoje?"` | Hora e data atual |
| `"como está o tempo em [cidade]?"` | Clima atual e previsão |
| `"qual a cotação do dólar?"` | Cotação em tempo real |
| `"pesquisa [assunto]"` | Busca na web + resume |
| `"o que é [termo]?"` | Consulta Wikipedia |
| `"traduz [frase] pra [idioma]"` | Tradução instantânea |
| `"o que significa [palavra]?"` | Dicionário |

### Produtividade

| Comando de exemplo | O que faz |
|---|---|
| `"cria um timer de 25 minutos"` | Timer com alerta sonoro |
| `"cria um alarme para [hora]"` | Alarme com voz |
| `"anota: [texto]"` | Salva nota na memória |
| `"o que eu anotei sobre [assunto]?"` | Recupera anotações |
| `"agenda [evento] para [data/hora]"` | Adiciona à agenda |
| `"abre minha agenda"` | Lista eventos próximos |
| `"modo Pomodoro"` | Inicia ciclo 25/5 min |
| `"modo descanso"` / `"modo foco"` | Muda personalidade e comportamento |
| `"modo jogo"` | Otimiza para gaming (libera VRAM, muda perfil) |

### Arquivos e clipboard

| Comando de exemplo | O que faz |
|---|---|
| `"abre [arquivo/pasta]"` | Abre no Explorer ou app associado |
| `"copia [texto]"` / `"cola"` | Controle de clipboard |
| `"histórico da área de transferência"` | Lista últimas N cópias |
| `"exporta [dado] como PDF"` | Geração de PDF |

### Visão e análise de tela

| Comando de exemplo | O que faz |
|---|---|
| `"o que tem na minha tela?"` | Analisa screenshot com IA visual |
| `"lê o texto da tela"` | OCR da tela atual |
| `"analisa essa imagem"` | Descreve imagem aberta |

### Terminal e código

| Comando de exemplo | O que faz |
|---|---|
| `"executa [comando] no terminal"` | Roda comando no PowerShell |
| `"gera um script que [descrição]"` | Gera código via LLM |
| `"abre o VS Code"` | Abre o editor |

### Contatos

| Comando de exemplo | O que faz |
|---|---|
| `"adiciona contato [nome]: [telefone/usuário]"` | Salva contato |
| `"qual o número do [nome]?"` | Busca na agenda |
| `"lista meus contatos"` | Exibe agenda |

### Modos de operação

| Modo | Ativação | Efeito |
|---|---|---|
| **Jogo** | `"modo jogo"` | Silencia notificações, libera VRAM, resposta mínima |
| **Foco** | `"modo foco"` | Bloqueia distrações, respostas curtas |
| **Descanso** | `"modo descanso"` | Tom mais casual, agenda pausada |
| **Silencioso** | `"modo silencioso"` | TTS desativado, só texto |
| **Trabalho** | `"modo trabalho"` | Perfil produtividade ativo |

### Proativo e presença

Quando detecta ausência do usuário (via câmera ou inatividade):
- Guarda mensagens recebidas no WhatsApp/Instagram/Discord
- Responde automaticamente se configurado (`AWAY_AUTO_REPLY=true`)
- Reporta tudo ao retornar: `"o que aconteceu enquanto eu estava fora?"`

### Atualizações automáticas

30 segundos após o startup, JARVIS verifica se há nova versão no GitHub. Se houver, aparece um toast no canto inferior direito com botão de download — sem interromper o uso.

---

## Estrutura de pastas

```
J.A.R.V.I.S/
├── main.py              # Ponto de entrada principal
├── config.py            # Configurações globais e prompts
├── launcher.py          # Launcher do executável (.exe)
├── credentials/         # Credenciais e dados pessoais (gitignored)
│   ├── .env             # Suas chaves de API (você cria a partir do .env.example)
│   └── .env.example     # Template documentado
├── comandos/            # Módulos de controle (um por domínio)
├── core/                # Motor: VAD, roteador, presença, modos
├── ui/                  # Interface Web (3 temas: Stark, macOS, Minimal)
├── VozIa/               # Síntese de voz (ElevenLabs, Kokoro, edge-tts)
├── updater/             # Verificação e aplicação de atualizações
├── installer/           # Script Inno Setup + ícone
└── tools/               # Pipeline de build e release
```

---

## Build / Release

```powershell
# Rebuild completo + gerar instalador + publicar no GitHub
.venv\Scripts\python.exe tools\make_release.py 2.1.0
```

Gera em `installer/output/`:
- `JARVIS_Setup_v2.1.0.exe` — instalador completo com Python embutido
- `update_payload_v2.1.0.zip` — payload para o sistema de auto-update
- `SHA256SUMS.txt` — checksums de verificação

---

## Requisitos (dev / from source)

- Windows 10/11 64-bit
- Python 3.12+
- ~4 GB de espaço (dependências incluindo torch/mediapipe)
- Microfone (para wake word / comandos de voz)
- GPU com VRAM ≥ 4 GB recomendada para LM Studio local (opcional)

---

## Licença

Distribuído sob a **Apache License 2.0** — veja [LICENSE](LICENSE) para os termos completos e [NOTICE](NOTICE) para as atribuições.

Este projeto redistribui modelos pré-treinados do **Google MediaPipe** (`hand_landmarker.task`, `face_landmarker.task`, `blaze_face_short_range.tflite`, em `gesture_interface/gesture_data/`), também sob Apache-2.0 e de propriedade do Google LLC / MediaPipe Authors. Consulte o [NOTICE](NOTICE).

---

## Autor

**NinjaZinS2** — [github.com/NinjaZinS2](https://github.com/NinjaZinS2)
