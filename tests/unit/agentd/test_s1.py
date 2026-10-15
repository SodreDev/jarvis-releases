"""Cartão F1-08: um teste por linha da tabela, o orçamento, o epoch morto e o replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.agentd.s1 import (
    ARQUIVO_TABELA,
    S1,
    TETO_MS,
    Acao,
    ErroDeTabela,
    EstadoS1,
    Tabela,
    decisoes_da_trilha,
    estado_da_trilha,
)
from jarvis.audio_io import FonteSintetica, reproduzir
from jarvis.audio_io.trilha import EventoDeTrilha
from jarvis.relogio import RelogioFalso

SESSAO = "0193f0a0-0000-7000-8000-000000000000"

# Um estado por linha da tabela: é o aceite (a). Se uma linha nova entrar sem teste, o
# `test_toda_linha_da_tabela_tem_teste` falha.
ESTADOS: dict[str, EstadoS1] = {
    "L01": EstadoS1(orcamento_estourado=True, fala_do_dono=False, decisao_de_turno="yield"),
    "L02": EstadoS1(epoch_atual=5, epoch_do_evento=4, decisao_de_turno="yield"),
    "L03": EstadoS1(aec_ok=False, tocando=True),
    "L04a": EstadoS1(fala_do_dono=True, tocando=True, duracao_fala_ms=120.0),
    "L04": EstadoS1(fala_do_dono=True, tocando=True, duracao_fala_ms=900.0),
    "L05": EstadoS1(fala_do_dono=True, tocando=False, decisao_de_turno="yield"),
    "L06": EstadoS1(
        fala_do_dono=True,
        tocando=False,
        duracao_fala_ms=5000.0,
        p_eot=0.1,
        decisao_de_turno="hold",
    ),
    "L07": EstadoS1(fala_do_dono=True, tocando=False, duracao_fala_ms=500.0, p_eot=0.8),
    "L08": EstadoS1(fala_do_dono=False, tocando=False, decisao_de_turno="yield"),
    "L09": EstadoS1(fala_do_dono=False, tocando=True, decisao_de_turno="yield"),
    "L10": EstadoS1(fala_do_dono=False, decisao_de_turno="unknown"),
    "L11": EstadoS1(fala_do_dono=False, decisao_de_turno="hold"),
    "L12": EstadoS1(fala_do_dono=False, decisao_de_turno="ausente"),
}
ESPERADO: dict[str, Acao] = {
    "L01": Acao.OUVIR,
    "L02": Acao.OUVIR,
    "L03": Acao.CANCELAR,
    "L04a": Acao.CEDER,
    "L04": Acao.CANCELAR,
    "L05": Acao.OUVIR,
    "L06": Acao.BACKCHANNEL,
    "L07": Acao.OUVIR,
    "L08": Acao.FALAR,
    "L09": Acao.OUVIR,
    "L10": Acao.OUVIR,
    "L11": Acao.OUVIR,
    "L12": Acao.OUVIR,
}


@pytest.fixture
def s1() -> S1:
    return S1()


def test_toda_linha_da_tabela_tem_teste() -> None:
    """Aceite (a): linha nova sem teste é falha de teste, não descuido silencioso."""
    tabela = Tabela.do_arquivo()

    assert set(tabela.ids) == set(ESTADOS), "toda linha precisa de um estado que a exercite"
    assert set(tabela.ids) == set(ESPERADO)


@pytest.mark.parametrize("linha_id", list(ESTADOS))
def test_cada_linha_decide_o_que_diz_decidir(linha_id: str, s1: S1) -> None:
    decisao = s1.decidir(ESTADOS[linha_id])

    assert decisao.linha == linha_id, f"{linha_id} foi capturada por {decisao.linha}"
    assert decisao.acao is ESPERADO[linha_id]
    assert decisao.porque, "decisão sem porquê não é auditável"


def test_a_tabela_cobre_as_cinco_acoes_da_secao_2() -> None:
    tabela = Tabela.do_arquivo()
    acoes = {linha.entao for linha in tabela.linhas}

    assert acoes == set(Acao), "as cinco ações da §2 têm de existir na tabela"
    assert sum(1 for linha in tabela.linhas if linha.entao is Acao.FALAR) == 1, (
        "só uma linha pode levar a falar"
    )


def test_orcamento_estourado_cai_em_ouvir_e_nunca_em_falar(s1: S1) -> None:
    """Aceite (c): atraso injetado estoura o orçamento e derruba a decisão para ouvir."""
    vez_de_falar = EstadoS1(fala_do_dono=False, tocando=False, decisao_de_turno="yield")

    assert s1.decidir(vez_de_falar, gasto_ms=0.0).acao is Acao.FALAR

    estourado = s1.decidir(vez_de_falar, gasto_ms=TETO_MS + 1.0)

    assert estourado.acao is Acao.OUVIR
    assert estourado.linha == "L01"


def test_dentro_do_orcamento_a_decisao_nao_muda(s1: S1) -> None:
    vez_de_falar = EstadoS1(fala_do_dono=False, tocando=False, decisao_de_turno="yield")

    assert s1.decidir(vez_de_falar, gasto_ms=TETO_MS - 1.0).acao is Acao.FALAR


def test_epoch_morto_nunca_produz_som(s1: S1) -> None:
    """Aceite (d): §3.3 regra 6 vale no S1 como vale no s2."""
    for estado in ESTADOS.values():
        morto = EstadoS1(
            epoch_atual=9,
            epoch_do_evento=8,
            aec_ok=estado.aec_ok,
            fala_do_dono=estado.fala_do_dono,
            tocando=estado.tocando,
            decisao_de_turno=estado.decisao_de_turno,
            p_eot=estado.p_eot,
            duracao_fala_ms=estado.duracao_fala_ms,
        )
        decisao = s1.decidir(morto)
        assert not decisao.produz_som, f"{decisao.linha} produziu som em epoch morto"


def test_unknown_nunca_vira_falar(s1: S1) -> None:
    for tocando in (False, True):
        decisao = s1.decidir(
            EstadoS1(fala_do_dono=False, tocando=tocando, decisao_de_turno="unknown", p_eot=0.5)
        )
        assert decisao.acao is not Acao.FALAR


def test_a_mesma_trilha_produz_a_mesma_sequencia_de_decisoes() -> None:
    """Aceite (e): determinismo sobre a trilha do F1-01."""

    def trilha() -> list[EventoDeTrilha]:
        fonte = FonteSintetica(relogio=RelogioFalso(), semente=7)
        return reproduzir(fonte, session_id=SESSAO).eventos

    primeira = decisoes_da_trilha(trilha())
    segunda = decisoes_da_trilha(trilha())

    assert [d.linha for d in primeira] == [d.linha for d in segunda]
    assert [d.acao for d in primeira] == [d.acao for d in segunda]
    assert primeira, "a trilha do F1-01 tem eventos"


def test_o_estado_da_trilha_acumula_fala_playback_e_epoch() -> None:
    eventos = [
        EventoDeTrilha(
            type="AudioActivity",
            epoch=0,
            ts_mono_ns=20_000_000,
            payload={"speech": True, "aec_ok": True, "device_id": "d", "energy_db": -18.0},
        ),
        EventoDeTrilha(
            type="AudioActivity",
            epoch=0,
            ts_mono_ns=1_020_000_000,
            payload={"speech": True, "aec_ok": True, "device_id": "d", "energy_db": -18.0},
        ),
        EventoDeTrilha(
            type="TurnPrediction",
            epoch=0,
            ts_mono_ns=1_040_000_000,
            payload={"p_eot": 0.9, "detector": "semantico", "decision": "yield"},
        ),
        EventoDeTrilha(
            type="Cancel",
            epoch=1,
            ts_mono_ns=1_060_000_000,
            payload={"epoch_invalidado": 0, "reason": "barge_in"},
        ),
    ]

    passos = estado_da_trilha(eventos)

    assert passos[1][1].duracao_fala_ms == pytest.approx(1000.0)
    assert passos[2][1].decisao_de_turno == "yield"
    assert passos[3][1].epoch_atual == 1
    assert passos[3][1].epoch_do_evento == 1


# --- a tabela é dado, e dado inválido é recusado --------------------------------------
def tabela_com(mudanca: dict[str, object], tmp_path: Path) -> Path:
    dados = json.loads(ARQUIVO_TABELA.read_text(encoding="utf-8"))
    dados.update(mudanca)
    caminho = tmp_path / "s1.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_condicao_desconhecida_e_recusada(tmp_path: Path) -> None:
    caminho = tabela_com(
        {"linhas": [{"id": "X", "quando": {"lua_cheia": True}, "entao": "ouvir", "porque": "x"}]},
        tmp_path,
    )

    with pytest.raises(ErroDeTabela, match="lua_cheia"):
        Tabela.do_arquivo(caminho)


def test_acao_fora_das_cinco_e_recusada(tmp_path: Path) -> None:
    caminho = tabela_com(
        {"linhas": [{"id": "X", "quando": {}, "entao": "improvisar", "porque": "x"}]}, tmp_path
    )

    with pytest.raises(ErroDeTabela, match="improvisar"):
        Tabela.do_arquivo(caminho)


def test_linha_sem_porque_e_recusada(tmp_path: Path) -> None:
    caminho = tabela_com(
        {"linhas": [{"id": "X", "quando": {}, "entao": "ouvir", "porque": "  "}]}, tmp_path
    )

    with pytest.raises(ErroDeTabela, match="auditável"):
        Tabela.do_arquivo(caminho)


def test_tabela_sem_saida_padrao_e_recusada(tmp_path: Path) -> None:
    caminho = tabela_com(
        {
            "linhas": [
                {"id": "X", "quando": {"fala_do_dono": True}, "entao": "ouvir", "porque": "x"}
            ]
        },
        tmp_path,
    )

    with pytest.raises(ErroDeTabela, match="saída padrão"):
        Tabela.do_arquivo(caminho)
