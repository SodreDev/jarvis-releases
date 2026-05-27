# JARVIS — Roadmap Arquitetural

> **Status**: Planejamento. Nenhuma execução até instrução explícita do usuário.
>
> **Regra de ouro do projeto**: a maior parte do que está aqui já EXISTE em alguma forma. Este roadmap evolui o que já temos, **sem remover features funcionais nem o `pyautogui`**.

## Princípios mestres (`PRINCIPIOS.md`)

1. Modularidade > velocidade. Toda nova feature passa por um conector/serviço, não vira hack no `main.py`.
2. **Default OFF**: o JARVIS vai virar instalador para terceiros. Toda feature opcional sai com toggle desligado em `config.py`.
3. **Não invadir o uso pessoal do PC**: automações com janela própria, perfil próprio, browser próprio. `pyautogui` é fallback, não primeira linha.
4. **Persistência**: nada deve depender de estado em RAM perdido a cada restart. Sessões, cookies, alarmes, notas, ferramentas conectadas → disco.
5. **Isolamento de identidade**: o JARVIS pode ter contas próprias (Discord/IG/WA) **e** opcionalmente operar nas contas do usuário. São perfis distintos.
6. **Segurança em camadas**: permissões mínimas, sanitização, logging, confirmação para ações destrutivas.
7. **Compatibilidade**: hoje Windows-first; arquitetura deve ser POSIX-amigável. Sem `WindowsApps`-only no caminho crítico.

---

## Mapa dos planos

| # | Tema | Estado atual (sumário) | Prioridade |
|---|------|------------------------|------------|
| [01](01-arquitetura-modular.md) | Arquitetura modular | `main.py` ~10380 linhas, módulos parcialmente separados em `comandos/`, `core/`, `classifiers/` | 🔴 Alta — refatoração contínua |
| [02](02-ambientes-mensageria-duplos.md) | Mensageria com 2 perfis (JARVIS vs Usuário) | WA via `pywhatkit`, IG via `instagrapi` — usa contas pessoais | 🔴 Alta |
| [03](03-cofre-credenciais.md) | Cofre de credenciais | `config.py` + `credentials/` parcial, sem cofre estruturado | 🟡 Média |
| [04](04-browser-automation.md) | Browser automation com perfil dedicado | Playwright já listado, mas pouco usado; muito `pyautogui` ainda | 🔴 Alta |
| [05](05-monitores-janelas.md) | Monitores e janelas multi-tela | `janela_ctrl.py` ok para janela ativa; multi-monitor não-mapeado | 🟡 Média |
| [06](06-painel-stark.md) | Painel web "Stark-classic" com cards/embeds por tema | `ui/` html simples, sem painel temático | 🟡 Média |
| [07](07-memoria-persistencia.md) | Memória — manter simples (SQLite opcional) | JSON files + JSONL — funciona; adicionar SQLite atrás de toggle | 🟢 Baixa |
| [08](08-mcp-conectores-plugins.md) | MCP + conectores plugáveis | Sem MCP. Tools registradas em `tool_registry.py` | 🟢 Baixa (futuro) |
| [09](09-seguranca-permissoes.md) | Segurança e permissões | `security/sanitizer.py`, `security/permissions.py` esqueletos | 🟡 Média |
| [10](10-geracao-documentos.md) | Geração visual: PDF/DOCX/PPTX/XLSX | Nada — feature nova | 🟡 Média |
| [11](11-leitura-interpretacao-docs.md) | Leitura/interpretação de documentos | `pdf_ctrl.py` extrai texto; sem layout/imagens | 🟡 Média |
| [12](12-config-instalador-toggles.md) | Config padrão para instalador | `config.py` mistura segredos + flags | 🔴 Alta (bloqueante p/ distribuir) |

---

## Como usar este roadmap

- Antes de mexer em qualquer área, **abra o `.md` correspondente** e cheque "Estado Atual" e "Decisões pendentes".
- Ao concluir uma decisão ou marco, **atualize a seção "Histórico"** do plano específico — não delete contexto.
- Decisões que afetam múltiplos planos vão em `PRINCIPIOS.md`.
- Riscos e dependências cruzadas estão na seção de cada plano.

## Regras de execução (quando sair do plano)

- Toda mudança em `main.py` precisa ser cirúrgica (≤ 2 funções por commit) até a refatoração modular do plano 01 reduzir o arquivo.
- Toggles novos em `config.py` SEMPRE `False` por padrão.
- Nada de remover `pyautogui` — só rebaixar para fallback documentado.
- Nada de quebrar `comandos/*_ctrl.py` existente.
