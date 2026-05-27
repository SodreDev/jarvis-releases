# J.A.R.V.I.S

Assistente de voz pessoal para Windows. Controla o PC, responde em voz, envia mensagens, toca músicas, monitora notificações e executa rotinas — tudo por comandos de voz ou texto.

> Inspirado no mordomo da Stark Industries. Britânico, direto, sem enrolação.

---

## Instalação

### Opção 1 — Instalador (recomendado, sem Python necessário)

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

JARVIS Personal Use License v1.0 — uso pessoal e não-comercial.  
Veja [LICENSE](LICENSE) para os termos completos.

---

## Autor

**NinjaZinS2** — [github.com/NinjaZinS2](https://github.com/NinjaZinS2)
