"""Cartão F1-13 com os processos de verdade: a `ui` aperta, o `audio-io` abre.

O que este teste prova e o unitário não pode provar: o pedido e o estado atravessam a
**fronteira de processo** pela pasta de sessão, e o indicador que a `ui` escreve na tela vem do
`audio-io` — não da própria `ui`. O atalho é o backend falso por arquivo, que é justamente para
isto: outro processo (aqui, o teste; na vida real, o botão da tela ou o portal) aperta a tecla.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.microfone import Modo, ler_estado
from jarvis.supervisao import Supervisor
from jarvis.ui.atalhos import VARIAVEL_ARQUIVO, VARIAVEL_BACKEND
from jarvis.ui.painel import ARQUIVO_TELA

LIMITE = 20.0


@pytest.fixture
def supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Supervisor]:
    monkeypatch.setenv(VARIAVEL_BACKEND, "falso")
    monkeypatch.setenv(VARIAVEL_ARQUIVO, str(tmp_path / "tecla"))
    supervisor = Supervisor(raiz=tmp_path / "exec")
    yield supervisor
    supervisor.parar_tudo()


def tecla(raiz: Path, *, apertada: bool) -> None:
    """Aperta ou solta a tecla de fora dos processos, do jeito que o backend falso lê."""
    arquivo = raiz.parent / "tecla"
    temporario = arquivo.with_name("tecla.tmp")
    temporario.write_text("1" if apertada else "0", encoding="utf-8")
    temporario.replace(arquivo)


def esperar(condicao: object, descricao: str, *, limite: float = LIMITE) -> None:
    fim = time.monotonic() + limite
    assert callable(condicao)
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu em {limite}s: {descricao}")


def tela(raiz: Path) -> str:
    caminho = raiz / ARQUIVO_TELA
    return caminho.read_text(encoding="utf-8").strip() if caminho.exists() else ""


def test_ptt_abre_e_fecha_a_fonte_de_outro_processo(supervisor: Supervisor) -> None:
    raiz = supervisor.raiz
    tecla(raiz, apertada=False)
    supervisor.iniciar("agentd", "--timeout", str(LIMITE))
    supervisor.esperar_barramento()
    supervisor.iniciar("ui", "--microfone", "--modo", "ptt", "--timeout", str(LIMITE))
    supervisor.iniciar("audio-io", "--controle-de-microfone", "--timeout", str(LIMITE))

    esperar(lambda: tela(raiz) != "", "a ui escrever o que está na tela")
    esperar(
        lambda: ler_estado(raiz).modo is Modo.PTT and not ler_estado(raiz).aberta,
        "o audio-io relatar a fonte fechada no modo PTT",
    )
    # A primeira tela da `ui` é "ainda não recebi notícia do processo de áudio": ela nasce
    # antes de o `audio-io` publicar estado. Esperar só pelo **arquivo de estado** não garante
    # que a `ui` já repintou — são dois processos, e capturar a tela aqui pegava a frase
    # inicial de vez em quando (corrida do teste, não do produto).
    esperar(lambda: "segure" in tela(raiz).lower(), "a ui repintar com a fonte fechada")
    fechado = tela(raiz)

    tecla(raiz, apertada=True)
    esperar(lambda: ler_estado(raiz).aberta, "a tecla apertada abrir a fonte")
    esperar(lambda: "Ouvindo" in tela(raiz), "a tela dizer que está ouvindo")
    esperar(lambda: ler_estado(raiz).amostras > 0, "a contagem de amostras subir")
    device_id = ler_estado(raiz).device_id

    tecla(raiz, apertada=False)
    esperar(lambda: not ler_estado(raiz).aberta, "soltar a tecla fechar a fonte")

    assert "segure" in fechado.lower(), f"a tela fechada tem de dizer o que fazer: {fechado!r}"
    assert device_id is not None, "fonte aberta relata o dispositivo que está aberto"
    assert ler_estado(raiz).amostras == 0, "fonte fechada: zero amostra desta abertura"
    assert supervisor.vivo("audio-io") and supervisor.vivo("ui")


def test_kill_switch_de_outro_processo_nao_abre_nem_com_a_tecla(supervisor: Supervisor) -> None:
    """Aceite (c) atravessando a fronteira: o botão da tela vence a tecla."""
    raiz = supervisor.raiz
    tecla(raiz, apertada=True)
    supervisor.iniciar("agentd", "--timeout", str(LIMITE))
    supervisor.esperar_barramento()
    supervisor.iniciar("ui", "--microfone", "--modo", "ptt", "--timeout", str(LIMITE))
    supervisor.iniciar("audio-io", "--controle-de-microfone", "--timeout", str(LIMITE))

    esperar(lambda: ler_estado(raiz).aberta, "a tecla apertada abrir a fonte")
    (raiz / "ui-botao").write_text("desligado", encoding="utf-8")

    esperar(lambda: not ler_estado(raiz).aberta, "o kill switch fechar a fonte")
    esperar(lambda: "desligado" in tela(raiz).lower(), "a tela dizer que está desligado")
    amostras_depois = ler_estado(raiz).amostras_totais
    time.sleep(0.5)

    assert ler_estado(raiz).modo is Modo.DESLIGADO
    assert ler_estado(raiz).amostras_totais == amostras_depois, (
        "com o kill switch ligado nenhuma amostra nova é capturada, nem com a tecla apertada"
    )
    assert ler_estado(raiz).aberta is False
