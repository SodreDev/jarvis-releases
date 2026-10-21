"""Interromper o Jarvis por voz (ADR-0040): o portão de eco, a vigia e o laço inteiro.

Tudo com áudio sintético (`jarvis.audio_io.sintese`) e ASR falso — nenhum microfone, nenhum
alto-falante. O eco é uma cópia atrasada e atenuada da fala do próprio Jarvis; a "TV" é fala
simulada mais baixa, presente antes e durante a fala dele; o dono é fala simulada mais alta, perto
do microfone. O que isto **não** prova está na ADR: sala de verdade, AEC de verdade, voz de verdade.
"""

from __future__ import annotations

import json
import wave
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path
from random import Random

from jarvis.audio_io.aec import quadros_de
from jarvis.audio_io.quadro import BYTES_POR_QUADRO, TAXA_PADRAO, Quadro
from jarvis.audio_io.sintese import aplicar_ganho_db, eco, fala_simulada, misturar, silencio
from jarvis.relogio import RelogioFalso
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.pendencias import Espera
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao, ler
from jarvis.voz.escuta import ModoDeEscuta
from jarvis.voz.interface import Hipotese, Onde
from jarvis.voz.interrupcao import (
    Acao,
    Motivo,
    PortaoDeEco,
    VigiaDeInterrupcao,
    eh_ordem_de_parar,
    em_linha,
    so_ordem_de_parar,
)
from jarvis.voz.palavra import DetectorDePalavra

LONGA = (
    "Era uma vez um reino muito distante, onde as montanhas tocavam as nuvens e os rios corriam "
    "devagar entre as pedras antigas. Lá vivia uma inventora que construía máquinas de vento, "
    "relógios de água e lanternas que acendiam sozinhas quando a noite chegava sem avisar ninguém. "
    "Todos os dias ela subia a colina mais alta para medir o tempo e anotar o caminho das aves."
)


def _fala(ms: float, semente: int, pico: float = 0.35, f0: float = 110.0) -> bytes:
    return fala_simulada(ms, aleatorio=Random(semente), pico=pico, f0_hz=f0)


def _quadros(amostras: bytes) -> list[Quadro]:
    return quadros_de(amostras)


def _junto(referencia: bytes, microfone: bytes) -> list[tuple[bytes, Quadro]]:
    """Quadro a quadro: o que foi para o alto-falante e o que o microfone ouviu no mesmo tique."""
    ref = _quadros(referencia)
    mic = _quadros(microfone)
    return [(r.amostras, m) for r, m in zip(ref, mic, strict=False)]


# --- o portão de eco ------------------------------------------------------------------------------
def test_o_eco_do_proprio_jarvis_nao_passa_no_portao() -> None:
    jarvis = _fala(4000, 1)
    microfone = eco(jarvis, atraso_ms=60, ganho_db=-12)[: len(jarvis)]
    portao = PortaoDeEco()

    passaram = 0
    for ref, quadro in _junto(jarvis, microfone):
        portao.referencia(ref)
        passaram += portao.ver(quadro)

    assert passaram == 0, f"{passaram} quadros de eco passaram como fala do dono"
    assert 8.0 < portao.perda_db < 20.0, portao.perda_db  # aprendeu ~12 dB do caminho


def test_o_dono_falando_por_cima_do_eco_passa() -> None:
    jarvis = _fala(4000, 1)
    dono = silencio(2000) + _fala(1500, 7, pico=0.5, f0=180.0)
    microfone = misturar(eco(jarvis, atraso_ms=60, ganho_db=-12)[: len(jarvis)], dono)
    portao = PortaoDeEco()

    resultados = []
    for ref, quadro in _junto(jarvis, microfone):
        portao.referencia(ref)
        resultados.append(portao.ver(quadro))

    antes = sum(resultados[:100])  # 0–2 s: só o eco
    durante = sum(resultados[100:175])  # 2–3,5 s: o dono por cima
    assert antes == 0
    assert durante >= 50, f"só {durante} de 75 quadros do dono passaram"


def test_a_tv_ligada_antes_e_durante_a_fala_nao_passa() -> None:
    tv = aplicar_ganho_db(_fala(9000, 3, f0=140.0), -20)
    portao = PortaoDeEco()
    for quadro in _quadros(tv[: 5 * TAXA_PADRAO * 2]):  # 5 s com o Jarvis calado: o ambiente
        portao.ver(quadro)
    jarvis = _fala(4000, 1)
    microfone = misturar(eco(jarvis, atraso_ms=60, ganho_db=-12)[: len(jarvis)], tv[5 * 32000 :])

    passaram = 0
    for ref, quadro in _junto(jarvis, microfone):
        portao.referencia(ref)
        passaram += portao.ver(quadro)

    assert portao.ambiente_db > -60.0  # mediu a TV
    assert passaram == 0, f"{passaram} quadros da TV passaram como o dono"


def test_quando_a_transcricao_diz_que_era_eco_o_portao_fica_mais_exigente() -> None:
    portao = PortaoDeEco(perda_db=20.0)
    portao.era_o_eco()
    assert portao.perda_db == 17.0


# --- a vigia -------------------------------------------------------------------------------------
class AsrDeTexto:
    """Devolve o texto roteirizado a cada chamada (o último se repete)."""

    def __init__(self, *textos: str) -> None:
        self.textos = list(textos)
        self.chamadas = 0

    def __call__(self, amostras: bytes) -> str:
        assert amostras, "a vigia mandou trecho vazio ao ASR"
        self.chamadas += 1
        return self.textos[min(self.chamadas, len(self.textos)) - 1]


def _vigia(
    modo: ModoDeEscuta,
    asr: Callable[[bytes], str],
    *,
    enderecada: Callable[[str], bool] | None = None,
    enviar: Callable[[Callable[[], object]], Future[object]] = em_linha,
) -> VigiaDeInterrupcao:
    vigia = VigiaDeInterrupcao(
        transcrever=asr,
        palavra=DetectorDePalavra(),
        enderecada=enderecada,
        enviar=enviar,
        portao=PortaoDeEco(perda_db=40.0),  # sem eco na sala de teste: o caminho já aprendido
    )
    vigia.comecar(modo)
    return vigia


def _rodar(
    vigia: VigiaDeInterrupcao,
    *,
    fala_do_dono_ms: float,
    depois_ms: float = 1200.0,
    cortes: list[bytes] | None = None,
) -> list[Acao]:
    """1 s do Jarvis falando com o microfone quieto, o dono por cima, e silêncio depois. Para no
    corte, como o laço (o epoch morre e a fala acaba ali); o trecho do corte vai para `cortes`."""
    jarvis = _fala(1000 + fala_do_dono_ms + depois_ms, 1)
    dono = silencio(1000) + _fala(fala_do_dono_ms, 7, pico=0.5, f0=180.0) + silencio(depois_ms)
    vigia.falando("era uma vez um reino muito distante")
    acoes = []
    for ref, quadro in _junto(jarvis, dono):
        vigia.portao.referencia(ref)
        acoes.append(vigia.ouvir(quadro, fala_no_vad=quadro.energia_db > -45.0))
        if acoes[-1] is Acao.CORTAR:
            if cortes is not None:
                cortes.append(vigia.audio_do_corte())
            break
    return acoes


def test_na_palavra_o_nome_dito_por_cima_corta_e_o_trecho_vira_o_comeco_do_turno() -> None:
    asr = AsrDeTexto("jarvis que horas são")
    vigia = _vigia(ModoDeEscuta.PALAVRA, asr)
    cortes: list[bytes] = []

    acoes = _rodar(vigia, fala_do_dono_ms=800, cortes=cortes)

    assert Acao.CORTAR in acoes
    assert Acao.PAUSAR not in acoes, "na palavra o Jarvis não pausa à toa: só o nome corta"
    corte = acoes.index(Acao.CORTAR)
    assert corte == 50 + 11, f"cortou no quadro {corte}: 240 ms depois de o dono começar"
    # Os 400 ms de antes e os 240 ms de fala: o começo da chamada vai para o turno novo.
    assert cortes == [cortes[0]] and len(cortes[0]) == (20 + 12) * BYTES_POR_QUADRO
    assert vigia.decisoes[-1].motivo is Motivo.PALAVRA_DE_ATIVACAO


def test_na_palavra_fala_sem_o_nome_nao_corta_nem_pausa() -> None:
    vigia = _vigia(ModoDeEscuta.PALAVRA, AsrDeTexto("que horas são agora"))

    acoes = _rodar(vigia, fala_do_dono_ms=800)

    assert Acao.CORTAR not in acoes and Acao.PAUSAR not in acoes
    assert vigia.decisoes[-1].motivo is Motivo.SEM_CHAMADA


def test_o_eco_do_proprio_nome_dito_pelo_jarvis_nao_corta() -> None:
    vigia = _vigia(ModoDeEscuta.PALAVRA, AsrDeTexto("eu sou o jarvis seu assistente"))
    vigia.falando("eu sou o Jarvis, seu assistente de voz")
    perda_antes = vigia.portao.perda_db

    acoes = _rodar(vigia, fala_do_dono_ms=800)

    assert Acao.CORTAR not in acoes
    eco = next(i for i, d in enumerate(vigia.decisoes) if d.motivo is Motivo.ECO_DO_JARVIS)
    assert eco == 0, "a primeira leitura já dizia que era o eco"
    assert perda_antes > 0


def test_na_continua_pausa_na_hora_e_sem_o_detector_retoma_quando_nao_e_ordem() -> None:
    vigia = _vigia(ModoDeEscuta.CONTINUA, AsrDeTexto("e amanhã como vai ficar o tempo"))

    acoes = _rodar(vigia, fala_do_dono_ms=900)

    pausa = acoes.index(Acao.PAUSAR)
    assert 50 + 11 <= pausa <= 50 + 14, "pausou tarde: o dono falou e o Jarvis seguiu falando"
    assert Acao.RETOMAR in acoes[pausa:]
    assert Acao.CORTAR not in acoes
    assert vigia.decisoes[-1].motivo is Motivo.SEM_CHAMADA


def test_na_continua_a_ordem_de_parar_corta_sem_a_palavra() -> None:
    vigia = _vigia(ModoDeEscuta.CONTINUA, AsrDeTexto("para"))

    acoes = _rodar(vigia, fala_do_dono_ms=500)

    assert Acao.CORTAR in acoes
    assert vigia.decisoes[-1].motivo is Motivo.ORDEM_DE_PARAR


def test_na_continua_com_o_detector_a_fala_dirigida_corta_e_a_alheia_retoma() -> None:
    perguntadas: list[str] = []

    def enderecada(texto: str) -> bool:
        perguntadas.append(texto)
        return texto.startswith("e amanhã")

    com_ele = _vigia(
        ModoDeEscuta.CONTINUA, AsrDeTexto("e amanhã vai chover"), enderecada=enderecada
    )
    assert Acao.CORTAR in _rodar(com_ele, fala_do_dono_ms=800)
    assert com_ele.decisoes[-1].motivo is Motivo.ENDERECADA

    alheia = _vigia(
        ModoDeEscuta.CONTINUA, AsrDeTexto("o jogo ontem foi bom demais"), enderecada=enderecada
    )
    acoes = _rodar(alheia, fala_do_dono_ms=800)
    assert Acao.CORTAR not in acoes and Acao.RETOMAR in acoes
    assert any(d.motivo is Motivo.NAO_ERA_COMIGO for d in alheia.decisoes)
    # A mesma fala alheia, depois de julgada, não pausa o Jarvis de novo nem volta ao detector.
    assert acoes.count(Acao.RETOMAR) == 1 and Acao.PAUSAR not in acoes
    assert perguntadas == ["e amanhã vai chover", "o jogo ontem foi bom demais"]


def test_transcricao_vazia_ou_asr_que_falha_nao_corta() -> None:
    vazia = _vigia(ModoDeEscuta.CONTINUA, AsrDeTexto(""))
    acoes = _rodar(vazia, fala_do_dono_ms=800)
    assert Acao.CORTAR not in acoes and Acao.RETOMAR in acoes
    assert vazia.decisoes[-1].motivo is Motivo.SEM_FALA

    def quebrado(_amostras: bytes) -> str:
        raise RuntimeError("o ASR caiu")

    falhou = _vigia(ModoDeEscuta.PALAVRA, quebrado)
    assert Acao.CORTAR not in _rodar(falhou, fala_do_dono_ms=800)


def test_pausa_sem_resposta_do_asr_retoma_no_prazo() -> None:
    def nunca(_funcao: Callable[[], object]) -> Future[object]:
        return Future()  # o ASR em segundo plano que não volta

    vigia = _vigia(ModoDeEscuta.CONTINUA, AsrDeTexto("x"), enviar=nunca)

    acoes = _rodar(vigia, fala_do_dono_ms=4000, depois_ms=500)

    pausa = acoes.index(Acao.PAUSAR)
    retomada = acoes.index(Acao.RETOMAR)
    assert (retomada - pausa) * 20 >= 2500, "retomou antes do prazo da pausa"
    assert any(d.motivo is Motivo.PRAZO_DA_PAUSA for d in vigia.decisoes)


def test_a_vigia_com_asr_em_segundo_plano_corta_quando_o_resultado_chega() -> None:
    pendentes: list[tuple[Future[object], Callable[[], object]]] = []

    def depois(funcao: Callable[[], object]) -> Future[object]:
        futuro: Future[object] = Future()
        pendentes.append((futuro, funcao))
        return futuro

    vigia = _vigia(ModoDeEscuta.PALAVRA, AsrDeTexto("jarvis para"), enviar=depois)
    jarvis = _fala(3000, 1)
    dono = silencio(1000) + _fala(1500, 7, pico=0.5, f0=180.0) + silencio(500)
    acoes = []
    for indice, (ref, quadro) in enumerate(_junto(jarvis, dono)):
        if indice == 70 and pendentes:  # o ASR termina 200 ms depois de pedido
            futuro, funcao = pendentes.pop(0)
            futuro.set_result(funcao())
        vigia.portao.referencia(ref)
        acoes.append(vigia.ouvir(quadro, fala_no_vad=quadro.energia_db > -45.0))

    assert acoes.index(Acao.CORTAR) == 70


def test_sem_o_eco_tira_o_comeco_que_era_o_jarvis() -> None:
    vigia = _vigia(ModoDeEscuta.CONTINUA, AsrDeTexto(""))
    vigia.falando("A previsão para amanhã é de sol com nuvens à tarde.")

    assert vigia.sem_o_eco("sol com nuvens e em Lisboa?") == "e em Lisboa?"
    assert vigia.sem_o_eco("e em Lisboa?") == "e em Lisboa?"
    assert vigia.sem_o_eco("sol") == "sol"  # uma palavra só não basta para dizer que era eco


def test_as_ordens_de_parar() -> None:
    for ordem in ("para", "Para!", "chega", "espera aí", "peraí", "silêncio", "cala a boca"):
        assert eh_ordem_de_parar(ordem), ordem
    for nao in ("para o carro na garagem que eu já desço", "ok", "obrigado", "que horas são"):
        assert not eh_ordem_de_parar(nao), nao
    assert so_ordem_de_parar("para") and so_ordem_de_parar("chega, chega")
    assert not so_ordem_de_parar("espera, abre o spotify antes")


# --- a configuração ------------------------------------------------------------------------------
def test_interromper_por_voz_vem_ligado_e_o_dono_pode_desligar(tmp_path: Path) -> None:
    assert Configuracao().interromper_por_voz is True
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text("interromper_por_voz = false\n", encoding="utf-8")
    assert ler(arquivo).interromper_por_voz is False
    arquivo.write_text("escuta = 'palavra'\n", encoding="utf-8")
    assert ler(arquivo).interromper_por_voz is True  # arquivo antigo: o padrão


# --- o laço inteiro -------------------------------------------------------------------------------
class AsrDoLaco:
    """O ASR da sessão: o primeiro trecho é o pedido longo; daí em diante, o que o dono diz por
    cima (a vigia e o turno novo ouvem a mesma coisa)."""

    nome = "asr-falso"
    modelo = "(nenhum)"
    licenca = "Apache-2.0"
    idioma = "pt-BR"
    onde = Onde.LOCAL

    def __init__(self, primeiro: str, depois: str) -> None:
        self.textos = (primeiro, depois)
        self.chamadas = 0

    def transcrever(self, amostras: bytes) -> Hipotese:
        self.chamadas += 1
        return Hipotese(self.textos[0] if self.chamadas == 1 else self.textos[1], 1.0)


def _wav(caminho: Path, *trechos: bytes) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(b"".join(trechos))
    return caminho


def _respostas(*textos: str) -> Callable[[object], str]:
    vez = [0]

    def responder(_contexto: object) -> str:
        vez[0] += 1
        return textos[min(vez[0], len(textos)) - 1]

    return responder


def _aplicativo(
    tmp_path: Path, escuta: str, asr: AsrDoLaco, respostas: Sequence[str]
) -> tuple[Aplicativo, list[str]]:
    tela: list[str] = []
    app = Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", escuta=escuta),
        raiz=tmp_path / "sessao",
        escrever_na_tela=tela.append,
        relogio=RelogioFalso(),
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
    )
    app._asr = asr
    app._motor = MotorRoteirizado(resposta=_respostas(*respostas), nome="roteiro")
    app.vigia = VigiaDeInterrupcao(
        transcrever=lambda amostras: asr.transcrever(amostras).texto, enviar=em_linha
    )
    # O dono pede (0,4 s), cala enquanto o Jarvis conta a história, fala por cima aos 4 s e cala.
    app.caminho_de_entrada = _wav(
        tmp_path / "entrada.wav",
        _fala(400, 5, pico=0.5, f0=180.0),
        silencio(3600),
        _fala(1000, 7, pico=0.5, f0=180.0),
        silencio(3000),
    )
    app.caminho_de_saida = tmp_path / "saida.wav"
    return app, tela


def _trilha(app: Aplicativo) -> list[dict[str, object]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]


def test_no_laco_o_nome_por_cima_corta_o_tts_e_o_pedido_novo_e_atendido(tmp_path: Path) -> None:
    asr = AsrDoLaco("jarvis me conta uma história", "jarvis que horas são")
    app, tela = _aplicativo(tmp_path, "palavra", asr, [LONGA, "São três e meia."])
    epoch = app.epoch

    app.rodar_audio(limite_de_turnos=2)

    assert [t.falou for t in app.turnos] == ["me conta uma história", "que horas são"]
    primeiro, segundo = app.turnos
    assert primeiro.cancelado, "a história não foi cortada"
    inteira = len(app._tts.sintetizar(LONGA)) // 2 if app._tts is not None else 0
    assert 0 < primeiro.amostras_tocadas < 0.6 * inteira, "tocou a história quase inteira"
    assert segundo.respondeu == "São três e meia." and not segundo.cancelado
    assert app.epoch == epoch + 1
    assert "  ⟂ interrompido (voz)" in tela
    # A conversa guarda só o que o dono ouviu da história, marcada como interrompida.
    assert app._cerebro is not None
    interrompida = [m for m in app._cerebro.conversa.turnos if m.interrompida]
    assert len(interrompida) == 1 and LONGA.startswith(interrompida[0].texto[:20])
    cortes = [
        e for e in _trilha(app) if e["evento"] == "interrupcao" and e.get("decisao") == "cortar"
    ]
    assert (
        cortes and cortes[0]["motivo"] == "palavra_de_ativacao" and cortes[0]["modo"] == "palavra"
    )
    assert all("texto" not in e and "fala" not in e for e in cortes), "a trilha guardou a fala"


def test_no_laco_fala_sem_o_nome_nao_corta_a_historia(tmp_path: Path) -> None:
    asr = AsrDoLaco("jarvis me conta uma história", "olha que bonito isso")
    app, _tela = _aplicativo(tmp_path, "palavra", asr, [LONGA])
    epoch = app.epoch

    app.rodar_audio(limite_de_turnos=2)

    assert len(app.turnos) == 1 and not app.turnos[0].cancelado
    assert app.epoch == epoch
    assert asr.chamadas >= 2, "a vigia nem ouviu o dono falando por cima"


def test_no_laco_jarvis_para_cala_sem_virar_pedido(tmp_path: Path) -> None:
    asr = AsrDoLaco("jarvis me conta uma história", "jarvis para")
    app, tela = _aplicativo(tmp_path, "palavra", asr, [LONGA, "isto não pode ser dito"])

    app.rodar_audio(limite_de_turnos=2)

    assert len(app.turnos) == 1 and app.turnos[0].cancelado
    assert "  (parei)" in tela
    assert isinstance(app._motor, MotorRoteirizado)
    assert len(app._motor.pedidos) == 1, "«para» virou pedido ao motor"


def test_na_continua_o_laco_pausa_e_retoma_a_historia_quando_nao_e_com_ele(tmp_path: Path) -> None:
    asr = AsrDoLaco("me conta uma história", "olha que bonito isso")
    app, _tela = _aplicativo(tmp_path, "vad", asr, [LONGA])

    app.rodar_audio(limite_de_turnos=1)

    assert len(app.turnos) == 1 and not app.turnos[0].cancelado
    decisoes = [e.get("decisao") for e in _trilha(app) if e["evento"] == "interrupcao"]
    assert decisoes[:2] == ["pausar", "retomar"], decisoes
    inteira = app._tts.sintetizar(LONGA) if app._tts is not None else b""
    tocado = app.turnos[0].amostras_tocadas * 2
    assert abs(tocado - len(inteira)) < 0.02 * len(inteira), "a pausa perdeu parte da história"


def test_o_sim_dito_por_cima_de_uma_pergunta_nao_confirma(tmp_path: Path) -> None:
    """Fala não confirma ação sozinha: cortar a pergunta é não tê-la ouvido (ADR-0038)."""
    asr = AsrDoLaco("jarvis me conta uma história", "jarvis sim")
    app, _tela = _aplicativo(tmp_path, "palavra", asr, [LONGA])
    app.abrir()
    assert app._cerebro is not None and app.ferramentas is not None
    from jarvis.executor.ferramentas import Confirmacao

    espera = Espera()
    pergunta = Confirmacao(
        id="p-1", tool_id="apps.quit", titulo="Encerrar", detalhe="x", motivo="y", prazo_s=30.0
    )
    app._cerebro.pendencias.abrir(pergunta, espera=espera)

    app.interromper("voz")  # o que a vigia faz ao ouvir "jarvis, sim" por cima

    assert espera.evento.is_set() and espera.sim is False
    assert app._cerebro.pendencias.valida() is None
