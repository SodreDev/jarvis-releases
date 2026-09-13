# Plano 03 — Cofre de Credenciais

## Estado Atual

- Pasta `credentials/` existe mas conteúdo não estruturado.
- `config.py` mistura: API keys, prompts, toggles, paths, cores.
- Segredos passados via `os.environ` em alguns lugares, hardcoded em outros.
- Sessão IG salva em `temp/instagram_session.json` (sem cifra).
- Tokens Spotify em `.spotify_cache` (formato do `spotipy`, sem cifra extra).

## Problema

- Distribuir o JARVIS hoje vazaria credenciais pessoais se o usuário esquecer de limpar.
- Sem trilha de uso: nunca sei quando um token foi acessado.
- Sem segregação por perfil (ver plano 02).

## Plano

### Estrutura

```
credentials/
├── vault.enc           ← arquivo cifrado (AES-GCM) opcional
├── vault.key.hint      ← lembrete de senha (NÃO a senha)
├── profiles/
│   ├── jarvis/
│   │   ├── discord.json
│   │   ├── whatsapp.json
│   │   └── …
│   └── user/
│       └── …
└── shared/
    ├── groq.json
    ├── lmstudio.json
    └── …
```

### API — `credentials/vault.py`

```python
class Vault:
    def __init__(self, master_password: str | None = None): ...
    def get(self, key: str, profile: str = "shared") -> str | dict | None: ...
    def set(self, key: str, value, profile: str = "shared") -> None: ...
    def list_keys(self, profile: str = "shared") -> list[str]: ...
    def is_locked(self) -> bool: ...
    def audit_log(self) -> list[AccessEvent]: ...
```

### Camadas (do mais simples ao mais robusto, todas opt-in)

1. **Plain JSON** (default p/ instalador inicial) — arquivos com `0600` perm. OK para uso pessoal local.
2. **Master password** (toggle `VAULT_ENCRYPTED=True`) — cifra com AES-GCM derivado de PBKDF2 sobre senha mestra.
3. **OS keyring** (toggle `VAULT_OS_KEYRING=True`) — usa `keyring` lib (Windows Credential Manager, libsecret, macOS Keychain).
4. **Vault externo** (toggle `VAULT_BACKEND=hashicorp|bitwarden|…`) — futuro, não MVP.

### Migração

- Script `tools/migrate_credentials.py` lê valores de `config.py` + `temp/instagram_session.json` + `.spotify_cache` e popula `credentials/profiles/user/`.
- `config.py` passa a importar do vault para retrocompatibilidade dos lookups antigos.

### Logging seguro

- Acesso a credencial → log em `logs/credentials_access.jsonl` (timestamp, key, profile, accessor module).
- Logs NUNCA contêm o valor.

## Decisões pendentes

1. **Lib cripto**: `cryptography` (padrão) vs `pynacl`. Recomendação: `cryptography` — já está em deps indiretos.
2. **Senha mestra na inicialização**: pedir interativo, env var, ou arquivo? Recomendação: env `JARVIS_VAULT_PASS` opcional + prompt interativo na primeira execução.
3. **Sessões grandes (IG, WA Web cookie jars)**: cifrar inteiras (JSON) ou só keys? Recomendação: cifrar inteiras, performance OK pois carrega 1x na boot.

## Riscos

- Se usuário perder senha mestra → perde acesso. Plano: `vault.key.hint` opcional + procedimento documentado de re-login em cada serviço.
- Lentidão de PBKDF2 na boot — mitigar com 100k iterações (~100ms aceitável).

## Referências de código

- [config.py](../../config.py) — fonte atual de segredos
- [credentials/](../../credentials/) — pasta a estruturar
- [.spotify_cache](../../.spotify_cache) — cache `spotipy`

## Histórico

- 2026-05-25 — Plano criado.
