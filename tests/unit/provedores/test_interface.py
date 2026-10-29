"""O esforço por modo e as capacidades: desconhecido não é "não", e o pensar nunca desce."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.provedores.interface import Capacidades, esforco_do_modo, limpar_texto
from jarvis.s2.motor import Modo
from jarvis.s2.motor_claude_cli import MotorClaudeCli


@pytest.mark.parametrize(
    ("esforco", "modo", "aceitos", "esperado"),
    [
        ("", Modo.RAPIDO, None, ""),
        ("", Modo.PENSAR, None, "high"),
        ("low", Modo.RAPIDO, None, "low"),
        ("low", Modo.PENSAR, None, "high"),
        ("xhigh", Modo.PENSAR, None, "xhigh"),  # pensar não desce
        ("minimal", Modo.RAPIDO, ("low", "medium", "high"), "low"),  # nada abaixo: o menor
        ("xhigh", Modo.RAPIDO, ("low", "medium", "high"), "high"),  # o mais perto por baixo
        ("medium", Modo.RAPIDO, (), ""),  # o modelo não aceita esforço
    ],
)
def test_esforco_do_modo(
    esforco: str, modo: Modo, aceitos: tuple[str, ...] | None, esperado: str
) -> None:
    assert esforco_do_modo(esforco, modo, aceitos) == esperado


def test_capacidades_completam_campo_a_campo_e_o_primeiro_vence() -> None:
    do_provedor = Capacidades(visao=False, contexto=8000)
    do_registro = Capacidades(visao=True, ferramentas=True, contexto=1, esforcos=("low",))

    junto = do_provedor.completar(do_registro)

    assert junto.visao is False  # o provedor disse "não": o registro não troca por "sim"
    assert junto.ferramentas is True
    assert junto.contexto == 8000
    assert junto.esforcos == ("low",)


def test_capacidades_de_fora_da_forma_viram_nao_informado() -> None:
    lida = Capacidades.de_dict(
        {"visao": 1, "esforcos": ["low", "turbo"], "contexto": True, "preco_entrada": -1}
    )
    assert lida == Capacidades(esforcos=("low",))
    assert Capacidades.de_dict("lixo") == Capacidades()


def test_limpar_texto_tira_controle_e_poe_teto() -> None:
    assert limpar_texto("a‮b\nc") == "a b c"
    assert len(limpar_texto("x" * 500)) == 120
    assert limpar_texto(42) == ""


def test_cli_do_claude_usa_o_esforco_do_preset_e_o_de_sempre_sem_ele(tmp_path: Path) -> None:
    def effort(motor: MotorClaudeCli, modo: Modo) -> str:
        argv = motor.argumentos(modo)
        return argv[argv.index("--effort") + 1]

    de_sempre = MotorClaudeCli(pasta_de_trabalho=tmp_path)
    assert effort(de_sempre, Modo.RAPIDO) == "low"
    assert effort(de_sempre, Modo.PENSAR) == "high"

    do_preset = MotorClaudeCli(pasta_de_trabalho=tmp_path, esforco="medium")
    assert effort(do_preset, Modo.RAPIDO) == "medium"
    assert effort(do_preset, Modo.PENSAR) == "high"
