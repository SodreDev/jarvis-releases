"""ADR-0061: tokens, custo e tempo até o 1º token de cada chamada ao motor — só números."""

from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.s2.cerebro import Cerebro
from jarvis.s2.consumo import (
    ConsumoDoTurno,
    Medicao,
    custo_microusd,
    estimar_tokens,
    medicao_da_chamada,
    medir,
    precos_do_motor,
    tokens_do_uso,
)
from jarvis.s2.motor import Contexto, Delta, Fim, Modo, MotivoDoFim, PedidoDeTool, Texto
from jarvis.trilha import ARQUIVO, TrilhaDeDiagnostico, consumo_por_dia, resumo_do_ultimo_turno
from jarvis.voz.interface import Cancelado, Onde

SEGREDO_DO_DONO = "minha conta do banco termina em 4321"


def _relogio(*instantes: float) -> Iterator[float]:
    yield from instantes


def test_tokens_de_cada_provedor_viram_entrada_e_saida() -> None:
    assert tokens_do_uso({"entrada": 10, "saida": 3}) == (10, 3)  # compatível e Codex
    assert tokens_do_uso({"prompt_tokens": 7, "completion_tokens": 2}) == (7, 2)
    # A CLI do Claude: o que veio do cache também é entrada.
    claude = {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 9}
    assert tokens_do_uso(claude) == (105, 9)
    assert tokens_do_uso({"deltas": 4}) == (None, None)
    assert tokens_do_uso({"entrada": True, "saida": -1}) == (None, None)


def test_custo_e_tokens_vezes_preco_por_milhao_em_micro_dolares() -> None:
    # 1 000 tokens a US$ 2/milhão + 500 a US$ 8/milhão = US$ 0,006 = 6 000 µUS$.
    assert custo_microusd(1000, 500, 2.0, 8.0) == 6000
    assert custo_microusd(1000, 500, None, 8.0) is None


def test_sem_usage_estima_pelos_caracteres_e_marca_estimado() -> None:
    medicao = medicao_da_chamada(
        {},
        caracteres_entrada=lambda: 400,
        caracteres_saida=41,
        precos=(1.0, 1.0),
        ms_primeiro_token=5.0,
        ms=9.0,
        fim="concluido",
    )
    assert (medicao.tokens_entrada, medicao.tokens_saida) == (100, estimar_tokens(41)) == (100, 11)
    assert medicao.estimado is True
    assert medicao.custo_microusd == 111


def test_com_usage_nao_monta_o_contexto_e_o_custo_reportado_vence() -> None:
    def nao_chame() -> int:
        raise AssertionError("com o usage, o texto do contexto não é montado")

    medicao = medicao_da_chamada(
        {"input_tokens": 10, "output_tokens": 2, "custo_microusd": 77},
        caracteres_entrada=nao_chame,
        caracteres_saida=999,
        precos=(1.0, 1.0),
        ms_primeiro_token=None,
        ms=1.0,
        fim="concluido",
    )
    assert (medicao.tokens_entrada, medicao.tokens_saida, medicao.estimado) == (10, 2, False)
    assert medicao.custo_microusd == 77


def test_sem_preco_o_custo_e_none_e_a_soma_do_turno_tambem() -> None:
    consumo = ConsumoDoTurno()
    consumo.somar(Medicao(10, 2, False, 30, 1.0, 2.0, "concluido"))
    assert consumo.campos()["custo_microusd"] == 30
    consumo.somar(Medicao(10, 2, True, None, 1.0, 2.0, "concluido"))
    campos = consumo.campos()
    assert campos == {
        "chamadas_ao_motor": 2,
        "tokens_entrada": 20,
        "tokens_saida": 4,
        "tokens_estimados": True,
        "custo_microusd": None,
    }
    assert ConsumoDoTurno().campos() == {"chamadas_ao_motor": 0}


def test_medir_passa_os_mesmos_deltas_e_mede_o_primeiro_token() -> None:
    deltas: list[Delta] = [
        Texto("olá"),
        PedidoDeTool("apps.open", {"nome": "x"}),
        Fim(MotivoDoFim.CONCLUIDO, uso={"entrada": 50, "saida": 5}),
    ]
    medidas: list[Medicao] = []
    instantes = _relogio(0.0, 0.25, 1.0)
    saida = list(
        medir(
            iter(deltas),
            caracteres_entrada=lambda: 0,
            precos=lambda: (None, None),
            ao_medir=medidas.append,
            relogio=lambda: next(instantes),
        )
    )
    assert saida == deltas
    [medicao] = medidas
    assert medicao.ms_primeiro_token == 250.0 and medicao.ms == 1000.0
    assert (medicao.tokens_entrada, medicao.tokens_saida, medicao.fim) == (50, 5, "concluido")


def test_fechar_no_meio_fecha_o_motor_e_ainda_mede_como_cortada() -> None:
    fechado: list[bool] = []

    def motor() -> Generator[Delta, None, None]:
        try:
            yield Texto("um")
            yield Texto("dois")
        finally:
            fechado.append(True)

    medidas: list[Medicao] = []
    deltas = medir(
        motor(), caracteres_entrada=lambda: 8, precos=lambda: (None, None), ao_medir=medidas.append
    )
    assert next(deltas) == Texto("um")
    deltas.close()
    assert fechado == [True]
    [medicao] = medidas
    assert medicao.fim == "cortada" and medicao.estimado and medicao.tokens_entrada == 2


def test_falha_ao_anotar_nao_derruba_quem_consome() -> None:
    def explode(_: Medicao) -> None:
        raise RuntimeError("disco cheio")

    saida = list(
        medir(
            iter([Fim(MotivoDoFim.CONCLUIDO)]),
            caracteres_entrada=lambda: 0,
            precos=lambda: (None, None),
            ao_medir=explode,
        )
    )
    assert len(saida) == 1


def test_precos_do_motor_so_aceita_numeros() -> None:
    @dataclass
    class ComPreco:
        precos: object

    assert precos_do_motor(ComPreco((0.5, 2))) == (0.5, 2.0)
    assert precos_do_motor(ComPreco(("x", -1))) == (None, None)
    assert precos_do_motor(object()) == (None, None)


@dataclass
class MotorComUso:
    """Motor falso: duas rodadas (uma proposta e a resposta), cada uma com o seu `usage`."""

    nome: str = "falso com uso"
    onde: Onde = Onde.NUVEM
    aceita_imagem: bool = False
    codigo: str = "falso/modelo"
    precos: tuple[float | None, float | None] = (1.0, 4.0)
    rodadas: list[list[Delta]] = field(default_factory=list)

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        yield from self.rodadas.pop(0)


def test_o_turno_soma_as_chamadas_e_a_trilha_so_recebe_numeros(tmp_path: Path) -> None:
    motor = MotorComUso(
        rodadas=[
            [
                Texto("Pronto, a resposta é curta."),
                Fim(MotivoDoFim.CONCLUIDO, uso={"entrada": 1000, "saida": 50}),
            ],
        ]
    )
    cerebro = Cerebro(motor=motor)
    resposta = cerebro.responder(SEGREDO_DO_DONO, epoch=0, publicar=lambda _: None)
    campos = resposta.consumo.campos()
    assert campos["chamadas_ao_motor"] == 1
    assert (campos["tokens_entrada"], campos["tokens_saida"]) == (1000, 50)
    assert campos["custo_microusd"] == 1000 * 1 + 50 * 4
    assert campos["tokens_estimados"] is False

    trilha = TrilhaDeDiagnostico(tmp_path, relogio=lambda: 1_700_000_000.0)
    trilha.novo_turno("t-1", motor="falso/modelo")
    trilha.evento(
        "motor.chamada",
        motor="falso/modelo",
        origem="turno",
        tokens_entrada=1000,
        tokens_saida=50,
        tokens_estimados=False,
        custo_microusd=1200,
        ms_primeiro_token=321.0,
        ms=900.0,
        fim="concluido",
    )
    trilha.evento("turno.fim", fim="concluido", **campos)
    texto = (tmp_path / ARQUIVO).read_text("utf-8")
    assert SEGREDO_DO_DONO not in texto
    eventos = [json.loads(linha) for linha in texto.splitlines()]
    assert all("campos_fora" not in e for e in eventos)
    resumo = "\n".join(resumo_do_ultimo_turno(tmp_path))
    assert "tokens 1000 → 50" in resumo and "US$ 0,0012" in resumo
    assert "1º token 321 ms" in resumo


def test_resumo_por_dia_soma_chamadas_e_diz_o_que_e_estimado_ou_sem_preco(tmp_path: Path) -> None:
    instantes = iter([1_700_000_000.0 + i for i in range(10)])
    trilha = TrilhaDeDiagnostico(tmp_path, relogio=lambda: next(instantes))
    for custo, estimado, ttft in ((2000, False, 100.0), (None, True, 300.0), (500, False, 200.0)):
        trilha.evento(
            "motor.chamada",
            origem="turno",
            tokens_entrada=100,
            tokens_saida=10,
            tokens_estimados=estimado,
            custo_microusd=custo,
            ms_primeiro_token=ttft,
            ms=1000.0,
            fim="concluido",
        )
    [linha] = consumo_por_dia(tmp_path)
    assert "3 chamada(s)" in linha and "tokens 300 → 30" in linha
    assert "US$ 0,0025" in linha and "1º token mediano 200 ms" in linha
    assert "1 com tokens estimados" in linha and "1 sem preço no catálogo" in linha


def test_resumo_por_dia_sem_chamadas_diz_que_nao_ha(tmp_path: Path) -> None:
    assert consumo_por_dia(tmp_path) == ["  consumo: nenhuma chamada ao motor na trilha"]
