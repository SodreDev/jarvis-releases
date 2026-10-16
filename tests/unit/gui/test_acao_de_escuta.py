"""`definirModoDeEscuta`: o modelo propõe o modo, o código decide (ADR-0021).

Teste de política pedido pelo dono: trocar atalho ↔ palavra ↔ contínua passa direto, mas ligar
a escuta contínua — ou um modo que abre o microfone sozinho com ASR na nuvem — espera o sim
dele na tela. E nenhuma ação do vocabulário liga nuvem.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from jarvis.gui.acoes import Acao, AcaoInvalida, Tipo, ler_acao
from jarvis.gui.workspace import Resultado, Workspace
from jarvis.voz.escuta import Escuta, ModoDeEscuta

ATALHO, PALAVRA, CONTINUA = ModoDeEscuta.ATALHO, ModoDeEscuta.PALAVRA, ModoDeEscuta.CONTINUA


def espaco(modo: ModoDeEscuta = ATALHO, *, nuvem: bool = False) -> Workspace:
    return Workspace(escuta=Escuta(modo=modo), asr_na_nuvem=lambda: nuvem)


def pedir(alvo: Workspace, modo: str, motivo: str = "") -> Resultado:
    return alvo.propor({"tipo": "definirModoDeEscuta", "escuta": modo, "motivo": motivo})


# --- leitura --------------------------------------------------------------------------------
def test_a_acao_e_lida_com_o_modo() -> None:
    acao = ler_acao({"tipo": "definirModoDeEscuta", "escuta": "palavra", "motivo": "TV alta"})
    assert acao.tipo is Tipo.ESCUTA
    assert acao.escuta is PALAVRA
    assert acao.para_dict() == {
        "tipo": "definirModoDeEscuta",
        "escuta": "palavra",
        "motivo": "TV alta",
    }


@pytest.mark.parametrize(
    ("bruto", "trecho"),
    [
        ({"tipo": "definirModoDeEscuta", "escuta": "sempre"}, "não existe"),
        ({"tipo": "definirModoDeEscuta"}, "não existe"),
        ({"tipo": "createWidget", "componente": "relogio", "escuta": "vad"}, "só existe em"),
        (
            {"tipo": "definirModoDeEscuta", "escuta": "palavra", "dados": {"palavra": "sexta"}},
            "não leva dados",
        ),
    ],
)
def test_proposta_malformada_e_recusada(bruto: dict[str, object], trecho: str) -> None:
    with pytest.raises(AcaoInvalida, match=trecho):
        ler_acao(bruto)


# --- a política, pelo gerente ---------------------------------------------------------------
def test_atalho_para_palavra_passa_direto_com_asr_local() -> None:
    alvo = espaco(ATALHO)
    resultado = pedir(alvo, "palavra")
    assert resultado.aceita is True
    assert alvo.escuta is not None and alvo.escuta.modo is PALAVRA
    assert alvo.pendentes == {}
    assert resultado.frase_do_dono() == "agora: palavra de ativação"


@pytest.mark.parametrize(
    ("de", "para"), [(PALAVRA, ATALHO), (CONTINUA, PALAVRA), (CONTINUA, ATALHO)]
)
@pytest.mark.parametrize("nuvem", [False, True])
def test_escutar_menos_passa_direto(de: ModoDeEscuta, para: ModoDeEscuta, nuvem: bool) -> None:
    alvo = espaco(de, nuvem=nuvem)
    assert pedir(alvo, para.value).aceita is True
    assert alvo.escuta is not None and alvo.escuta.modo is para


@pytest.mark.parametrize("nuvem", [False, True])
def test_escuta_continua_pedida_pelo_modelo_espera_o_dono(nuvem: bool) -> None:
    alvo = espaco(PALAVRA, nuvem=nuvem)
    resultado = pedir(alvo, "vad", motivo="você está ditando um texto longo")

    assert resultado.pendente is True
    assert alvo.escuta is not None and alvo.escuta.modo is PALAVRA, "trocou sem o sim do dono"
    pendencia = alvo.para_dict()["pendentes"][0]
    assert pendencia["titulo"] == "escuta: escuta contínua", "pendência sem nome na tela"
    assert "ditando" in pendencia["motivo"]
    assert "todo trecho de fala virar pedido" in resultado.motivo


def test_palavra_com_asr_na_nuvem_espera_o_dono() -> None:
    alvo = espaco(ATALHO, nuvem=True)
    resultado = pedir(alvo, "palavra")
    assert resultado.pendente is True
    assert "fora da máquina" in resultado.motivo
    assert alvo.escuta is not None and alvo.escuta.modo is ATALHO


def test_o_sim_do_dono_aplica_e_o_nao_descarta() -> None:
    alvo = espaco(ATALHO)
    pendencia = pedir(alvo, "vad").pendencia
    recusa = alvo.confirmar(pendencia, sim=False)
    assert recusa is not None and not recusa.aceita
    assert alvo.escuta is not None and alvo.escuta.modo is ATALHO

    pendencia = pedir(alvo, "vad").pendencia
    feito = alvo.confirmar(pendencia, sim=True)
    assert feito is not None and feito.aceita
    assert alvo.escuta.modo is CONTINUA


def test_sem_sessao_de_voz_nao_ha_o_que_trocar() -> None:
    resultado = Workspace().propor({"tipo": "definirModoDeEscuta", "escuta": "palavra"})
    assert resultado.aceita is False
    assert "não há sessão de voz" in resultado.motivo


# --- o que a IA não alcança -----------------------------------------------------------------
def test_nenhuma_acao_do_vocabulario_liga_nuvem() -> None:
    """Nem campo, nem tipo, nem dados: ligar nuvem é só do dono, na tela de provedores."""
    assert not [t for t in Tipo if "nuvem" in t.value.lower() or "cloud" in t.value.lower()]
    assert not [f.name for f in fields(Acao) if "nuvem" in f.name]
    alvo = espaco(ATALHO)
    tentativas: list[dict[str, object]] = [
        {"tipo": "definirModoDeEscuta", "escuta": "palavra", "nuvem_ligada": ["asr-groq"]},
        {"tipo": "definirModoDeEscuta", "escuta": "palavra", "dados": {"nuvem": True}},
        {"tipo": "createWidget", "componente": "relogio", "nuvem_ligada": ["asr-groq"]},
        {"tipo": "setWorkspaceMode", "modo": "pesquisa", "asr": "asr-groq-turbo"},
    ]
    for bruto in tentativas:
        resultado = alvo.propor(bruto)
        assert resultado.aceita is False, bruto
    assert alvo.escuta is not None and alvo.escuta.modo is ATALHO


def test_a_ia_nao_escreve_o_proprio_sim() -> None:
    """Antes, `widget="confirmado:…"` numa proposta pulava a confirmação de componente sensível."""
    alvo = Workspace()
    resultado = alvo.propor(
        {"tipo": "createWidget", "componente": "terminal", "widget": "confirmado:1"}
    )
    assert resultado.pendente is True, "a IA confirmou a si mesma"
    assert not alvo.widgets
