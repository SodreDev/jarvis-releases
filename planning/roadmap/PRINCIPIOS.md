# Princípios de Arquitetura — Imutáveis

> Estes princípios valem para TODO trabalho no JARVIS. Releia antes de mudanças grandes.

## 0. Mensageria SEMPRE via Chromium humanizado — NUNCA por API oficial

- **PROIBIDO**: `instagrapi`, `discord.py` (modo bot), `python-telegram-bot`, `pywhatkit` (envia via WhatsApp Web mas usa pyautogui), Gmail API, etc.
- **OBRIGATÓRIO**: todo envio/leitura de mensagem em qualquer plataforma (WhatsApp, Instagram, Discord, Telegram, Gmail, etc.) acontece dentro do **Chromium controlado por Playwright**, com:
  - Perfil/cookies persistentes por (perfil, plataforma) em `data/browser_profiles/`.
  - Janela em posição off-screen (`-32000,0`) para **não roubar foco** do teclado/mouse do usuário.
  - Operações via API do Playwright (`page.click`, `page.fill`, `keyboard`) — **JAMAIS** via mouse/teclado do SO (pyautogui é fallback documentado, não default).
  - Comportamento humano: delays gaussianos, jitter de clique, pausas em pontuação (ver `jarvis/browser/human.py`).
  - Stealth básico (`navigator.webdriver=undefined`, etc.) — `jarvis/browser/launcher.py`.
- **Por quê**: o objetivo é zero risco de ban por automação detectada e zero interferência no input do usuário.

## 1. Não-interferência no uso pessoal

- Automação NUNCA controla mouse/teclado globais salvo fallback explicitamente marcado.
- Toda interação web do JARVIS roda em **browser próprio com perfil dedicado** (Playwright contexts persistentes).
- `pyautogui` permanece, mas só como último recurso (documentado em cada call site).

## 2. Default OFF

- Qualquer feature que requer credenciais, internet pesada, ou uso intrusivo nasce com toggle desligado em `config.py`.
- Pessoas que instalarem o JARVIS terão experiência mínima funcional sem configurar nada.
- Feature crítica de uma persona (ex: voz) **pode** vir ligada, com fallback offline.

## 3. Identidades separadas

- **Perfil JARVIS**: contas próprias do bot (Discord/IG/WA dedicadas) — opera 100% sem interferir no usuário.
- **Perfil Usuário** (opt-in): JARVIS responde em nome do usuário, em sessão isolada (cookie store separado), com confirmação para envio.
- Nunca misturar credenciais entre perfis.

## 4. Modularidade

- Tudo que vira tool → registrado em `comandos/tool_registry.py`.
- Tudo que vira conector externo → módulo isolado em `connectors/` (a criar) com interface comum.
- `main.py` é orquestrador, não implementador.

## 5. Persistência consciente

- Estado de RAM que precise sobreviver a restart → arquivo. Decisão entre JSON/JSONL/SQLite é baseada em escala (ver plano 07).
- Logs de ação importantes (envio de msg, comandos destrutivos, gasto de API) → `historico.jsonl`.
- Histórico de chat para o LLM **limitado** (já caímos para 8 turnos persistidos — evitar regredir).

## 6. Segurança em camadas

- Permissões: cada tool declara permissões necessárias; engine valida.
- Sanitização: nunca passar input do usuário direto para shell/SQL/URL sem `security/sanitizer.py`.
- Confirmação: ações destrutivas (deletar arquivo, send msg, mexer em config global) pedem confirmação.

## 7. Persona com opinião

- JARVIS é PERSONA — opina, arrisca palpite, discorda. **Nunca** se esconde atrás de "como IA…".
- `_scrub_disclaimer` aplicado em 5 sites; toda nova rota de LLM deve passar pelo mesmo filtro.
- Tom: "quer que eu cuide disso, Senhor?" — não "quer executar uma função?".

## 8. Compatibilidade futura

- Caminhos: `pathlib.Path`, nunca string `C:\…` hard-coded em código novo.
- Comandos de SO: detectar `platform.system()` e ramificar.
- Sem WindowsApps dependency no caminho crítico.

## 9. Observabilidade

- Toda chamada de tool registra: nome, args (sem secrets), duração, sucesso/erro.
- Logs em `logs/jarvis.log` com rotação.
- Dashboard de status (plano 06, secundário) lê desses logs.

## 10. Reversibilidade

- Toda migração de schema (JSON → SQLite, etc.) deixa o JSON antigo intacto durante N versões.
- Toggles novos têm migration path documentado.
