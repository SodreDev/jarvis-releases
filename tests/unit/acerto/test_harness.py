"""ADR-0064: o harness de acerto em pt-BR — nota 0/1/2 sem juiz, gate por categoria, motor falso."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from tools import harness_acerto

from jarvis.acerto import (
    CENARIOS,
    N_MINIMO,
    NENHUMA,
    Ambiente,
    Cenario,
    Placar,
    Tipo,
    avaliar,
    carregar,
    gate,
    ler_base,
    pontuar_ferramenta,
    rodar,
)
from jarvis.s2.motor import Contexto, Delta, Fim, Modo, MotivoDoFim, PedidoDeTool, Texto
from jarvis.voz.interface import Cancelado, Onde


def _motor_cenario(ferramenta: str, **args: object) -> Cenario:
    return Cenario("c", "motor", Tipo.MOTOR, "abre o Discord", ferramenta, dict(args))


def test_nota_dois_um_e_zero_sem_juiz() -> None:
    cenario = _motor_cenario("apps.launch", nome="discord")
    assert pontuar_ferramenta(cenario, "apps.launch", {"nome": "discord", "extra": 1}) == 2
    assert pontuar_ferramenta(cenario, "apps.launch", {"nome": "spotify"}) == 1
    assert pontuar_ferramenta(cenario, "apps.launch", {}) == 1
    assert pontuar_ferramenta(cenario, "window.close", {"nome": "discord"}) == 0
    assert pontuar_ferramenta(cenario, None, {}) == 0
    nenhuma = _motor_cenario(NENHUMA)
    assert pontuar_ferramenta(nenhuma, None, {}) == 2
    assert pontuar_ferramenta(nenhuma, "web.buscar", {}) == 0


@dataclass
class MotorFalso:
    """Responde por palavra-chave, de propósito imperfeito: erra o argumento do Discord e propõe
    busca na piada. Nunca rede."""

    nome: str = "falso"
    onde: Onde = Onde.LOCAL
    aceita_imagem: bool = False

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        fala = contexto.mensagens[-1].texto.casefold()
        if "horas" in fala:
            yield PedidoDeTool("system.clock.now", {})
        elif "discord" in fala:
            yield PedidoDeTool("apps.launch", {"nome": "Discórdia"})
        elif "anota" in fala:
            yield PedidoDeTool("memoria.lembrar", {"texto": fala})
        elif "pesquisa" in fala or "piada" in fala:
            yield PedidoDeTool("web.buscar", {"consulta": fala})
        else:
            yield Texto("Não sei.")
        yield Fim(MotivoDoFim.CONCLUIDO)


def test_os_cenarios_de_motor_so_rodam_com_motor_e_pontuam_a_primeira_proposta() -> None:
    cenarios = [c for c in carregar() if c.tipo is Tipo.MOTOR]
    assert len(cenarios) >= N_MINIMO
    assert all(avaliar(c, Ambiente()) is None for c in cenarios), "sem motor, não roda"

    placar = rodar(cenarios, motor=MotorFalso(), rodadas=1)
    assert placar.n == {"motor": len(cenarios)}
    # hora 2, discord 1 (argumento errado), busca 2, anota 2, piada 0 (propôs busca)
    assert placar.pontos["motor"] == 7 and placar.maximo["motor"] == 10
    assert {e.cenario.id: e.pontos for e in placar.erros} == {
        "motor-abre-discord": 1,
        "motor-piada-sem-ferramenta": 0,
    }


def test_os_cenarios_do_codigo_passam_no_gate_da_linha_de_base() -> None:
    placar = rodar(carregar())
    assert gate(placar, ler_base()) == []
    assert all(n >= N_MINIMO for n in placar.n.values()), "toda categoria do gate tem n mínimo"
    assert "motor" not in placar.n


def _placar(fracoes: dict[str, float], n: int = 10) -> Placar:
    return Placar(
        pontos={c: f * 2 * n for c, f in fracoes.items()},
        maximo=dict.fromkeys(fracoes, 2 * n),
        n=dict.fromkeys(fracoes, n),
        erros=(),
    )


def test_o_gate_reprova_categoria_que_cai_alem_da_tolerancia_e_o_total() -> None:
    base = {
        "total": 0.9,
        "categorias": {"apps": {"fracao": 0.9, "n": 10}, "web": {"fracao": 0.9, "n": 10}},
    }
    assert gate(_placar({"apps": 0.9, "web": 0.9}), base) == []
    problemas = gate(_placar({"apps": 1.0, "web": 0.8}), base)
    assert problemas == ["web: 90.0% → 80.0%"], "o total igual não esconde a categoria que caiu"
    assert any("total caiu" in p for p in gate(_placar({"apps": 0.86, "web": 0.86}), base))
    assert (
        gate(_placar({"apps": 0.0, "web": 0.9}, n=N_MINIMO - 1), {"categorias": base["categorias"]})
        == []
    )
    assert gate(_placar({"apps": 0.9}), base) == ["web: a categoria sumiu dos cenários"]


def test_id_repetido_nos_cenarios_e_recusado(tmp_path: Path) -> None:
    texto = CENARIOS.read_text("utf-8")
    primeiro = texto.index("[[cenario]]")
    bloco = texto[primeiro : texto.index("[[cenario]]", primeiro + 1)]
    caminho = tmp_path / "c.toml"
    caminho.write_text(texto + "\n" + bloco, "utf-8")
    with pytest.raises(ValueError, match="repetido"):
        carregar(caminho)


def test_o_script_sai_com_zero_no_gate_verde(capsys: pytest.CaptureFixture[str]) -> None:
    assert harness_acerto.main(["--gate"]) == 0
    saida = capsys.readouterr().out
    assert "| **total** |" in saida and "nada piorou" in saida
