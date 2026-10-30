"""O diagnóstico que o dono roda e cola (`tools/diagnostico_navegador.py`): com o host de verdade e
uma extensão falsa de antes do CDP, ele diz que é preciso recarregar — sem tocar em aba nenhuma —
e da trilha só saem códigos."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from tools import diagnostico_navegador as diagnostico

from jarvis.navegador.cliente import RECARREGAR
from jarvis.trilha import ARQUIVO
from tests.unit.navegador.test_host import Extensao, Navegador


@pytest.fixture
def curto(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("d")


@pytest.fixture
def navegador(curto: Path) -> Iterator[Callable[[Extensao], Navegador]]:
    abertos: list[Navegador] = []

    def abrir(roteiro: Extensao) -> Navegador:
        nav = Navegador(curto, roteiro, 5.0)
        nav.abrir()
        abertos.append(nav)
        return nav

    yield abrir
    for nav in abertos:
        nav.fechar()


def _de_antes(pedido: dict[str, Any]) -> dict[str, Any]:
    erro = {"codigo": "metodo_invalido", "mensagem": "método não autorizado para a extensão"}
    return {"id": pedido["id"], "ok": False, "error": erro}


def test_o_diagnostico_diz_para_recarregar_a_extensao_de_antes(
    navegador: Callable[[Extensao], Navegador], curto: Path, tmp_path: Path
) -> None:
    nav = navegador(_de_antes)
    trilha = tmp_path / "trilha"
    trilha.mkdir()
    eventos = [
        {"t": 1.0, "turno": "t1", "evento": "turno.inicio", "motor": "conversa-groq/x"},
        {"t": 2.0, "turno": "t1", "evento": "ferramenta.inicio", "tool_id": "browser.console"},
        {"t": 3.0, "turno": "t1", "evento": "turno.fim", "fim": "erro", "erro": "recusou"},
    ]
    (trilha / ARQUIVO).write_text("\n".join(json.dumps(e) for e in eventos), "utf-8")

    relatorio = diagnostico.coletar(
        home=tmp_path / "casa",
        ambiente={"XDG_RUNTIME_DIR": str(curto)},
        pasta_da_trilha=trilha,
        turnos=4,
        proc=tmp_path / "proc",
    )

    assert [s["vivo"] for s in relatorio["sockets"]] == [True]
    assert relatorio["versoes"][0]["extensao"] is None
    assert RECARREGAR in relatorio["o_que_fazer"]
    assert relatorio["trilha"]["ferramentas_que_nao_terminaram"] == ["browser.console"]
    # a pergunta de versão não chega à página: só `ponte.versao` foi à extensão
    assert [p["method"] for p in nav.recebidos] == ["ponte.versao"]
    linhas: list[str] = []
    diagnostico.imprimir({**relatorio, "configuracao": {}}, linhas.append)
    assert any("Recarregar" in linha for linha in linhas)


def test_sem_host_vivo_o_diagnostico_manda_abrir_o_navegador(tmp_path: Path) -> None:
    pasta = tmp_path / "run"
    pasta.mkdir(mode=0o700)
    relatorio = diagnostico.coletar(
        home=tmp_path / "casa",
        ambiente={"XDG_RUNTIME_DIR": str(pasta)},
        pasta_da_trilha=tmp_path / "trilha",
        turnos=4,
        proc=tmp_path / "proc",
    )
    assert relatorio["sockets"] == [] and relatorio["versoes"] == []
    assert any("nenhum host vivo" in passo for passo in relatorio["o_que_fazer"])
    assert any("--instalar" in passo for passo in relatorio["o_que_fazer"])
