"""ADR-0038 no laço de verdade (modo texto, TTS paramétrico, extensão falsa, sem rede).

O cenário do relato do dono: "abre o vídeo mais recente do canal X no youtube". O Jarvis diz a
frase curta e fica livre; o dono pede outra coisa enquanto a tarefa trabalha e é respondido; a
tarefa termina com a aba no vídeo, e a resposta chega **em voz** pela fila de avisos — no piso
livre, sem ninguém ter de perguntar — e entra na conversa. Nenhuma linha do Jarvis traz protocolo.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path

from jarvis.navegador.cliente import ClienteDoNavegador
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from tests.unit.s2.test_tarefa_do_pedido import (
    PEDIDO,
    PROTOCOLO,
    TITULO,
    VIDEO,
    ExtensaoFalsa,
    _roteiro_do_youtube,
)

PRAZO_S = 10.0


def test_a_tarefa_trabalha_a_conversa_segue_e_a_resposta_chega_em_voz(tmp_path: Path) -> None:
    lar = tmp_path / "casa"
    lar.mkdir()
    linhas: list[str] = []
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco", acesso="padrao"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=linhas.append,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=lar,
    )
    app.abrir(com_asr=False)
    app._motor = MotorRoteirizado(resposta=_roteiro_do_youtube)
    extensao = ExtensaoFalsa()
    extensao.leitura_liberada.clear()  # a tarefa fica presa na leitura até o dono falar de novo
    assert app.ferramentas is not None
    app.ferramentas.navegador = CorposDoNavegador(ClienteDoNavegador(extensao))
    app.avisos.piso_livre_s = 0.0  # o teste não espera o 1,5 s de silêncio do D22
    final = f"Jarvis: Abri «{TITULO}» na aba atual."

    def dono() -> Iterator[str | None]:
        yield PEDIDO
        assert extensao.lendo.wait(PRAZO_S), "a tarefa começou e está trabalhando"
        yield "que horas são?"
        extensao.leitura_liberada.set()
        limite = time.monotonic() + PRAZO_S
        while final not in linhas and time.monotonic() < limite:
            yield None  # o tique sem nada digitado: é aqui que o aviso vai à voz
            threading.Event().wait(0.02)

    app.rodar_texto(dono())

    falas = [linha for linha in linhas if linha.startswith("Jarvis: ")]
    assert falas == ["Jarvis: Vou procurar no YouTube.", "Jarvis: São dez horas.", final]
    for fala in falas:
        for marca in PROTOCOLO:
            assert marca not in fala, f"{marca!r} vazou em {fala!r}"
    assert extensao.url == VIDEO
    assert app._cerebro is not None
    ditas = [m.texto for m in app._cerebro.conversa.turnos if m.papel == "jarvis"]
    assert ditas[-1] == final.removeprefix("Jarvis: "), "o que tocou entrou na conversa"
