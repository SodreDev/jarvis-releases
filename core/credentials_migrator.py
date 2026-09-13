# core/credentials_migrator.py
# Migra arquivos legados da raiz do projeto para a pasta credentials/.
# Roda automaticamente no startup do main.py, ANTES de importar config.
# -*- coding: utf-8 -*-
"""
Move credenciais e dados pessoais para uma pasta única `credentials/` para que
o usuário possa fazer commits do projeto no git sem expor segredos.

Funciona tanto em dev (.py) quanto em frozen (.exe). A pasta é colocada ao
lado do executável (ou ao lado de main.py em dev), seguindo o mesmo critério
de `main._data()`.

Estratégia:
  • Se o arquivo legado existe e o destino NÃO existe → move (shutil.move)
  • Se ambos existem → mantém o destino, renomeia o legado para .bak
  • Se nenhum existe → ignora
  • Erros são capturados silenciosamente para nunca derrubar o startup
"""
import os
import sys
import shutil
from typing import List, Tuple


def _base_dir() -> str:
    """Mesma lógica de main._data(): dir do .exe (frozen) ou dir de main.py."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Sobe um nível porque este arquivo está em core/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Pares (legado_relativo_à_raiz, destino_relativo_a_credentials)
_MIGRATIONS: List[Tuple[str, str]] = [
    (".env",                          ".env"),
    ("contatos.json",                 "contatos.json"),
    ("condicionais.json",             "condicionais.json"),
    ("alarmes.json",                  "alarmes.json"),
    ("jarvis_prefs.json",             "jarvis_prefs.json"),
    ("jarvis_modo.json",              "jarvis_modo.json"),
    ("historico.jsonl",               "historico.jsonl"),
    ("notif_history.jsonl",           "notif_history.jsonl"),
    ("vision_cache.jsonl",            "vision_cache.jsonl"),
    (os.path.join("temp", "instagram_session.json"), "instagram_session.json"),
    ("gmail_credentials.json",        "gmail_credentials.json"),
    ("gmail_token.json",              "gmail_token.json"),
]


def migrate_to_credentials_dir() -> dict:
    """Executa a migração. Retorna dict com listas de movidos/ignorados/erros."""
    base = _base_dir()
    creds_dir = os.path.join(base, "credentials")
    try:
        os.makedirs(creds_dir, exist_ok=True)
    except Exception as e:
        return {"movidos": [], "ignorados": [], "erros": [f"mkdir credentials/: {e}"]}

    movidos:   List[str] = []
    ignorados: List[str] = []
    erros:     List[str] = []

    # ── Frozen: copia templates bundled (_MEIPASS/credentials/) para credentials/
    #     se ainda não existirem. Permite que o .exe sozinho funcione para
    #     um usuário novo (ele vê o .env.example e o README).
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), "credentials")
        if os.path.isdir(bundled):
            for nome in (".env.example", "README.md"):
                src_b = os.path.join(bundled, nome)
                dst_b = os.path.join(creds_dir, nome)
                if os.path.exists(src_b) and not os.path.exists(dst_b):
                    try:
                        shutil.copy2(src_b, dst_b)
                        movidos.append(f"template bundled → credentials/{nome}")
                    except Exception as e:
                        erros.append(f"copy template {nome}: {e}")

    for legado_rel, destino_rel in _MIGRATIONS:
        src = os.path.join(base, legado_rel)
        dst = os.path.join(creds_dir, destino_rel)

        if not os.path.exists(src):
            continue   # nada a fazer

        try:
            if os.path.exists(dst):
                # destino já existe → não sobrescreve, renomeia legado
                bak = src + ".bak"
                # Se .bak também existe, anexa timestamp
                if os.path.exists(bak):
                    import time
                    bak = f"{src}.bak.{int(time.time())}"
                os.replace(src, bak)
                ignorados.append(f"{legado_rel} → {os.path.basename(bak)} (destino já existia)")
            else:
                shutil.move(src, dst)
                movidos.append(f"{legado_rel} → credentials/{destino_rel}")
        except Exception as e:
            erros.append(f"{legado_rel}: {e}")

    return {"movidos": movidos, "ignorados": ignorados, "erros": erros}


if __name__ == "__main__":
    # Permite rodar manualmente: python -m core.credentials_migrator
    resultado = migrate_to_credentials_dir()
    print(f"Movidos:   {len(resultado['movidos'])}")
    for m in resultado["movidos"]:
        print(f"  ✓ {m}")
    print(f"Ignorados: {len(resultado['ignorados'])}")
    for i in resultado["ignorados"]:
        print(f"  ~ {i}")
    print(f"Erros:     {len(resultado['erros'])}")
    for e in resultado["erros"]:
        print(f"  ✗ {e}")
