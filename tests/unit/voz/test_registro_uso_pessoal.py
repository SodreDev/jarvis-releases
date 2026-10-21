"""A quinta recusa do portão de motores: uso pessoal sem a declaração do dono (ADR-0039).

O `tts-omnivoice` roda na máquina do dono — nada sai dela —, mas os **pesos** são CC-BY-NC. O
portão de execução o trata como a nuvem: escolher não liga. Só liga com a chave que o próprio
registro nomeia (`omnivoice_uso_pessoal = true`), e campo de licença vazio barra sem saída.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.voz.config import ASR_PADRAO, TTS_PADRAO, Configuracao
from jarvis.voz.interface import Onde
from jarvis.voz.registro import (
    CAMPOS_DE_USO_PESSOAL,
    MotorRecusado,
    conferir,
    exigir_motor,
    motor_registrado,
)

PESSOAL = "tts-omnivoice"

REGISTRO = """
[[motor]]
id = "pessoal-completo"
papel = "tts"
onde = "local"
ligado = false
licenca_do_cliente = "Apache-2.0"
estado = "uso_pessoal"
licenca_dos_pesos = "CC-BY-NC"
uso_comercial = "proibido"
chave_do_aceite = "teste_uso_pessoal"
fonte_dos_pesos = "https://exemplo.invalid/card"
marca_dagua = "não declarada"
fonte = "https://exemplo.invalid/pacote"
data_de_acesso = "2026-10-21"

[[motor]]
id = "pessoal-sem-licenca-dos-pesos"
papel = "tts"
onde = "local"
ligado = false
licenca_do_cliente = "Apache-2.0"
estado = "uso_pessoal"
licenca_dos_pesos = ""
uso_comercial = "proibido"
chave_do_aceite = "teste_uso_pessoal"
fonte_dos_pesos = "https://exemplo.invalid/card"
marca_dagua = "não declarada"
fonte = "https://exemplo.invalid/pacote"
data_de_acesso = "2026-10-21"
"""


@pytest.fixture
def registro(tmp_path: Path) -> Path:
    arquivo = tmp_path / "motores.toml"
    arquivo.write_text(REGISTRO, encoding="utf-8")
    return arquivo


def test_escolher_nao_basta_sem_a_declaracao_do_dono(registro: Path) -> None:
    with pytest.raises(MotorRecusado, match="uso pessoal") as erro:
        exigir_motor("pessoal-completo", arquivo=registro)
    assert "teste_uso_pessoal = true" in str(erro.value), "a recusa diz o que escrever"


def test_a_declaracao_do_dono_liga(registro: Path) -> None:
    motor = exigir_motor(
        "pessoal-completo", arquivo=registro, uso_pessoal_aceito=["pessoal-completo"]
    )
    assert motor.de_uso_pessoal and motor.onde is Onde.LOCAL


def test_declarar_outro_motor_nao_liga_este(registro: Path) -> None:
    with pytest.raises(MotorRecusado, match="uso pessoal"):
        exigir_motor("pessoal-completo", arquivo=registro, uso_pessoal_aceito=["outro"])


def test_ligar_nuvem_ou_aceitar_sem_termos_nao_substitui_a_declaracao(registro: Path) -> None:
    with pytest.raises(MotorRecusado, match="uso pessoal"):
        exigir_motor(
            "pessoal-completo",
            arquivo=registro,
            nuvem_ligada=["pessoal-completo"],
            sem_termos_aceitos=["pessoal-completo"],
        )


def test_licenca_dos_pesos_vazia_barra_mesmo_com_tudo_aceito(registro: Path) -> None:
    """Sem a licença dos pesos não há aviso para mostrar: barra sem saída, como a procedência."""
    with pytest.raises(MotorRecusado, match="licenca_dos_pesos"):
        exigir_motor(
            "pessoal-sem-licenca-dos-pesos",
            arquivo=registro,
            uso_pessoal_aceito=["pessoal-sem-licenca-dos-pesos"],
            sem_termos_aceitos=["pessoal-sem-licenca-dos-pesos"],
        )


def test_o_aviso_e_de_licenca_e_vem_dos_campos(registro: Path) -> None:
    motor = motor_registrado("pessoal-completo", arquivo=registro)
    assert motor is not None
    aviso = motor.frase_de_aviso
    assert aviso == motor.aviso_de_uso_pessoal
    assert aviso.startswith("USO PESSOAL, NÃO COMERCIAL")
    assert "CC-BY-NC" in aviso and "teste_uso_pessoal = true" in aviso
    assert "Clonar voz sem autorização" in aviso
    assert "sai desta máquina" not in aviso, "é aviso de licença, não de rede"


def test_conferir_diz_o_que_falta_e_some_com_a_declaracao(registro: Path) -> None:
    faltas = {f.motor: f.motivo for f in conferir(arquivo=registro)}
    assert "uso pessoal" in faltas["pessoal-completo"]
    depois = {f.motor for f in conferir(arquivo=registro, uso_pessoal_aceito=["pessoal-completo"])}
    assert "pessoal-completo" not in depois


# --- o registro de verdade --------------------------------------------------------------------


def test_o_omnivoice_do_produto_nasce_desligado_e_nunca_e_padrao() -> None:
    motor = motor_registrado(PESSOAL)
    assert motor is not None
    assert motor.de_uso_pessoal and not motor.ligado and motor.onde is Onde.LOCAL
    assert PESSOAL not in {TTS_PADRAO, ASR_PADRAO}
    assert Configuracao().tts == TTS_PADRAO != PESSOAL
    assert not set(motor.campos_vazios) & set(CAMPOS_DE_USO_PESSOAL)
    assert "CC-BY-NC" in motor.licenca_dos_pesos and "Boson" in motor.licenca_dos_pesos
    assert motor.chave_do_aceite == "omnivoice_uso_pessoal"


def test_o_omnivoice_do_produto_recusa_sem_a_declaracao() -> None:
    with pytest.raises(MotorRecusado, match="omnivoice_uso_pessoal = true"):
        exigir_motor(PESSOAL)
    assert exigir_motor(PESSOAL, uso_pessoal_aceito=[PESSOAL]).id == PESSOAL
