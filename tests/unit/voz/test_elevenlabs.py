"""TTS na ElevenLabs contra o serviço falso: portão, cabeçalho próprio, PCM e cancelamento."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.rede import SondaInjetada, ler_degradacao
from jarvis.voz.chaves import VARIAVEL_ELEVENLABS, SegredoAusente
from jarvis.voz.elevenlabs import CABECALHO_DA_CHAVE, FORMATO, MotorTtsElevenLabs
from jarvis.voz.interface import MotorDeTts, Onde
from jarvis.voz.nuvem import NuvemRealProibidaEmCI, ServicoRecusou
from jarvis.voz.registro import MotorRecusado
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

MOTOR = "tts-elevenlabs"
SEGREDO = "sk_chave_de_teste_que_nao_pode_vazar_0123456789"
VOZ = "voz-do-dono-123"
TEXTO = "Quer que eu avise o João agora?"


def ambiente_com_chave() -> dict[str, str]:
    return {"CI": "1", VARIAVEL_ELEVENLABS: SEGREDO}


def pcm(ms: float) -> bytes:
    return de_int16([1000] * int(TAXA_PADRAO * ms / 1000))


def motor_em(servico: ServicoFalso, raiz: Path, **extras: object) -> MotorTtsElevenLabs:
    return MotorTtsElevenLabs(
        raiz=raiz,
        voz=VOZ,
        base=servico.base,
        nuvem_ligada=[MOTOR],
        ambiente=ambiente_com_chave(),
        **extras,  # type: ignore[arg-type]
    )


def test_sem_o_interruptor_do_dono_nao_abre(tmp_path: Path) -> None:
    motor = MotorTtsElevenLabs(
        raiz=tmp_path, voz=VOZ, base="http://127.0.0.1:1", ambiente=ambiente_com_chave()
    )
    with pytest.raises(MotorRecusado, match="desligado"):
        motor.abrir()


def test_sem_chave_a_recusa_diz_o_que_exportar(tmp_path: Path) -> None:
    motor = MotorTtsElevenLabs(
        raiz=tmp_path,
        voz=VOZ,
        base="http://127.0.0.1:1",
        nuvem_ligada=[MOTOR],
        ambiente={"CI": "1"},
    )
    with pytest.raises(SegredoAusente, match=VARIAVEL_ELEVENLABS):
        motor.abrir()


def test_sem_voz_escolhida_recusa_em_vez_de_inventar(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        motor = MotorTtsElevenLabs(
            raiz=tmp_path,
            voz="",
            base=servico.base,
            nuvem_ligada=[MOTOR],
            ambiente=ambiente_com_chave(),
        )
        with pytest.raises(MotorRecusado, match="sem voz escolhida"):
            motor.abrir()


def test_base_que_nao_e_local_e_proibida_sob_ci(tmp_path: Path) -> None:
    motor = MotorTtsElevenLabs(
        raiz=tmp_path, voz=VOZ, nuvem_ligada=[MOTOR], ambiente=ambiente_com_chave()
    )
    with pytest.raises(NuvemRealProibidaEmCI):
        motor.abrir()


def test_satisfaz_a_interface_e_se_declara_de_nuvem(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        motor = motor_em(servico, tmp_path)
        assert isinstance(motor, MotorDeTts)
        assert motor.onde is Onde.NUVEM
        assert motor.abrir().licenca_do_cliente == "Apache-2.0"


def test_o_aviso_diz_que_o_texto_sai_e_o_que_a_retencao_declara(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        aviso = motor_em(servico, tmp_path).aviso
        assert "o texto que o Jarvis vai falar sai desta máquina para ElevenLabs" in aviso
        assert "history preservation" in aviso
        assert "non-commercial" in aviso  # o que o plano gratuito proíbe


def test_sintetiza_pcm_e_monta_o_pedido_como_o_servico_espera(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=pcm(500), tipo="audio/pcm")) as servico:
        motor = motor_em(servico, tmp_path)
        amostras = motor.sintetizar(TEXTO)

        assert amostras == pcm(500)
        assert len(amostras) % 2 == 0
        pedido = servico.pedidos[0]
        assert pedido.caminho == f"/v1/text-to-speech/{VOZ}?output_format={FORMATO}"
        assert json.loads(pedido.corpo) == {
            "text": TEXTO,
            "model_id": "eleven_multilingual_v2",
        }
        assert motor.caracteres_enviados == len(TEXTO)


def test_a_chave_vai_no_cabecalho_proprio_e_sem_prefixo(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=pcm(100))) as servico:
        motor_em(servico, tmp_path).sintetizar(TEXTO)

        pedido = servico.pedidos[0]
        assert pedido.cabecalho(CABECALHO_DA_CHAVE) == SEGREDO
        assert not pedido.tem_cabecalho("Authorization")
        assert SEGREDO not in pedido.caminho
        assert SEGREDO not in pedido.corpo.decode("utf-8", "replace")


def test_retencao_zero_so_vai_quando_o_dono_pede(tmp_path: Path) -> None:
    """`enable_logging=false` é Enterprise: mandar por conta própria faria o serviço recusar."""
    with ServicoFalso(roteiro=Roteiro(corpo=pcm(100))) as servico:
        motor_em(servico, tmp_path).sintetizar(TEXTO)
        assert "enable_logging" not in servico.pedidos[0].caminho

    with ServicoFalso(roteiro=Roteiro(corpo=pcm(100))) as servico:
        motor_em(servico, tmp_path, retencao_zero=True).sintetizar(TEXTO)
        assert "enable_logging=false" in servico.pedidos[0].caminho


def test_corpo_que_nao_e_pcm_e_recusado_em_vez_de_virar_chiado(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=b"isto nao e pcm 16")) as servico:
        with pytest.raises(ServicoRecusou, match="não é PCM16"):
            motor_em(servico, tmp_path).sintetizar(TEXTO)
        assert not ler_degradacao(tmp_path).ativa, "corpo torto não é queda de rede"


def test_epoch_morto_nao_manda_o_texto_para_fora(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=pcm(100))) as servico:
        motor = motor_em(servico, tmp_path, cancelado=lambda: True)
        assert motor.sintetizar(TEXTO) == b""
        assert servico.pedidos == []
        assert motor.caracteres_enviados == 0, "texto de epoch morto não sai da máquina"


def test_cancelamento_no_meio_do_corpo_descarta_o_audio(tmp_path: Path) -> None:
    chamadas = {"n": 0}

    def cancelado() -> bool:
        chamadas["n"] += 1
        return chamadas["n"] > 2

    with ServicoFalso(roteiro=Roteiro(corpo=pcm(4000), pedacos=8, pausa_s=0.01)) as servico:
        motor = motor_em(servico, tmp_path, cancelado=cancelado)
        assert motor.sintetizar(TEXTO) == b""
        assert len(servico.pedidos) == 1
        assert motor.descartadas_por_cancelamento == 1


def test_servico_fora_declara_degradacao(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        base = servico.base
    motor = MotorTtsElevenLabs(
        raiz=tmp_path,
        voz=VOZ,
        base=base,
        nuvem_ligada=[MOTOR],
        ambiente=ambiente_com_chave(),
        prazo_s=2.0,
    )

    assert motor.sintetizar(TEXTO) == b""
    assert ler_degradacao(tmp_path).servico == "ElevenLabs"
    assert motor.degradado


def test_o_que_caiu_numa_sessao_nao_cala_a_fala_de_mesmo_numero_da_seguinte(
    tmp_path: Path,
) -> None:
    """Os descartados da regra 5 ficam no disco entre sessões: o id não pode ser só o contador
    (2026-10-29), senão a 1ª fala de toda sessão nova sai muda porque a 1ª de ontem caiu."""
    with ServicoFalso(roteiro=Roteiro(status=503, corpo=b'{"error":"fora"}')) as servico:
        assert motor_em(servico, tmp_path).sintetizar(TEXTO) == b""
    assert ler_degradacao(tmp_path).descartados

    with ServicoFalso(roteiro=Roteiro(corpo=pcm(100), tipo="audio/pcm")) as servico:
        assert motor_em(servico, tmp_path).sintetizar(TEXTO) == pcm(100)
        assert len(servico.pedidos) == 1


def test_sonda_apagada_nem_tenta(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=pcm(100))) as servico:
        motor = motor_em(servico, tmp_path, sonda=SondaInjetada(ligada=False))
        assert motor.sintetizar(TEXTO) == b""
        assert servico.pedidos == []


def test_chave_invalida_sobe_como_recusa_e_nao_como_queda(tmp_path: Path) -> None:
    corpo = json.dumps({"detail": {"message": f"invalid key {SEGREDO}"}}).encode()
    with (
        ServicoFalso(roteiro=Roteiro(status=401, corpo=corpo)) as servico,
        pytest.raises(ServicoRecusou) as erro,
    ):
        motor_em(servico, tmp_path).sintetizar(TEXTO)

    assert SEGREDO not in str(erro.value)
    assert not ler_degradacao(tmp_path).ativa
