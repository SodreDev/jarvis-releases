# Updater do JARVIS

Sistema de atualização via **GitHub Releases**. Funciona com repositório público
ou privado (basta um PAT com escopo `repo`).

## Como funciona

1. `version.py` lê o arquivo `VERSION` na raiz do projeto.
2. `updater/check_update.py` consulta `GET /repos/{owner}/{repo}/releases/latest`.
3. Compara `tag_name` (sem o `v`) com a versão local via tupla numérica.
4. Se houver update, baixa o asset `update_payload_v{X.Y.Z}.zip` OU o
   instalador `JARVIS_Setup_v{X.Y.Z}.exe`.
5. Extrai o payload sobre a raiz do projeto, **preservando** `credentials/`,
   `data/`, `temp/`, `logs/`, `build/`, `dist/`, `.venv/`, `.git/`,
   `__pycache__/`, `memories/`.

## Configuração

### 1. Apontar para o repositório de releases

Edite `credentials/jarvis_prefs.json`:

```json
{
  "updater": {
    "repo":  "seuusuario/jarvis-releases",
    "token": "ghp_xxxxxxxxxxxxxxxxxxxx"
  }
}
```

OU defina variáveis de ambiente:

```
JARVIS_UPDATE_REPO=seuusuario/jarvis-releases
JARVIS_UPDATE_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

OU adicione em `credentials/.env`:

```
JARVIS_UPDATE_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
JARVIS_UPDATE_REPO=seuusuario/jarvis-releases
```

### 2. Gerar PAT para repo privado

GitHub → Settings → Developer settings → Personal access tokens →
**Fine-grained tokens** → "Generate new token":

- **Repository access**: Only select repositories → `jarvis-releases`
- **Permissions**: `Contents: Read-only`
- Expiration: 1 ano (renove a cada ciclo)

Cole o token em `credentials/.env` (gitignored).

## Comandos

```powershell
# Checar (sem baixar)
.venv\Scripts\python.exe -m updater.check_update --check

# Checar com JSON
.venv\Scripts\python.exe -m updater.check_update --check --json

# Aplicar payload (extrai .py sobre o projeto)
.venv\Scripts\python.exe -m updater.check_update --apply

# Baixar o setup.exe (modo instalador interativo)
.venv\Scripts\python.exe -m updater.check_update --installer
```

## Formato esperado da release

Para o updater funcionar sem erros, cada release no GitHub deve ter:

| Campo            | Valor                                           |
|------------------|-------------------------------------------------|
| **Tag**          | `vX.Y.Z` (semver, ex: `v2.0.1`)                |
| **Title**        | `JARVIS X.Y.Z`                                  |
| **Description**  | Changelog em markdown                           |
| **Asset 1**      | `update_payload_vX.Y.Z.zip` (somente .py)       |
| **Asset 2** (opc)| `JARVIS_Setup_vX.Y.Z.exe`                       |
| **Asset 3** (opc)| `SHA256SUMS.txt`                                |

Use `tools/make_release.py` para gerar os assets automaticamente (ver
`tools/README.md`).

## Segurança

- Caminhos com `..` ou absolutos são **bloqueados** durante a extração.
- Pastas protegidas (`PROTECTED` em `check_update.py`) nunca são
  sobrescritas — seus dados pessoais (credentials, histórico, alarmes,
  contatos, prefs) ficam intactos.
- O PAT nunca é commitado: vive em `credentials/.env` (ignorado pelo git).
