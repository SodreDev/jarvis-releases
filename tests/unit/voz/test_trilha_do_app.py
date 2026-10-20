"""A trilha de diagnóstico no laço de verdade: o turno, a ferramenta e o fim — e nada do que o
dono disse, do que a ferramenta devolveu, nem dos valores dos argumentos."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from jarvis.audio_io.playback import FilaDePlayback
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.trilha import ARQUIVO, eventos_do_ultimo_turno, resumo_do_ultimo_turno
from jarvis.voz.app import PASTA_DA_TRILHA, Aplicativo
from jarvis.voz.config import Configuracao


def _roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
    if any(m.papel == "ferramenta" for m in contexto.mensagens):
        return ["Tem um arquivo na pasta."]
    return ["Deixa eu ver. ", PedidoDeTool("files.list_dir", {"path": "~/Documentos"})]


def test_o_turno_deixa_so_metadados_na_trilha(tmp_path: Path) -> None:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    (lar / "Documentos" / "extrato-do-banco-secreto.txt").write_text("saldo", "utf-8")
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco", acesso="padrao"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _: None,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=lar,
    )
    app.abrir(com_asr=False)
    app._motor = MotorRoteirizado(resposta=_roteiro)
    fila = FilaDePlayback(sumidouro=SumidouroEmMemoria(), session_id=app.session_id)

    app.responder("o que tem em Documentos? minha senha é hunter2hunter2", fila=fila)

    pasta = app.raiz / PASTA_DA_TRILHA
    tipos = [e["evento"] for e in eventos_do_ultimo_turno(pasta)]
    assert tipos == ["turno.inicio", "ferramenta", "turno.fim"]
    ferramenta = eventos_do_ultimo_turno(pasta)[1]
    assert ferramenta["tool_id"] == "files.list_dir" and ferramenta["status"] == "ok"
    assert ferramenta["argumentos"] == ["path"] and ferramenta["pdp"] == "allow"
    bruto = (pasta / ARQUIVO).read_text("utf-8")
    for proibido in ("hunter2", "extrato-do-banco", "Documentos", "Deixa eu ver", "Tem um arquivo"):
        assert proibido not in bruto, proibido
    assert any("files.list_dir: ok" in linha for linha in resumo_do_ultimo_turno(pasta))
