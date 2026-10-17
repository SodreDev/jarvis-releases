"""O detector de endereçamento no laço de escuta contínua (ADR-0029), sem nuvem e sem microfone.

Mesmo banco do `test_app_escuta.py`: WAV no lugar do microfone, ASR e VAD falsos; o classificador
é o de mentira, com respostas roteirizadas por frase.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from jarvis.decisao.enderecamento import DetectorDeEnderecamento
from jarvis.decisao.fake import ClassificadorFalso, Roteiro, endereco
from jarvis.decisao.interface import Pergunta, Resposta
from jarvis.voz.escuta import ModoDeEscuta
from tests.unit.voz.test_app_escuta import VadComRajadas, _app

DUAS_FALAS = ((1, 15), (70, 90))


def _por_frase(p_por_frase: Mapping[str, float], intencao: str = "resposta") -> Roteiro:
    def roteiro(
        estado: dict[str, str], perguntas: Mapping[str, Pergunta]
    ) -> Mapping[str, Resposta]:
        return endereco(p_por_frase[estado["fala"]], intencao)(estado, perguntas)

    return roteiro


def test_na_continua_so_a_fala_endereçada_vira_turno_e_a_outra_nao_deixa_o_texto(
    tmp_path: Path,
) -> None:
    app, linhas = _app(
        tmp_path, ModoDeEscuta.CONTINUA, "amor, cadê a chave do carro", "que horas são"
    )
    app.detector = DetectorDeEnderecamento(
        classificador=ClassificadorFalso(
            roteiro=_por_frase({"amor, cadê a chave do carro": 0.04, "que horas são": 0.96})
        )
    )
    app.rodar_audio(vad=VadComRajadas(*DUAS_FALAS))

    assert [t.falou for t in app.turnos] == ["que horas são"]
    assert not any("chave do carro" in linha for linha in linhas), "a fala alheia vazou na tela"
    assert any("endereçamento: resposta" in linha for linha in linhas)
    assert app.detector.nao_era_comigo == 1 and app.detector.enderecadas == 1


def test_na_duvida_nao_age_e_o_classificador_fora_do_ar_e_dito_uma_vez(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.CONTINUA, "uma", "duas")
    app.detector = DetectorDeEnderecamento(
        classificador=ClassificadorFalso(roteiro=endereco(0.99), falhar_com="503 do serviço")
    )
    app.rodar_audio(vad=VadComRajadas(*DUAS_FALAS))

    assert app.turnos == []
    avisos = [a for a in app.dados_dos_avisos()["avisos"] if "endereçamento" in a["origem"]]
    assert len(avisos) == 1 and "não ajo" in avisos[0]["resumo"]
    assert app.detector.falhas == 2


def test_fora_da_continua_o_detector_nem_e_consultado(tmp_path: Path) -> None:
    classificador = ClassificadorFalso(roteiro=endereco(0.0))
    app, _ = _app(tmp_path, ModoDeEscuta.PALAVRA, "jarvis, que horas são")
    app.detector = DetectorDeEnderecamento(classificador=classificador)
    app.rodar_audio(vad=VadComRajadas((1, 15)))

    assert [t.falou for t in app.turnos] == ["que horas são"]
    assert classificador.chamadas == [], "palavra de ativação e atalho não gastam consulta"


def test_sem_detector_a_continua_se_comporta_como_antes(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, ModoDeEscuta.CONTINUA, "qualquer coisa que o microfone ouvir")
    assert app.detector is None
    app.rodar_audio(vad=VadComRajadas((1, 15)))

    assert [t.falou for t in app.turnos] == ["qualquer coisa que o microfone ouvir"]


def test_escolher_o_motor_sem_ligar_a_nuvem_nao_ativa_e_diz_por_que(tmp_path: Path) -> None:
    app, linhas = _app(tmp_path, ModoDeEscuta.CONTINUA, "oi")
    app.configuracao = app.configuracao.com(enderecamento="decisao-jev-openrouter")
    app.ambiente = {"JARVIS_AUDIO_BACKEND": "arquivo", "CI": "1"}

    app.abrir()

    assert app.detector is None
    assert any("não está ativo" in linha and "desligado" in linha for linha in linhas)
