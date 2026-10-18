"""Contrato estático da extensão: não inicia navegador, host nativo nem rede."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
EXTENSAO = RAIZ / "extensao"


def _json(nome: str) -> dict[str, object]:
    return json.loads((EXTENSAO / nome).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _id_chromium(chave: str) -> str:
    digest = hashlib.sha256(base64.b64decode(chave)).hexdigest()[:32]
    return digest.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def test_manifesto_mv3_pina_ids_e_so_pede_paginas_http() -> None:
    manifesto = _json("manifest.json")
    permissoes = manifesto["permissions"]
    hosts = manifesto["host_permissions"]

    assert manifesto["manifest_version"] == 3
    assert isinstance(permissoes, list)
    assert isinstance(hosts, list)
    assert set(permissoes) == {"activeTab", "tabs", "nativeMessaging"}
    assert hosts == ["http://*/*", "https://*/*"]
    assert manifesto["browser_specific_settings"] == {
        "gecko": {"id": "jarvis-browser@granafacil.local", "strict_min_version": "121.0"}
    }
    assert _id_chromium(str(manifesto["key"])) == "eainnehpangdlhmjenljnbfkjjeckoli"


def test_manifestos_do_host_so_aceitam_a_extensao_fixada_e_usam_stdio() -> None:
    chrome = _json("host/br.com.granafacil.jarvis.chrome.json")
    firefox = _json("host/br.com.granafacil.jarvis.firefox.json")

    for manifesto in (chrome, firefox):
        assert manifesto["name"] == "br.com.granafacil.jarvis"
        assert manifesto["type"] == "stdio"
        assert manifesto["path"] == "__JARVIS_NATIVE_HOST_ABSOLUTO__"
    assert chrome["allowed_origins"] == ["chrome-extension://eainnehpangdlhmjenljnbfkjjeckoli/"]
    assert firefox["allowed_extensions"] == ["jarvis-browser@granafacil.local"]


def test_extensao_expoe_so_comandos_tipados_e_sem_servidor_de_rede() -> None:
    fundo = (EXTENSAO / "background.js").read_text(encoding="utf-8")
    conteudo = (EXTENSAO / "content.js").read_text(encoding="utf-8")

    for metodo in (
        "tabs.list",
        "tabs.active",
        "tabs.open",
        "tabs.navigate",
        "page.read",
        "page.inspect",
        "page.click",
        "page.type",
        "page.scroll",
    ):
        assert f'case "{metodo}"' in fundo
    assert "connectNative" in fundo
    assert "new WebSocket(" not in fundo
    assert "fetch(" not in fundo
    assert 'addEventListener("message"' not in conteudo
    assert "campo_sensivel" in conteudo
    assert "time[datetime]" in conteudo
