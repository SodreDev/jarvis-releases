"""ASR na Groq contra um serviço falso: portão, chave, cancelamento, prazo e degradação.

Nenhum teste aqui fala com a Groq de verdade — `proibir_nuvem_real_em_ci` impede, e há um
teste que prova que impede. Chamada real é do dono, com a chave dele, depois.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.rede import SondaInjetada, ler_degradacao
from jarvis.voz.chaves import VARIAVEL_GROQ, SegredoAusente
from jarvis.voz.groq import SEGUNDOS_MINIMOS_COBRADOS, MotorAsrGroq
from jarvis.voz.interface import Hipotese, MotorDeAsr, Onde, cancelado_por_epoch
from jarvis.voz.nuvem import NuvemRealProibidaEmCI, ServicoRecusou
from jarvis.voz.registro import MotorRecusado
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

MOTOR = "asr-groq-whisper-large-v3-turbo"
SEGREDO = "gsk_chave_de_teste_que_nao_pode_vazar_0123456789"
TEXTO = "anotei a reunião de terça às quinze e trinta"


def ambiente_com_chave() -> dict[str, str]:
    """`CI=1` fica ligado: é o que mantém o teste longe da nuvem de verdade."""
    return {"CI": "1", VARIAVEL_GROQ: SEGREDO}


def audio_de(ms: float) -> bytes:
    return de_int16([0] * int(TAXA_PADRAO * ms / 1000))


def resposta_boa(texto: str = TEXTO, avg_logprob: float = -0.2) -> bytes:
    return json.dumps(
        {
            "text": texto,
            "segments": [{"id": 0, "text": texto, "avg_logprob": avg_logprob}],
        }
    ).encode()


def motor_em(
    servico: ServicoFalso,
    raiz: Path,
    **extras: object,
) -> MotorAsrGroq:
    return MotorAsrGroq(
        raiz=raiz,
        base=servico.base,
        nuvem_ligada=[MOTOR],
        ambiente=ambiente_com_chave(),
        **extras,  # type: ignore[arg-type]
    )


# --- portão: o motor não existe para quem não ligou --------------------------------------


def test_sem_o_interruptor_do_dono_o_motor_nao_abre(tmp_path: Path) -> None:
    motor = MotorAsrGroq(raiz=tmp_path, base="http://127.0.0.1:1", ambiente=ambiente_com_chave())
    with pytest.raises(MotorRecusado, match="desligado"):
        motor.abrir()


def test_o_portao_vem_antes_da_chave(tmp_path: Path) -> None:
    """Pedir chave para um motor que nem roda seria ensinar o dono a exportar por nada."""
    motor = MotorAsrGroq(raiz=tmp_path, base="http://127.0.0.1:1", ambiente={"CI": "1"})
    with pytest.raises(MotorRecusado):
        motor.abrir()


def test_sem_chave_no_ambiente_a_recusa_diz_o_que_exportar(tmp_path: Path) -> None:
    motor = MotorAsrGroq(
        raiz=tmp_path,
        base="http://127.0.0.1:1",
        nuvem_ligada=[MOTOR],
        ambiente={"CI": "1"},
    )
    with pytest.raises(SegredoAusente, match=VARIAVEL_GROQ):
        motor.abrir()


def test_base_que_nao_e_local_e_proibida_sob_ci(tmp_path: Path) -> None:
    """Estrutural: a suíte não tem como falar com a Groq de verdade, nem por configuração."""
    motor = MotorAsrGroq(raiz=tmp_path, nuvem_ligada=[MOTOR], ambiente=ambiente_com_chave())
    with pytest.raises(NuvemRealProibidaEmCI, match="não é local"):
        motor.abrir()


def test_o_motor_satisfaz_a_interface_unica_e_se_declara_de_nuvem(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        motor = motor_em(servico, tmp_path)
        assert isinstance(motor, MotorDeAsr)
        assert motor.onde is Onde.NUVEM
        assert motor.abrir().licenca_do_cliente == "Apache-2.0"


def test_o_aviso_obrigatorio_sai_do_registro(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        motor = motor_em(servico, tmp_path)
        aviso = motor.aviso
        assert "o seu áudio sai desta máquina para Groq" in aviso
        assert "30 dias" in aviso and "ZDR" in aviso


# --- caminho feliz ------------------------------------------------------------------------


def test_transcreve_contra_o_servico_falso(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor = motor_em(servico, tmp_path)
        hipotese = motor.transcrever(audio_de(1200))

        assert isinstance(hipotese, Hipotese)
        assert hipotese.texto == TEXTO
        assert 0.0 < hipotese.confianca <= 1.0
        assert len(servico.pedidos) == 1
        pedido = servico.pedidos[0]
        assert pedido.caminho == "/audio/transcriptions"
        assert pedido.campo("model") == "whisper-large-v3-turbo"
        assert pedido.campo("language") == "pt"
        assert pedido.campo("response_format") == "verbose_json"


def test_a_chave_vai_no_cabecalho_e_em_lugar_nenhum_mais(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor_em(servico, tmp_path).transcrever(audio_de(1200))

        pedido = servico.pedidos[0]
        assert pedido.autorizacao == f"Bearer {SEGREDO}"
        assert SEGREDO not in pedido.caminho
        assert SEGREDO not in pedido.corpo.decode("utf-8", "replace")
        for nome, valor in pedido.cabecalhos.items():
            if nome != "Authorization":
                assert SEGREDO not in valor


def test_o_audio_vai_como_wav_16k_mono_sem_reamostrar(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor_em(servico, tmp_path).transcrever(audio_de(1000))

        corpo = servico.pedidos[0].corpo
        inicio = corpo.find(b"RIFF")
        assert inicio > 0, "o WAV não foi anexado"
        import io
        import wave

        with wave.open(io.BytesIO(corpo[inicio:]), "rb") as arquivo:
            assert arquivo.getframerate() == TAXA_PADRAO
            assert arquivo.getnchannels() == 1
            assert arquivo.getsampwidth() == 2
            assert arquivo.getnframes() == TAXA_PADRAO  # 1 s


def test_resposta_sem_segmento_devolve_confianca_nao_medida(tmp_path: Path) -> None:
    corpo = json.dumps({"text": TEXTO}).encode()
    with ServicoFalso(roteiro=Roteiro(corpo=corpo)) as servico:
        hipotese = motor_em(servico, tmp_path).transcrever(audio_de(1200))
        assert hipotese.texto == TEXTO
        assert hipotese.confianca == 0.0


def test_conta_as_requisicoes_abaixo_do_minimo_cobrado(tmp_path: Path) -> None:
    """A Groq cobra 10 s mesmo para 1,2 s. O dono vê a conta no diagnóstico."""
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor = motor_em(servico, tmp_path)
        motor.transcrever(audio_de(1200))
        assert motor.requisicoes_abaixo_do_minimo == 1

        motor.transcrever(audio_de(SEGUNDOS_MINIMOS_COBRADOS * 1000 + 500))
        assert motor.requisicoes_abaixo_do_minimo == 1


# --- cancelamento: o contrato do F1-09/F1-11 na rede -------------------------------------


def test_epoch_morto_nao_paga_requisicao(tmp_path: Path) -> None:
    """Cancelado antes de abrir o socket: nenhum pedido chega ao serviço."""
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor = motor_em(servico, tmp_path, cancelado=lambda: True)
        hipotese = motor.transcrever(audio_de(1200))

        assert hipotese == Hipotese("", 0.0)
        assert servico.pedidos == []
        assert motor.descartadas_por_cancelamento == 1


def test_cancelamento_por_epoch_usa_o_contrato_da_adr_0002(tmp_path: Path) -> None:
    epoch_atual = 7
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor = motor_em(servico, tmp_path, cancelado=cancelado_por_epoch(lambda: epoch_atual, 7))
        assert motor.transcrever(audio_de(1200)).texto == TEXTO  # epoch vivo

        epoch_atual = 8  # o dono falou por cima: o epoch avançou
        assert motor.transcrever(audio_de(1200)) == Hipotese("", 0.0)
        assert len(servico.pedidos) == 1, "o segundo pedido não devia ter saído"


def test_cancelamento_no_meio_do_corpo_descarta_o_que_chegou(tmp_path: Path) -> None:
    """O pedaço em voo é **descartado**: nada de transcrição pela metade de turno morto."""
    chamadas = {"n": 0}

    def cancelado() -> bool:
        # Vivo até o pedido sair e o corpo começar a chegar; morto na leitura seguinte.
        chamadas["n"] += 1
        return chamadas["n"] > 2

    corpo = resposta_boa(TEXTO + " " + "palavra " * 4000)
    with ServicoFalso(roteiro=Roteiro(corpo=corpo, pedacos=8, pausa_s=0.01)) as servico:
        motor = motor_em(servico, tmp_path, cancelado=cancelado)
        hipotese = motor.transcrever(audio_de(1200))

        assert hipotese == Hipotese("", 0.0), "corpo pela metade não pode virar hipótese"
        assert len(servico.pedidos) == 1, "o pedido saiu: o cancelamento chegou depois"
        assert motor.descartadas_por_cancelamento == 1


# --- degradação: nada pendurado (F1-14) ---------------------------------------------------


def test_servico_fora_declara_degradacao_e_nao_pendura(tmp_path: Path) -> None:
    with ServicoFalso() as servico:
        base = servico.base  # o servidor sai do ar ao fechar o `with`
    motor = MotorAsrGroq(
        raiz=tmp_path,
        base=base,
        nuvem_ligada=[MOTOR],
        ambiente=ambiente_com_chave(),
        prazo_s=2.0,
    )

    assert motor.transcrever(audio_de(1200)) == Hipotese("", 0.0)

    degradacao = ler_degradacao(tmp_path)
    assert degradacao.ativa and degradacao.servico == "Groq"
    assert "botão de falar" in degradacao.frase  # cai para PTT e diz isso
    assert motor.degradado


def test_sonda_apagada_nem_tenta_a_chamada(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        motor = motor_em(servico, tmp_path, sonda=SondaInjetada(ligada=False))
        assert motor.transcrever(audio_de(1200)) == Hipotese("", 0.0)
        assert servico.pedidos == [], "sem rede, não se abre socket por otimismo"


def test_erro_do_servidor_vira_degradacao(tmp_path: Path) -> None:
    with ServicoFalso(roteiro=Roteiro(status=503, corpo=b'{"error":"indisponivel"}')) as servico:
        motor = motor_em(servico, tmp_path)
        assert motor.transcrever(audio_de(1200)) == Hipotese("", 0.0)
        assert ler_degradacao(tmp_path).ativa


def test_chave_invalida_nao_e_confundida_com_falta_de_rede(tmp_path: Path) -> None:
    """401 tem de chegar ao dono como "a sua chave não serve", não como "estou sem internet"."""
    corpo = json.dumps({"error": {"message": f"Invalid API Key: {SEGREDO}"}}).encode()
    with ServicoFalso(roteiro=Roteiro(status=401, corpo=corpo)) as servico:
        motor = motor_em(servico, tmp_path)
        with pytest.raises(ServicoRecusou) as erro:
            motor.transcrever(audio_de(1200))

    assert "confira a chave" in str(erro.value)
    assert SEGREDO not in str(erro.value), "o corpo do serviço repetiu a chave e vazou"
    assert VARIAVEL_GROQ in str(erro.value)
    assert not ler_degradacao(tmp_path).ativa, "recusa do serviço não é queda de rede"


def test_limite_de_taxa_e_degradacao_e_nao_recusa(tmp_path: Path) -> None:
    """429 é "tente mais tarde": cai para PTT em vez de dizer que a chave está errada."""
    with ServicoFalso(roteiro=Roteiro(status=429, corpo=b'{"error":"rate limit"}')) as servico:
        motor = motor_em(servico, tmp_path)
        assert motor.transcrever(audio_de(1200)) == Hipotese("", 0.0)
        assert ler_degradacao(tmp_path).ativa


def test_prazo_nosso_vence_servico_lento(tmp_path: Path) -> None:
    """O prazo é nosso (regra 1 do F1-14): não se espera o `timeout` de ninguém."""
    with ServicoFalso(
        roteiro=Roteiro(corpo=resposta_boa(), atraso_antes_do_cabecalho_s=2.0)
    ) as servico:
        motor = motor_em(servico, tmp_path, prazo_s=0.3)
        assert motor.transcrever(audio_de(1200)) == Hipotese("", 0.0)
        assert ler_degradacao(tmp_path).ativa
