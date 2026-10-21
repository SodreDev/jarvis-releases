"""Cartão F1-06: ASR incremental, coalescing e a atribuição CC-BY como portão."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from tools.license_gate import conferir_atribuicao, inventariar_modelos

from jarvis.agentd.asr import (
    ESTABILIDADE_MINIMA,
    MotorDeAsr,
    MotorDeReferencia,
    MotorWhisper,
    TranscritorIncremental,
)
from jarvis.agentd.percepcao import Percepcao, Transcritor
from jarvis.audio_io.aec import quadros_de
from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.barramento.envelope import Prioridade, Tipo
from jarvis.barramento.epoch import DonoDoEpoch
from jarvis.barramento.fila import FilaDePrioridade, chave_de_coalescing
from jarvis.corpus.metricas import acordo_de_prefixo, cer, wer
from jarvis.ui.sobre import atribuicoes, texto_sobre

RAIZ = Path(__file__).resolve().parents[3]
TEXTO = "abre a pasta de fotos na área de trabalho"


def audio_de(ms: float) -> bytes:
    """Áudio qualquer com a duração pedida: o oráculo olha a duração, não o conteúdo."""
    return de_int16([0] * int(TAXA_PADRAO * ms / 1000))


def transcritor_de_referencia(duracao_ms: float = 1000.0) -> TranscritorIncremental:
    return TranscritorIncremental(
        motor=MotorDeReferencia(texto=TEXTO, duracao_ms=duracao_ms), passo_ms=200.0
    )


def test_o_oraculo_devolve_o_texto_na_proporcao_do_audio_ouvido() -> None:
    motor = MotorDeReferencia(texto=TEXTO, duracao_ms=1000.0)

    assert motor.transcrever(audio_de(0))[0] == ""
    # 9 palavras: metade do áudio ⇒ as 4 primeiras (round(4,5) = 4).
    assert motor.transcrever(audio_de(500))[0] == "abre a pasta de"
    assert motor.transcrever(audio_de(1000))[0] == TEXTO
    assert motor.transcrever(audio_de(5000))[0] == TEXTO, "não passa do texto inteiro"
    assert isinstance(motor, MotorDeAsr)


def test_o_parcial_sai_por_passo_e_a_estabilidade_e_medida() -> None:
    transcritor = transcritor_de_referencia()
    transcritor.comecar(session_id="0193f0a0-0000-7000-8000-000000000000", epoch=1)

    eventos = [e for q in quadros_de(audio_de(1000)) for e in transcritor.ouvir(q)]

    assert [e.type for e in eventos] == [Tipo.PARTIAL_TRANSCRIPT] * len(eventos)
    assert len(eventos) >= 4, "um parcial por passo de 200 ms"
    assert all(e.priority is Prioridade.P1 for e in eventos)
    assert all(e.payload["lang"] == "pt-BR" for e in eventos)
    # A janela cresce: o texto nunca encurta, e a estabilidade é o acordo com o passo anterior.
    textos = [str(e.payload["text"]) for e in eventos]
    assert textos == sorted(textos, key=len)
    assert eventos[-1].payload["stability"] > 0.0


def test_estabilidade_de_1_quando_a_hipotese_so_cresce() -> None:
    assert acordo_de_prefixo("abre a pasta", "abre a pasta de fotos") < 1.0
    assert acordo_de_prefixo("abre a pasta de fotos", "abre a pasta de fotos") == 1.0


def test_utilizavel_tem_limiar_escrito_antes_de_medir() -> None:
    """Aceite (b): mudar o limiar depois de ver o resultado seria escolher o número."""
    assert ESTABILIDADE_MINIMA == 0.6
    transcritor = transcritor_de_referencia()
    transcritor.comecar(session_id="0193f0a0-0000-7000-8000-000000000000", epoch=1)
    for quadro in quadros_de(audio_de(1200)):
        transcritor.ouvir(quadro)

    primeiro = transcritor.primeiro_utilizavel_ms()

    assert primeiro is not None
    assert any(p.utilizavel for p in transcritor.passos)
    assert all(p.estabilidade >= ESTABILIDADE_MINIMA for p in transcritor.passos if p.utilizavel)


def test_o_final_carrega_confianca() -> None:
    transcritor = transcritor_de_referencia()
    transcritor.comecar(session_id="0193f0a0-0000-7000-8000-000000000000", epoch=2)
    for quadro in quadros_de(audio_de(1000)):
        transcritor.ouvir(quadro)

    finais = transcritor.fechar()

    assert len(finais) == 1
    assert finais[0].type is Tipo.FINAL_TRANSCRIPT
    assert finais[0].payload["text"] == TEXTO
    assert 0.0 <= finais[0].payload["confidence"] <= 1.0
    assert finais[0].epoch == 2


def test_sem_audio_nenhum_evento_e_inventado() -> None:
    transcritor = transcritor_de_referencia()
    transcritor.comecar(session_id="0193f0a0-0000-7000-8000-000000000000", epoch=1)

    assert transcritor.fechar() == []


def test_dez_parciais_em_200_ms_viram_uma_revisao_de_estado(sessao: str) -> None:
    """Aceite (c): o coalescing é do barramento, e o `s2` reage uma vez (§3.4)."""
    from jarvis.s2.__main__ import reagir

    transcritor = transcritor_de_referencia(duracao_ms=200.0)
    transcritor.comecar(session_id=sessao, epoch=1)
    transcritor.passo_ms = 20.0  # um parcial por quadro, para ter dez em 200 ms

    parciais = [e for q in quadros_de(audio_de(200)) for e in transcritor.ouvir(q)]
    assert len(parciais) == 10

    fila = FilaDePrioridade()
    for parcial in parciais:
        fila.publicar(parcial)

    assert len({chave_de_coalescing(p) for p in parciais}) == 1, "mesma hipótese, mesma chave"
    sobreviventes = []
    while (evento := fila.retirar()) is not None:
        sobreviventes.append(evento)
    assert len(sobreviventes) == 1, "dez hipóteses sobre o mesmo instante são uma hipótese"

    class ProcessoFalso:
        session_id = sessao
        epoch = 1

    revisoes = reagir(ProcessoFalso(), sobreviventes[0], "aceitar")  # type: ignore[arg-type]
    assert [e.type for e in revisoes] == [Tipo.STATE_REVISION]
    assert revisoes[0].payload["fala_ouvida"] == sobreviventes[0].payload["text"]


def test_o_transcritor_cumpre_o_encaixe_da_percepcao(sessao: str) -> None:
    """A ordem da regra 1 continua valendo com o ASR de verdade no lugar."""
    transcritor = transcritor_de_referencia()
    percepcao = Percepcao(dono=DonoDoEpoch(session_id=sessao), transcritor=transcritor)
    from tests.fabricas import evento

    eventos = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True), 1)

    assert isinstance(transcritor, Transcritor)
    assert [e.type for e in eventos] == [Tipo.CANCEL], "sem áudio ainda, só o cancelamento"
    assert transcritor.epoch == 1


def test_wer_e_cer_contam_o_que_dizem() -> None:
    assert wer(TEXTO, TEXTO).taxa == 0.0
    assert wer("abre a pasta", "abre a casa").taxa == pytest.approx(1 / 3)
    assert cer("país", "pais").taxa == pytest.approx(0.25), "acento conta: é pt-BR"


# --- atribuição CC-BY (aceite (d)) ---------------------------------------------------
def test_a_tela_sobre_lista_as_atribuicoes_obrigatorias() -> None:
    texto = texto_sobre()

    assert "Apache-2.0" in texto
    for item in atribuicoes():
        assert item.id in texto


def test_a_atribuicao_esta_nos_tres_lugares_do_produto() -> None:
    assert conferir_atribuicao(inventariar_modelos()) == []
    obrigados = [m.nome for m in inventariar_modelos() if m.licenca == "CC-BY-4.0"]
    assert obrigados, "o cartão F1-06 registra parakeet CC-BY: a lista não pode estar vazia"


def test_apagar_a_linha_do_notice_quebra_a_porta(tmp_path: Path) -> None:
    """Aceite (d), em teste: é isto que o CI roda."""
    notice = tmp_path / "NOTICE"
    notice.write_text("sem atribuição nenhuma\n", encoding="utf-8")

    faltando = conferir_atribuicao(inventariar_modelos(), arquivos=(notice,))

    assert faltando
    assert all("NOTICE" in falta for falta in faltando)


def test_a_porta_de_atribuicao_roda_como_processo_e_falha_com_notice_mutilado(
    tmp_path: Path,
) -> None:
    """O portão de verdade: `license_gate.py --verificar-atribuicao` como o CI chama."""
    original = (RAIZ / "NOTICE").read_text(encoding="utf-8")
    mutilado = "\n".join(
        linha for linha in original.splitlines() if "parakeet-tdt-0.6b-v3" not in linha
    )
    reserva = tmp_path / "NOTICE.bak"
    reserva.write_text(original, encoding="utf-8")

    def gate() -> int:
        return subprocess.run(
            [sys.executable, str(RAIZ / "tools" / "license_gate.py"), "--verificar-atribuicao"],
            capture_output=True,
            text=True,
            check=False,
            cwd=RAIZ,
        ).returncode

    assert gate() == 0
    try:
        (RAIZ / "NOTICE").write_text(mutilado + "\n", encoding="utf-8")
        assert gate() == 4, "apagar a linha do NOTICE tem de quebrar o CI"
    finally:
        (RAIZ / "NOTICE").write_text(original, encoding="utf-8")
    assert gate() == 0


def test_o_motor_whisper_declara_modelo_e_licenca_sem_carregar_nada() -> None:
    """Quem publica WER tem de poder dizer com qual modelo e sob qual licença."""
    motor = MotorWhisper(tamanho="small")

    assert motor.modelo == "openai/whisper-small"
    assert motor.licenca == "Apache-2.0"
    assert motor.nome == "faster-whisper@small"


def test_a_dica_do_asr_local_vai_so_como_texto_inicial() -> None:
    """ADR-0043: a dica vai em `initial_prompt` e **não** em `hotwords` — medido com áudio
    sintético, a dica em `hotwords` vazou no ruído ("Jarvis" na respiração) e como texto inicial
    não. A inicial maiúscula já vem de `jarvis.voz.dica` (2026-10-17: "jarvis" não muda a saída)."""
    chamadas: list[dict[str, object]] = []

    class ModeloFalso:
        def transcribe(self, audio: object, **argumentos: object) -> tuple[list[object], None]:
            chamadas.append(argumentos)
            return [], None

    motor = MotorWhisper(dica="Jarvis, Discord, TeamSpeak.")
    motor._modelo = ModeloFalso()
    motor.transcrever(bytes(640))
    assert chamadas[0]["initial_prompt"] == "Jarvis, Discord, TeamSpeak."
    assert "hotwords" not in chamadas[0] or chamadas[0]["hotwords"] is None

    chamadas.clear()
    sem_dica = MotorWhisper()
    sem_dica._modelo = ModeloFalso()
    sem_dica.transcrever(bytes(640))
    assert chamadas[0]["initial_prompt"] is None
