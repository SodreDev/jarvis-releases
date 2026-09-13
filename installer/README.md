# Installer — Inno Setup

Empacota o JARVIS num `.exe` instalável que detecta o caminho automaticamente.

## Pré-requisitos

- **Inno Setup 6+**: https://jrsoftware.org/isdl.php
- Após instalar, garanta que `iscc.exe` está no PATH (ou use o caminho completo:
  `"C:\Program Files (x86)\Inno Setup 6\iscc.exe"`).

## Build manual

1. Garanta que `dist\JARVIS\JARVIS.exe` existe (rode o PyInstaller primeiro):

   ```powershell
   .venv\Scripts\python.exe -m PyInstaller JARVIS.spec --noconfirm
   ```

2. Compile o instalador:

   ```powershell
   iscc installer\jarvis.iss
   ```

   ou com versão custom:

   ```powershell
   iscc /DAppVer=2.0.1 installer\jarvis.iss
   ```

3. Saída: `installer\output\JARVIS_Setup_v{X.Y.Z}.exe`

## Estrutura instalada (`{app}` = pasta escolhida pelo usuário)

```
{app}\
  ├── main.py                ← live-source (launcher.py procura aqui)
  ├── config.py
  ├── launcher.py
  ├── version.py
  ├── VERSION                ← lido pelo updater
  ├── requirements.txt
  ├── jarvis_icon.ico
  ├── dist\
  │   └── JARVIS\
  │       ├── JARVIS.exe     ← atalho do menu Iniciar aponta aqui
  │       └── _internal\
  ├── comandos\
  ├── core\
  ├── classifiers\
  ├── documents\
  ├── dashboard\
  ├── updater\
  ├── jarvis\
  ├── VozIa\
  ├── gesture_interface\
  ├── entity\
  ├── security\
  ├── ui\
  ├── config\
  └── credentials\
      ├── .env.example       ← template (NUNCA o .env real)
      └── README.md
```

## Auto-detecção de caminho

O JARVIS **nunca** depende de uma pasta fixa:

- `version.py` → lê `VERSION` ao lado de `sys.executable` ou `__file__`.
- `config.py` → `_data_base()` retorna o dir do `.exe` ou do `.py`.
- `launcher.py` → procura `main.py` dois níveis acima de `sys.executable`
  (padrão `{app}\dist\JARVIS\JARVIS.exe` → live-source em `{app}\main.py`).
- `updater\check_update.py` → mesma lógica para encontrar `credentials\` e
  aplicar o payload.

Você pode instalar em `C:\Program Files\JARVIS`, `D:\Apps\JARVIS`, ou qualquer
outra pasta — funciona em todos.

## O que NÃO é incluído no installer

Por segurança / privacidade, estes itens **nunca** vão no `.exe`:

- `credentials\.env` (chaves de API reais)
- `credentials\*.json` (sessões, tokens OAuth)
- `data\` (perfis Chromium, contatos, histórico)
- `temp\`, `logs\`, `build\` (artefatos)
- `.venv\`, `.git\`, `__pycache__\`
- `*.vcf` (contatos)
- `historico.jsonl`, `notif_history.jsonl`, `vision_cache.jsonl`

## Atualização incremental (sem reinstalar)

Para releases de patch (mudanças só em `.py`), use o **payload** do updater:

```powershell
.venv\Scripts\python.exe -m updater.check_update --apply
```

Ele baixa apenas os arquivos alterados do GitHub Release e aplica sobre
`{app}\`, preservando `credentials\`, `data\`, `temp\`. Ver `updater\README.md`.
