"""A ligação das `browser.*` ao laço de voz: opt-in do dono, sem navegador nem socket reais."""

from __future__ import annotations

from pathlib import Path

from jarvis.navegador.cliente import familia_do_host
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao, escrever, ler

BASE = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco", acesso="padrao")


def _app(tmp_path: Path, **mudancas: object) -> Aplicativo:
    raiz = tmp_path / "sessao"
    raiz.mkdir(parents=True, exist_ok=True)
    return Aplicativo(
        configuracao=BASE.com(**mudancas),
        raiz=raiz,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "XDG_RUNTIME_DIR": str(tmp_path / "rt")},
        lar=tmp_path / "casa",
    )


def test_o_padrao_e_desligado_e_as_tools_do_navegador_nao_aparecem(tmp_path: Path) -> None:
    assert BASE.navegador_controlado is False
    ids = {t["id"] for t in _app(tmp_path)._montar_ferramentas().catalogo_para_o_modelo()}
    assert not {i for i in ids if i.startswith("browser.") and i != "browser.launch"}


def test_ligado_pelo_dono_o_modelo_ve_as_seis_tools_e_sem_navegador_o_erro_e_claro(
    tmp_path: Path,
) -> None:
    ferramentas = _app(tmp_path, navegador_controlado=True)._montar_ferramentas()
    ids = {t["id"] for t in ferramentas.catalogo_para_o_modelo()}
    assert {"browser.tabs", "browser.read", "browser.click", "browser.type"} <= ids
    assert "browser.acao_sensivel" not in ids
    resultado = ferramentas.executar("browser.tabs", {}, cancelado=lambda: False)
    assert resultado.status == "erro"
    assert "nenhum navegador" in resultado.motivo


def test_o_que_o_dono_grava_volta_igual(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    escrever(BASE.com(navegador_controlado=True), arquivo)
    assert ler(arquivo).navegador_controlado is True
    assert "navegador_controlado = true" in arquivo.read_text("utf-8")


def test_a_familia_do_host_vem_do_navegador_principal() -> None:
    assert familia_do_host("") == ""
    assert familia_do_host("firefox") == "firefox"
    assert {familia_do_host(n) for n in ("brave", "chrome", "chromium", "vivaldi")} == {"chromium"}
