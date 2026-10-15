# tools/

Pipeline de release reproduzível.

## Uso

```powershell
# Validar segredos (rápido — não modifica nada)
.venv\Scripts\python.exe tools\make_release.py 2.0.1 --scan-only

# Release completo (scan + build + installer + payload + checksum + tag)
.venv\Scripts\python.exe tools\make_release.py 2.0.1

# Skip flags úteis durante desenvolvimento
.venv\Scripts\python.exe tools\make_release.py 2.0.1 --skip-build --skip-installer
```

## Etapas

1. **Scan de segredos**: regex contra padrões conhecidos (OpenAI, Groq, Gemini,
   GitHub PAT, AWS, ElevenLabs, Discord, JWT, RSA, hardcoded passwords).
   Aborta se qualquer match for encontrado em arquivos não-gitignorados.
2. **Bump VERSION**: atualiza o arquivo `VERSION` na raiz.
3. **PyInstaller**: gera `dist/JARVIS/JARVIS.exe` usando o `.venv`.
4. **Inno Setup**: gera `installer/output/JARVIS_Setup_v{X.Y.Z}.exe`.
5. **Payload**: `installer/output/update_payload_v{X.Y.Z}.zip` (apenas `.py`).
6. **SHA256SUMS**: checksums dos assets.
7. **Release notes**: template em markdown para editar manualmente.
8. **git tag**: tag local `vX.Y.Z` (NÃO faz push automaticamente).

## Pós-script — publicação manual

```powershell
git push origin v2.0.1

gh release create v2.0.1 `
    installer\output\JARVIS_Setup_v2.0.1.exe `
    installer\output\update_payload_v2.0.1.zip `
    installer\output\SHA256SUMS.txt `
    --notes-file installer\output\release_notes_v2.0.1.md `
    --repo SodreDev/jarvis-releases
```

Para repo privado, garanta que `gh auth login` foi feito com escopo `repo`
(o mesmo PAT que o updater usa).

## Falso-positivos no scan

Se o scanner detectar literais que NÃO são segredos (ex: documentação,
templates), adicione em `ALLOWLIST_LITERALS` no topo de `make_release.py`.
