# J.A.R.V.I.S — Melhorias Planejadas

> Documento gerado em 14/03/2026. Registra todas as melhorias e funcionalidades discutidas para implementação futura.

---

## Melhorias de Qualidade (Quick Wins)

### 1. Normalizador de Texto para TTS
**Onde:** `VozIa/kokoro_tts_engine.py` + pipeline Edge TTS em `main.py`  
**Problema:** Siglas, símbolos e abreviações são falados de forma estranha ou letra por letra.  
**Exemplos do problema:**
- `"R$ 150"` → fala "R cifrão 1 5 0" em vez de "cento e cinquenta reais"
- `"GPU"` → fala "G P U" em vez de "gépi-iú"
- `"°C"` → fala "grau C" mas sem naturalidade
- `"50%"` → fala "cinquenta porcento" (ok) mas `"100%"` às vezes falha
- URLs longas → faladas caractere por caractere

**Solução:** Criar `VozIa/tts_normalizer.py` com um pré-processador que roda antes de qualquer síntese:
```
R$ N         → "N reais"
N%           → "N por cento"
N°C / N°F    → "N graus Celsius / Fahrenheit"
GPU/CPU/RAM  → "gépi-iú / cê-pê-u / rã"
URLs         → remover ou substituir por "[link]"
e.g. / i.e.  → "por exemplo / isto é"
```

---

### 2. TTS Chunked / Streaming
**Onde:** `main.py` — método `_exibir_resposta` e pipeline de TTS  
**Problema:** Hoje a resposta completa é gerada pela IA, depois sintetizada, depois reproduzida. Para respostas longas isso cria um delay perceptível de 3–8 segundos.  
**Solução:** Dividir em sentenças ao receber o texto:
1. Detectar primeiro `"."` / `"!"` / `"?"` → sintetizar e iniciar reprodução imediatamente
2. Enquanto a primeira sentença é falada, sintetizar a segunda em paralelo (thread)
3. Fila de áudio com crossfade suave entre chunks

**Ganho percebido:** Latência aparente cai de ~5s para ~1.5s.

---

### 3. Guard Educacional/Científico para `_SYS_CALC`
**Onde:** `main.py` — `_detectar_comando_sistema`, regex `_SYS_CALC`  
**Problema:** O mesmo que ocorreu com `_SYS_VOLUME_SET` e texto de química — a regex de calculadora pode disparar em expressões matemáticas de conteúdo colado (ex: `"A = p + n"`, `"E = mc²"`).  
**Solução:** Reutilizar o mesmo `_is_science` / `_is_educational` guard já implementado para volume, aplicando-o antes do check de calculadora. Considerar extrair para método auxiliar `_is_educational_context(tl)` reutilizável.

---

### 4. Logger Central
**Onde:** `main.py` — múltiplos `except Exception: pass` silenciosos  
**Problema:** Erros engolidos silenciosamente dificultam muito o diagnóstico de problemas em produção. O arquivo `@AutomationLog.txt` existe mas nem todos os erros chegam lá.  
**Solução:** Um módulo `logger_ctrl.py` simples com níveis INFO/WARN/ERROR que:
- Escreve em `@AutomationLog.txt` com timestamp
- Opcionalmente exibe no chat como mensagem `[SISTEMA]` para erros graves
- Substitui os `pass` nos `except` por `_log.warn(...)` no mínimo

---

### 5. Hot Reload de `config.py`
**Onde:** `config.py` + `main.py` inicialização  
**Problema:** Qualquer mudança de voz, modelo, API key ou cidade exige reiniciar o app completamente.  
**Solução:** Thread de watchdog monitorando o `mtime` de `config.py` a cada 10s. Se detectar mudança, recarregar via `importlib.reload(config)` e reaplicar:
- Voz TTS (Edge + Kokoro)
- Modelo LM Studio / Groq
- `CIDADE_PADRAO` para clima/briefing

---

## Funcionalidades Novas

### 6. Controle de Arquivos por Voz (`file_ctrl.py`)
**Módulo novo:** `comandos/file_ctrl.py`  
**Dependências:** `pathlib`, `shutil` (stdlib — sem instalações extras)  
**Comandos planejados:**
- *"cria uma pasta chamada Projetos na área de trabalho"*
- *"move o PDF mais recente para a área de trabalho"*
- *"procura arquivos .py modificados hoje"*
- *"qual é o tamanho da pasta Downloads?"*
- *"lista os arquivos de [caminho]"*
- *"renomeia [arquivo] para [novo nome]"*

**Regexes a adicionar em `main.py`:**
```
_SYS_FILE_CRIAR   → criar pasta / criar arquivo
_SYS_FILE_MOVER   → mover / copiar arquivo
_SYS_FILE_BUSCAR  → procurar / encontrar arquivos
_SYS_FILE_INFO    → tamanho / data / propriedades
_SYS_FILE_LISTAR  → listar arquivos / ver conteúdo de pasta
```

---

### 7. Fetch de URL + Resumo pela IA (`url_fetch_ctrl.py`)
**Módulo novo:** `comandos/url_fetch_ctrl.py`  
**Dependências:** `httpx` ou `requests` (já no projeto indiretamente), `BeautifulSoup4`  
**Comando:** *"abra essa URL e me diga o que tem nela"* / *"resuma o conteúdo de [url]"*  
**Fluxo:**
1. Regex detecta URL no texto ou comando explícito de fetch
2. Faz GET com timeout, extrai texto limpo via BeautifulSoup
3. Passa para `_lm_gerar_stream` com prompt de resumo
4. Complementa o `pdf_ctrl` para conteúdo web

**Segurança:** Bloquear IPs privados (127.x, 192.168.x, 10.x) para evitar SSRF.

---

### 8. Ditado → Colar na Janela Ativa
**Onde:** `main.py` — método `_processar_audio_ditado`  
**Problema:** No modo ditado, o texto transcrito vai apenas para o chat do JARVIS. O usuário precisa copiar manualmente.  
**Solução:** Após transcrição, usar `pyperclip.copy(texto)` + `pynput` para enviar `Ctrl+V` na janela que estava em foco antes do hotkey de ditado ser pressionado.  
**Cuidado:** Salvar o handle da janela ativa *antes* de qualquer delay de processamento, e só colar se o usuário confirmar (ou adicionar flag `auto_colar` no config).

---

### 9. Contexto Multi-Turno para Voz
**Onde:** `main.py` — `_processar_texto` / `_chamar_chat`  
**Problema:** Cada comando de voz é processado isoladamente. Se o usuário disser *"e aquela planilha de antes?"* ou *"continue o que eu disse"*, a IA não tem contexto.  
**Solução:** Manter `self._voz_ctx: list[dict]` com o buffer das últimas N trocas de voz (padrão: 5). Injetar esse buffer no início do prompt quando `origem == "voz"`.  
**Controle de tamanho:** Manter a janela deslizante por tokens (ex: ≤ 800 tokens histório) para não explodir o contexto do LM Studio.

---

### 10. OCR em Região Selecionada
**Onde:** `comandos/ocr_ctrl.py` + frontend `ui/index.html`  
**Problema:** `ler_tela()` só lê a tela inteira. Às vezes o usuário quer apenas um trecho.  
**Solução A (por coordenadas):** *"leia o texto na região superior direita"* — mapeamento verbal de regiões (canto, terço superior, metade esquerda etc.)  
**Solução B (overlay visual):** Janela transparente sobre a tela onde o usuário arrasta para selecionar a região. Retorna a `bbox` para `ler_regiao()` (que já existe em `ocr_ctrl.py`).

---

### 11. Detecção Automática de Idioma + Resposta no Idioma Certo
**Onde:** `main.py` — `_processar_texto` + TTS  
**Problema:** Se o usuário falar em inglês, JARVIS responde em português com voz PT-BR, quebrando a imersão.  
**Solução:**
1. Detectar idioma com `langdetect` (leve, offline) ou heurística de stopwords
2. Se `lang == "en"` → usar `VOZ_EDGE_EN` e incluir instrução no system prompt para responder em inglês
3. Manter estado de idioma por sessão para não re-detectar a cada mensagem

---

### 12. Alertas Automáticos de Recursos do Sistema
**Onde:** `comandos/condicional_ctrl.py` (já tem a base de regras)  
**Funcionalidade nova:** Triggers automáticos configuráveis por voz:
- *"me avisa quando a CPU ultrapassar 90%"*
- *"alerta se a memória RAM ficar abaixo de 2 GB livres"*
- *"notifica quando o disco C estiver acima de 90% cheio"*

**Implementação:** Adicionar tipo `"recurso_sistema"` ao `condicional_ctrl`, com polling via `psutil` (já importado em `main.py`) a cada 30s.

---

### 13. Exportar Conversa
**Onde:** `main.py` + `comandos/pdf_ctrl.py`  
**Comando:** *"exporta essa conversa"* / *"salva o histórico como PDF"* / *"exporta o chat de hoje"*  
**Formatos:**
- `.md` — simples, rápido, usa só stdlib
- `.pdf` — via `pdf_ctrl` já existente (renderizar histórico como documento)
- `.txt` — fallback universal

**Fonte de dados:** `historico.jsonl` já existe no projeto — só precisa de um formatador.

---

### 14. Atalhos de Teclado Configuráveis
**Onde:** `main.py` — seção de hotkeys com `pynput` (já no projeto)  
**Problema:** Apenas PTT está configurado como hotkey. Ações comuns exigem sempre voz ou digitação.  
**Solução:** Mapa de atalhos configurável em `config.py`:
```python
HOTKEYS = {
    "ctrl+shift+s": "screenshot_analise",  # print + análise pela IA
    "ctrl+shift+c": "clipboard_resumir",   # resumir clipboard
    "ctrl+shift+t": "traducao_clipboard",  # traduzir clipboard
    "ctrl+shift+h": "hist_hoje",           # ver histórico de hoje
}
```
Registrar via `pynput.keyboard.GlobalHotKeys` na inicialização. Usuário pode editar `HOTKEYS` em `config.py` e o hot reload (melhoria #5) aplica sem reiniciar.

---

## Ordem de Prioridade Sugerida

| Prioridade | # | Justificativa |
|:---:|---|---|
| 🔴 Alta | 1 | Afeta toda resposta falada — ganho imediato e perceptível |
| 🔴 Alta | 2 | Muda a percepção de velocidade do assistente |
| 🟠 Média | 9 | Conversas de voz se tornam muito mais naturais |
| 🟠 Média | 6 | Muito útil no dia a dia, sem deps externas |
| 🟡 Baixa | 3 | Segurança contra false positives (mesmo padrão do volume) |
| 🟡 Baixa | 8 | Qualidade de vida para modo ditado |
| 🟢 Futura | 14 | Conveniência, `pynput` já presente |
| 🟢 Futura | 13 | Utilidade pontual |
| 🟢 Futura | 11 | Nicho (maioria dos comandos é PT-BR) |
| 🟢 Futura | 12 | Power user feature |
| 🟢 Futura | 7 | Depende de `httpx`/`beautifulsoup4` |
| 🟢 Futura | 10 | Depende de UI overlay |
| ⚪ Técnica | 4 | Dívida técnica — não muda comportamento visível |
| ⚪ Técnica | 5 | Conveniência de desenvolvimento |

---

*Próximo foco: melhorias no classificador de intenções (ver plano separado).*
