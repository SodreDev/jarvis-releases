"""O registro de provedores de modelo passa pelo mesmo portão dos motores de voz (ADR-0017/0056)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.licencas import Categoria
from jarvis.provedores.interface import ESFORCOS, ProvedorDeModelos
from jarvis.provedores.registro import (
    CLAUDE_CLI,
    COMPATIVEL_NUVEM,
    ECO,
    PAPEL,
    abrir,
    classe_de,
    exigir,
    ler_provedores,
    ler_regras,
)
from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, validar
from jarvis.voz.interface import Onde
from jarvis.voz.registro import Motor, MotorRecusado, ler_motores

PROVEDORES = ler_provedores()


def test_o_registro_tem_o_eco_e_a_cli_do_claude() -> None:
    ids = [p.id for p in PROVEDORES]
    assert ids[:2] == [ECO, CLAUDE_CLI]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("provedor", PROVEDORES, ids=lambda p: p.id)
def test_cada_provedor_tem_procedencia_licenca_e_termos(provedor: Motor) -> None:
    assert provedor.papel == PAPEL
    assert provedor.id.startswith("conversa-")
    assert provedor.categoria_da_licenca is Categoria.PERMISSIVA
    if provedor.id == COMPATIVEL_NUVEM:
        # Os termos dependem do serviço que o dono escolher: vazios de propósito (política 4).
        assert set(provedor.campos_vazios) == {
            "uso_comercial",
            "retencao_declarada",
            "treina_com_entrada",
            "dono_da_saida",
        }
    else:
        assert provedor.campos_vazios == ()  # procedência, termos (nuvem), lista com fonte e data
    assert not provedor.ligado, "nuvem nasce desligada; local não precisa do interruptor"
    assert isinstance(classe_de(provedor), type)


@pytest.mark.parametrize("provedor", PROVEDORES, ids=lambda p: p.id)
def test_cada_provedor_abre_para_listar_sem_o_interruptor(provedor: Motor, tmp_path: Path) -> None:
    aberto = abrir(provedor.id, ambiente={}, pasta_de_trabalho=tmp_path)
    assert isinstance(aberto, ProvedorDeModelos)
    assert aberto.id == provedor.id
    assert aberto.onde is provedor.onde


def test_regras_de_capacidade_tem_procedencia_e_provedor_registrado() -> None:
    ids = {p.id for p in PROVEDORES}
    regras = ler_regras()
    assert regras
    for regra in regras:
        assert regra.provedor in ids
        assert regra.fonte.startswith("https://") and len(regra.data) == 10
        assert regra.capacidades.esforcos is None or set(regra.capacidades.esforcos) <= set(
            ESFORCOS
        )


def test_chamar_nuvem_desligada_recusa_e_diz_o_que_sai() -> None:
    with pytest.raises(MotorRecusado, match="desligado") as erro:
        exigir(CLAUDE_CLI, ligados=())
    assert "a conversa" in str(erro.value)
    assert exigir(CLAUDE_CLI, ligados=(CLAUDE_CLI,)).id == CLAUDE_CLI
    assert exigir(ECO, ligados=()).onde is Onde.LOCAL


def test_a_configuracao_aceita_ligar_provedor_de_modelo_e_recusa_o_local() -> None:
    validar(Configuracao(nuvem_ligada=(CLAUDE_CLI,)))
    with pytest.raises(ConfiguracaoInvalida, match="local"):
        validar(Configuracao(nuvem_ligada=(ECO,)))
    with pytest.raises(ConfiguracaoInvalida, match="não está no registro"):
        validar(Configuracao(nuvem_ligada=("conversa-inventado",)))


def test_ids_nao_colidem_com_os_motores_de_voz() -> None:
    assert not {p.id for p in PROVEDORES} & {m.id for m in ler_motores()}


def test_compativel_de_nuvem_so_chama_com_o_aceite_dos_termos() -> None:
    with pytest.raises(MotorRecusado, match="campo obrigatório vazio"):
        exigir(COMPATIVEL_NUVEM, ligados=(COMPATIVEL_NUVEM,))
    motor = exigir(COMPATIVEL_NUVEM, ligados=(COMPATIVEL_NUVEM,), sem_termos=(COMPATIVEL_NUVEM,))
    assert motor.frase_de_aviso.startswith("ATENÇÃO: este serviço não publica termos")
