"""A confirmação respondida por voz, de ponta a ponta (dono, 2026-10-25; ADR-0048).

O laço da trilha do dono (24/10): o Jarvis perguntou, o dono disse «Jarvis, sim» por cima, o corte
derrubou a pergunta (não ouvida = não) e o motor a repropôs — três vezes. Aqui o laço inteiro roda
com áudio sintético (`jarvis.audio_io.sintese`), ASR falso e o motor roteirizado, sem microfone nem
alto-falante: o dono pede, o Jarvis termina o turno na pergunta, e a resposta falada — por cima da
pergunta ou depois dela, com ou sem a palavra — executa ou cancela **uma vez**, sem reproposta.

O que isto não prova: sala, eco e ASR de verdade (o eco acústico é a `test_interromper_por_voz`).
"""

from __future__ import annotations

import json
import wave
from collections.abc import Callable, Sequence
from pathlib import Path
from random import Random
from typing import Any

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import fala_simulada, silencio
from jarvis.memoryd.cofre import CofreFernet, nova_chave
from jarvis.memoryd.conversa import ConversaPersistente, abrir_conversa
from jarvis.memoryd.indice import IndiceEmMemoria
from jarvis.politica.memoria import Estado
from jarvis.relogio import RelogioFalso
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.interface import Hipotese, Onde
from jarvis.voz.interrupcao import VigiaDeInterrupcao, em_linha

PEDIDO = "jarvis apaga aquela anotação do café"
COMECO = "Vou apagar aquela anotação do café que você me pediu para guardar na semana passada. "
"""A frase antes da ferramenta: longa o bastante para a pergunta ainda tocar quando o dono fala."""


class AsrDoLaco:
    """O primeiro trecho é o pedido; daí em diante, a resposta do dono (a vigia e o turno ouvem
    a mesma coisa)."""

    nome = "asr-falso"
    modelo = "(nenhum)"
    licenca = "Apache-2.0"
    idioma = "pt-BR"
    onde = Onde.LOCAL

    def __init__(self, resposta: str) -> None:
        self.resposta = resposta
        self.chamadas = 0

    def transcrever(self, amostras: bytes) -> Hipotese:
        self.chamadas += 1
        return Hipotese(PEDIDO if self.chamadas == 1 else self.resposta, 1.0)


def _fala(ms: float, semente: int) -> bytes:
    return fala_simulada(ms, aleatorio=Random(semente), pico=0.5, f0_hz=180.0)


def _wav(caminho: Path, *trechos: bytes) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(b"".join(trechos))
    return caminho


def _resultado(contexto: Contexto) -> dict[str, Any] | None:
    textos = [m.texto for m in contexto.mensagens if m.papel == "ferramenta"]
    return json.loads(textos[-1].removesuffix(" …[truncado]")) if textos else None


def _apagar_a(alvo: str) -> Callable[[Contexto], Sequence[str | PedidoDeTool]]:
    def roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        resultado = _resultado(contexto)
        if resultado is None:
            return [COMECO, PedidoDeTool("memoria.apagar", {"alvo_id": alvo, "escopo": "memoria"})]
        return ["Apaguei."] if resultado["status"] == "ok" else ["Não apaguei."]

    return roteiro


def _memoria_do_dono(tmp_path: Path) -> tuple[ConversaPersistente, str]:
    conversa = abrir_conversa(
        tmp_path / "sessao", cofre=lambda: CofreFernet(nova_chave()), indice=IndiceEmMemoria()
    )
    assert conversa.livro is not None
    origem = conversa.livro.gravar_turno(
        session_id=conversa.conversa_id,
        papel="dono",
        texto="o café acabou, comprar café",
        trust="user_voice",
    )
    feita = conversa.livro.lembrar(
        "comprar café", estado=Estado.ATIVA, fonte=origem, extrator="teste"
    )
    return conversa, str(feita["assertion_id"])


def _memoria_viva(conversa: ConversaPersistente, alvo: str) -> bool:
    assert conversa.livro is not None
    sql = "SELECT 1 FROM assertion WHERE id = ?"
    return bool(conversa.livro.con.execute(sql, (alvo,)).fetchone())


def _rodar(
    tmp_path: Path, resposta: str, *, por_cima: bool, escuta: str = "palavra"
) -> tuple[Aplicativo, ConversaPersistente, str, list[str]]:
    """O dono pede; o Jarvis fala e termina na pergunta; o dono responde — `por_cima` (enquanto a
    pergunta ainda toca) ou depois que ela acabou."""
    conversa, alvo = _memoria_do_dono(tmp_path)
    asr = AsrDoLaco(resposta)
    tela: list[str] = []
    app = Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", escuta=escuta),
        raiz=tmp_path / "sessao",
        escrever_na_tela=tela.append,
        relogio=RelogioFalso(),
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        conversa=conversa,
    )
    app._asr = asr
    app._motor = MotorRoteirizado(resposta=_apagar_a(alvo), nome="roteiro")
    app.vigia = VigiaDeInterrupcao(
        transcrever=lambda amostras: asr.transcrever(amostras).texto, enviar=em_linha
    )
    espera_ms = 2200 if por_cima else 12_000
    app.caminho_de_entrada = _wav(
        tmp_path / "entrada.wav",
        _fala(500, 5),
        silencio(espera_ms),
        _fala(700, 7),
        silencio(4000),
    )
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.rodar_audio(limite_de_turnos=2)
    return app, conversa, alvo, tela


def _trilha(app: Aplicativo) -> list[dict[str, Any]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]


def _pedidos_ao_motor(app: Aplicativo) -> int:
    assert isinstance(app._motor, MotorRoteirizado)
    return len(app._motor.pedidos)


def _cortes(app: Aplicativo) -> list[str]:
    return [
        str(e["motivo"])
        for e in _trilha(app)
        if e["evento"] == "interrupcao" and e.get("decisao") == "cortar"
    ]


def test_jarvis_sim_por_cima_da_pergunta_confirma_uma_vez_sem_reproposta(tmp_path: Path) -> None:
    """O caso da trilha do dono: «Jarvis, sim» cortando a pergunta. Corta limpo, a pergunta foi
    ouvida (não vira "não"), a ação roda uma vez, e o motor não é chamado de novo."""
    app, conversa, alvo, tela = _rodar(tmp_path, "Jarvis, sim.", por_cima=True)

    assert [t.falou for t in app.turnos] == ["apaga aquela anotação do café", "sim"]
    primeiro, segundo = app.turnos
    assert primeiro.cancelado, "a resposta não cortou a pergunta"
    assert primeiro.respondeu.endswith("Posso apagar de vez?")
    assert _cortes(app) == ["resposta_a_pergunta"]
    assert not _memoria_viva(conversa, alvo), "com o sim do dono, apagou"
    assert segundo.respondeu and not segundo.cancelado, "o sim não teve a frase do feito"
    assert _pedidos_ao_motor(app) == 1, "a pergunta foi reproposta"
    assert app._cerebro is not None and app._cerebro.pendencias.valida() is None
    assert "Você: Jarvis, sim." in tela


def test_sim_sem_a_palavra_depois_da_pergunta_confirma(tmp_path: Path) -> None:
    """No modo palavra, com a pergunta aberta, «sim» sem o nome é a resposta."""
    app, conversa, alvo, _tela = _rodar(tmp_path, "Sim.", por_cima=False)

    assert [t.falou for t in app.turnos] == ["apaga aquela anotação do café", "sim"]
    assert not app.turnos[0].cancelado, "a pergunta tocou inteira"
    assert not _memoria_viva(conversa, alvo)
    assert _pedidos_ao_motor(app) == 1


def test_pode_apagar_repetindo_a_acao_perguntada_confirma(tmp_path: Path) -> None:
    app, conversa, alvo, _tela = _rodar(tmp_path, "Pode apagar.", por_cima=True)

    assert not _memoria_viva(conversa, alvo)
    assert _pedidos_ao_motor(app) == 1


def test_nao_por_cima_cancela_sem_reproposta(tmp_path: Path) -> None:
    app, conversa, alvo, _tela = _rodar(tmp_path, "Jarvis, não.", por_cima=True)

    assert app.turnos[0].cancelado and _cortes(app) == ["resposta_a_pergunta"]
    assert _memoria_viva(conversa, alvo), "com o não, nada foi apagado"
    assert app.turnos[1].respondeu.startswith("Tudo bem, não vou fazer isso")
    assert _pedidos_ao_motor(app) == 1, "o não virou pedido ao motor"
    assert app._cerebro is not None and app._cerebro.pendencias.valida() is None


def test_cancela_depois_da_pergunta_cancela(tmp_path: Path) -> None:
    app, conversa, alvo, _tela = _rodar(tmp_path, "Cancela.", por_cima=False)

    assert _memoria_viva(conversa, alvo)
    assert app.turnos[-1].respondeu.startswith("Tudo bem, não vou fazer isso")
    assert _pedidos_ao_motor(app) == 1


@pytest.mark.parametrize(
    ("por_cima", "motivo"), [(True, "eco_do_jarvis"), (False, "eco_da_pergunta")]
)
def test_o_eco_da_pergunta_nao_confirma_nem_cancela(
    tmp_path: Path, por_cima: bool, motivo: str
) -> None:
    """O microfone devolve a própria pergunta («…Posso apagar de vez?»): não corta, não responde e
    não a derruba como "outro assunto" (ADR-0048) — ela segue esperando o dono. Por cima, a vigia
    a descarta como eco; depois da fala, o laço a descarta como eco da pergunta."""
    app, conversa, alvo, _tela = _rodar(tmp_path, "Posso apagar de vez?", por_cima=por_cima)

    assert len(app.turnos) == 1 and not app.turnos[0].cancelado
    assert _cortes(app) == []
    assert motivo in [e.get("motivo") for e in _trilha(app)]
    assert _memoria_viva(conversa, alvo)
    assert _pedidos_ao_motor(app) == 1


def test_na_continua_o_sim_por_cima_tambem_confirma(tmp_path: Path) -> None:
    app, conversa, alvo, _tela = _rodar(tmp_path, "Sim, pode.", por_cima=True, escuta="vad")

    assert app.turnos[0].cancelado and _cortes(app) == ["resposta_a_pergunta"]
    assert not _memoria_viva(conversa, alvo)
    assert _pedidos_ao_motor(app) == 1
