# Plano 09 — Segurança & Permissões

## Estado Atual

- `security/sanitizer.py` e `security/permissions.py` existem como esqueletos.
- Tools são chamadas sem verificação formal de permissão.
- Confirmação para ações destrutivas é ad-hoc (algumas têm, outras não).

## Problema

- Plugins futuros podem fazer estragos se não houver gating.
- LLM pode "alucinar" um `controle_sistema(acao='desligar')` sem confirmação.
- Sem auditoria do que cada tool fez quando.

## Plano

### Modelo de permissões

```python
class Permission(Enum):
    READ_FS         = "fs:read"
    WRITE_FS        = "fs:write"
    EXEC_PROCESS    = "process:exec"
    NETWORK         = "net"
    INPUT_DEVICES   = "input:devices"    # pyautogui
    AUDIO_IO        = "audio"
    CAMERA          = "camera"
    SCREEN_CAPTURE  = "screen:capture"
    SEND_MESSAGE    = "msg:send"
    READ_MESSAGE    = "msg:read"
    VAULT_READ      = "vault:read"
    VAULT_WRITE     = "vault:write"
    DESTRUCTIVE     = "destructive"      # delete, shutdown
```

Cada `@register` declara `permissions=[…]`.

### Engine

- Boot: carrega `data/permissions_grants.json` — quais permissões cada conector tem.
- Ao chamar tool: engine verifica grants. Se `DESTRUCTIVE` → pede confirmação (TTS + UI).
- Logs em `logs/permissions_audit.jsonl`.

### Sanitização

- Input do usuário → `security/sanitizer.py` antes de:
  - Comandos shell (`subprocess`).
  - Paths (resolver `..`, restringir a whitelisted dirs).
  - URLs (validar scheme, host).
  - SQL (parameterizar — proibir concat).
- Listas brancas por contexto (ex: `safe_apps = ["spotify", "chrome", ...]`).

### Confirmação de ações destrutivas

- Quando intent classifica como DESTRUCTIVE → JARVIS verbaliza confirmação ("Tem certeza que quer desligar o PC, Senhor?") e aguarda "sim".
- Toggle `CONFIRM_DESTRUCTIVE=True` default ON.
- Confirmações idempotentes (mesmo comando 2x em janela curta = sim implícito).

### Diretórios restritos

- Whitelist em config:
  ```python
  ALLOWED_DIRS = [
      Path.home() / "Downloads",
      Path.home() / "Documents",
      Path.home() / "Desktop",
      JARVIS_DATA_DIR,
  ]
  ```
- Operações de FS fora disso → bloqueadas + log de tentativa.

### Sandbox de plugins (futuro)

- Plugins de terceiros rodam em subprocess com `os.setresuid`/`AppContainer` (Win) — recursos restritos.
- MVP: confiar no manifest declarado; auditar pós-execução.

### Sem root

- JARVIS nunca pede UAC/sudo no caminho principal.
- Operações que precisam: tool isolada com confirmação explícita.

## Decisões pendentes

1. **TUF/signing de plugins**: assinatura digital? Recomendação: postergar — começa com hash check.
2. **2FA para ações críticas (envio msg em massa, deletar arquivos)**: confirmar por voz + clique. Recomendação: sim, configurável.
3. **Mode "kiosk"** (uso público): perfil que desliga todas as features destrutivas. Recomendação: criar `SECURITY_PROFILE=normal|paranoid|kiosk`.

## Riscos

- Engine de permissão muito agressivo → frustração. UX importa: confirmações poucas, claras.
- LLM pode tentar contornar pedindo "ignore confirmação" — engine não obedece o LLM, só o usuário humano via voz/clique.

## Referências de código

- [security/sanitizer.py](../../security/sanitizer.py)
- [security/permissions.py](../../security/permissions.py)
- [comandos/tool_registry.py](../../comandos/tool_registry.py)

## Histórico

- 2026-05-25 — Plano criado.
