"""Contrato estático da extensão: não inicia navegador, host nativo nem rede."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
EXTENSAO = RAIZ / "extensao"
TESTE_RECONEXAO = Path(__file__).with_name("background_reconexao.test.mjs")
TESTE_RESPOSTAS = Path(__file__).with_name("background_respostas.test.mjs")
TESTE_NAVEGACAO = Path(__file__).with_name("background_navegacao.test.mjs")
TESTE_CONTROLE = Path(__file__).with_name("background_controle.test.mjs")
TESTE_INDICADOR = Path(__file__).with_name("indicador.test.mjs")


def _json(nome: str) -> dict[str, object]:
    return json.loads((EXTENSAO / nome).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _id_chromium(chave: str) -> str:
    digest = hashlib.sha256(base64.b64decode(chave)).hexdigest()[:32]
    return digest.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def test_manifesto_mv3_pina_ids_e_so_age_em_paginas_http() -> None:
    manifesto = _json("manifest.json")
    permissoes = manifesto["permissions"]
    hosts = manifesto["host_permissions"]

    assert manifesto["manifest_version"] == 3
    assert isinstance(permissoes, list)
    assert isinstance(hosts, list)
    assert set(permissoes) == {"activeTab", "tabs", "nativeMessaging"}
    # `<all_urls>` só porque a captura da tela a exige no Chromium (captureVisibleTab) e no
    # Firefox (captureTab) — ADR-0032. O conteúdo roda só em http/https, e o fundo só captura aba
    # http/https; página interna do navegador o Chromium nem deixa capturar com esta permissão.
    assert hosts == ["<all_urls>"]
    conteudos = manifesto["content_scripts"]
    assert isinstance(conteudos, list)
    # A faixa "no controle" nasce com o documento (indicador.js), antes da página; o resto do
    # conteúdo, quando ela termina. Os dois só em http/https e só no quadro principal.
    assert [(c["js"], c["run_at"]) for c in conteudos] == [
        (["indicador.js"], "document_start"),
        (["content.js"], "document_idle"),
    ]
    assert all(c["matches"] == ["http://*/*", "https://*/*"] for c in conteudos)
    assert all(c["all_frames"] is False for c in conteudos)
    # O botão da extensão é o PARAR (sem popup: o clique vai para o fundo) e mostra o selo.
    assert manifesto["action"] == {
        "default_title": "Jarvis — ponte local, sem controlar nenhuma aba"
    }
    fundo = (EXTENSAO / "background.js").read_text(encoding="utf-8")
    assert '"aba_nao_http"' in fundo
    assert manifesto["browser_specific_settings"] == {
        "gecko": {"id": "jarvis-browser@granafacil.local", "strict_min_version": "121.0"}
    }
    assert _id_chromium(str(manifesto["key"])) == "eainnehpangdlhmjenljnbfkjjeckoli"


def test_o_fundo_roda_no_chromium_e_no_firefox() -> None:
    """O Firefox não tem service worker de extensão: só com `service_worker` ele recusa instalar
    ("background.service_worker is currently disabled. Add background.scripts.", Firefox 158 em
    contêiner, 2026-10-19). Com as duas chaves, o Chromium ≥ 121 usa o worker e ignora `scripts`,
    e o Firefox ≥ 121 usa `scripts` (MDN, manifest.json/background) — o mesmo arquivo."""
    fundo = _json("manifest.json")["background"]
    assert fundo == {"service_worker": "background.js", "scripts": ["background.js"]}


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
        "tabs.current",
        "tabs.open",
        "tabs.navigate",
        "tabs.show",
        "controle.soltar",
        "controle.manter",
        "controle.parar",
        "controle.estado",
        "page.read",
        "page.inspect",
        "page.click",
        "page.type",
        "page.scroll",
        "page.map",
        "page.act",
        "page.capture",
        "page.readUrl",
    ):
        assert f'case "{metodo}"' in fundo
    assert "connectNative" in fundo
    assert "new WebSocket(" not in fundo
    assert "fetch(" not in fundo
    assert 'addEventListener("message"' not in conteudo
    assert "campo_sensivel" in conteudo
    # O alvo vem do Jarvis como texto visível ou referência do mapa (ADR-0032), nunca seletor CSS:
    # o seletor estável é gerado e usado só dentro da página, para reencontrar o elemento.
    assert "params.selector" not in conteudo and "params.seletor" not in conteudo
    assert "eval(" not in conteudo and "new Function" not in conteudo
    assert "time[datetime]" in conteudo


def test_so_a_automacao_social_chega_a_criar_janela() -> None:
    """Uma instância só (dono, 2026-10-21: a janela própria do Jarvis parecia outro Brave, e o
    vídeo abriu nela). O único `windows.create` da extensão é o da janela do Jarvis, e só o caminho
    do modo `automacao_social` chama quem a cria (o comportamento: `background_navegacao`)."""
    fundo = (EXTENSAO / "background.js").read_text(encoding="utf-8")
    assert fundo.count("windows.create(") == 1
    assert fundo.count("await janelaDoJarvis()") == 2  # a aba social e a busca social
    assert fundo.count("return abrirNaJanelaDoJarvis(url, concessao);") == 1
    assert 'const MODO_AUTOMACAO_SOCIAL = "automacao_social"' in fundo


@pytest.mark.parametrize(
    "roteiro",
    [TESTE_RECONEXAO, TESTE_RESPOSTAS, TESTE_NAVEGACAO, TESTE_CONTROLE, TESTE_INDICADOR],
    ids=lambda p: p.stem,
)
def test_comportamento_do_fundo_com_porta_e_abas_falsas(roteiro: Path) -> None:
    """Reconexão (uma porta, um timer), a forma do que vai ao host (resultado plano), a navegação
    conferida (a aba saiu do lugar, a página abriu, ficou à vista?) e o controle: a faixa, o selo e
    o PARAR (ADR-0027 regra 4)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js não está disponível para o teste comportamental da extensão")

    resultado = subprocess.run(
        [node, "--test", str(roteiro)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
