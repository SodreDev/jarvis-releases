"""Timers, alarmes e lembretes que viram `Notification` (item 4, grupo 2; ADR-0025).

Relógio e espera são injetados: o teste anda o tempo à mão, sem dormir de verdade.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.alarmes import (
    LIMITE_DE_ALARMES,
    AgendaDeAlarmes,
    Alarme,
    agenda_compartilhada,
    quando_da_fala,
)
from jarvis.executor.comandos import LancadorFalso
from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.nativas import Nativas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731
AGORA = datetime(2026, 10, 19, 22, 30, 0).astimezone()


class Relogio:
    def __init__(self, inicio: float) -> None:
        self.t = inicio

    def __call__(self) -> float:
        return self.t


def _esperar(condicao: Any, segundos: float = 3.0) -> bool:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.005)
    return bool(condicao())


# --- resolver a fala ------------------------------------------------------------
def test_daqui_a_n_segundos_e_hora_do_dia_e_data_iso() -> None:
    assert quando_da_fala(em_segundos=600, as_=None, agora=AGORA) == AGORA.timestamp() + 600
    sete = quando_da_fala(em_segundos=None, as_="07:00", agora=AGORA)
    assert datetime.fromtimestamp(sete).strftime("%d %H:%M") == "20 07:00", (
        "às 7, dito à noite, é amanhã"
    )
    iso = quando_da_fala(em_segundos=None, as_="2026-10-25T09:15", agora=AGORA)
    assert datetime.fromtimestamp(iso).strftime("%Y-%m-%d %H:%M") == "2026-10-25 09:15"


@pytest.mark.parametrize(
    ("em", "as_", "trecho"),
    [
        (None, None, "um dos dois"),
        (60, "07:00", "um dos dois"),
        (0, None, "vai de 1 a"),
        (10**8, None, "vai de 1 a"),
        (None, "amanhã cedo", "HH:MM"),
        (None, "2020-01-01T10:00", "já passou"),
        (None, "2027-01-01T10:00", "30 dias"),
    ],
)
def test_pedido_ruim_de_alarme_volta_com_a_frase(em: Any, as_: Any, trecho: str) -> None:
    with pytest.raises(ValueError, match=trecho):
        quando_da_fala(em_segundos=em, as_=as_, agora=AGORA)


# --- a agenda ------------------------------------------------------------
def test_o_alarme_dispara_na_hora_e_uma_vez_so(tmp_path: Path) -> None:
    disparados: list[Alarme] = []
    relogio = Relogio(1000.0)
    agenda = AgendaDeAlarmes(tmp_path / "alarmes.json", disparados.append, relogio=relogio)
    agenda.iniciar()
    try:
        alarme = agenda.agendar("tirar o bolo do forno", 1010.0)
        time.sleep(0.05)
        assert disparados == [], "ainda não venceu"

        relogio.t = 1011.0
        agenda.agendar("outro", 5000.0)  # acorda a linha (qualquer mudança acorda)

        assert _esperar(lambda: [a.id for a in disparados] == [alarme.id])
        time.sleep(0.1)
        assert len(disparados) == 1
        assert [a.mensagem for a in agenda.listar()] == ["outro"]
    finally:
        agenda.encerrar()


def test_persiste_e_o_que_venceu_fechado_dispara_ao_abrir_como_atrasado(tmp_path: Path) -> None:
    arquivo = tmp_path / "alarmes.json"
    primeiro = AgendaDeAlarmes(arquivo, lambda _a: None, relogio=Relogio(1000.0))
    primeiro.agendar("ligar para a Bia", 1200.0)
    primeiro.agendar("daqui a muito", 9000.0)

    recebidos: list[Alarme] = []
    segundo = AgendaDeAlarmes(arquivo, recebidos.append, relogio=Relogio(2000.0))
    segundo.iniciar()
    try:
        assert _esperar(lambda: len(recebidos) == 1)
        assert recebidos[0].mensagem == "ligar para a Bia" and recebidos[0].atrasado
        assert [a.mensagem for a in segundo.listar()] == ["daqui a muito"]
    finally:
        segundo.encerrar()


def test_cancelar_tira_da_agenda_e_do_disco_e_id_errado_volta_com_a_frase(tmp_path: Path) -> None:
    agenda = AgendaDeAlarmes(tmp_path / "a.json", lambda _a: None, relogio=Relogio(0.0))
    alarme = agenda.agendar("x y z", 100.0)

    agenda.cancelar(alarme.id)

    assert agenda.listar() == [] and (tmp_path / "a.json").read_text() == "[]"
    with pytest.raises(ValueError, match="não existe o alarme"):
        agenda.cancelar("al-nada")


def test_agenda_tem_teto_e_arquivo_corrompido_nao_derruba(tmp_path: Path) -> None:
    arquivo = tmp_path / "a.json"
    arquivo.write_text("{isto nao e json", "utf-8")
    agenda = AgendaDeAlarmes(arquivo, lambda _a: None, relogio=Relogio(0.0))
    agenda.iniciar()
    try:
        for i in range(LIMITE_DE_ALARMES):
            agenda.agendar(f"lembrete {i}", 1e6 + i)
        with pytest.raises(ValueError, match="cancele algum"):
            agenda.agendar("mais um", 2e6)
    finally:
        agenda.encerrar()


def test_entrega_que_falha_nao_derruba_a_agenda(tmp_path: Path) -> None:
    chegaram: list[str] = []

    def quebra_na_primeira(alarme: Alarme) -> None:
        chegaram.append(alarme.mensagem)
        if len(chegaram) == 1:
            raise RuntimeError("fila caiu")

    relogio = Relogio(0.0)
    agenda = AgendaDeAlarmes(tmp_path / "a.json", quebra_na_primeira, relogio=relogio)
    agenda.iniciar()
    try:
        agenda.agendar("um dois", 5.0)
        agenda.agendar("três quatro", 6.0)
        relogio.t = 10.0
        agenda.agendar("acorda", 99.0)
        assert _esperar(lambda: len(chegaram) == 2)
    finally:
        agenda.encerrar()


def test_a_agenda_compartilhada_e_uma_so_por_arquivo_e_troca_quem_recebe(tmp_path: Path) -> None:
    arquivo = tmp_path / "compartilhada.json"
    a: list[Alarme] = []
    b: list[Alarme] = []

    primeira = agenda_compartilhada(arquivo, a.append)
    segunda = agenda_compartilhada(arquivo, b.append)

    try:
        assert primeira is segunda, "cada conversa nova não cria agenda nova"
        assert primeira.ao_disparar == b.append
    finally:
        primeira.encerrar()


# --- as tools ------------------------------------------------------------
@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        agenda = AgendaDeAlarmes(
            tmp_path / "area" / "alarmes.json", lambda _a: None, relogio=Relogio(AGORA.timestamp())
        )
        executor = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            nativas=Nativas(lar=lar, lancar=LancadorFalso(), agora=lambda: AGORA, agenda=agenda),
        )
        executor.preparar()
        yield executor


def test_marcar_alarme_avisa_em_voz_lista_e_o_desfazer_cancela(
    executor: ExecutorDeFerramentas,
) -> None:
    marcado = executor.executar(
        "timer.alarm.set", {"mensagem": "tirar o bolo", "em_segundos": 600}, cancelado=NUNCA
    )

    assert marcado.status == "ok", marcado.motivo
    assert marcado.aviso == "Marquei o lembrete para daqui a 10 minutos, às 22:40: tirar o bolo."
    assert marcado.acao_id.startswith("a-")
    lista = executor.executar("timer.alarm.list", {}, cancelado=NUNCA)
    assert [(a["mensagem"], a["falta_segundos"]) for a in lista.dados["alarmes"]] == [
        ("tirar o bolo", 600)
    ]

    desfeito = executor.executar("acao.desfazer", {}, cancelado=NUNCA)

    assert desfeito.status == "ok"
    assert executor.executar("timer.alarm.list", {}, cancelado=NUNCA).dados["alarmes"] == []


def test_cancelar_pelo_id_e_pedido_invalido_e_erro_com_frase(
    executor: ExecutorDeFerramentas,
) -> None:
    marcado = executor.executar(
        "timer.alarm.set", {"mensagem": "ligar", "em_segundos": 60}, cancelado=NUNCA
    )

    ruim = executor.executar("timer.alarm.set", {"mensagem": "ligar"}, cancelado=NUNCA)
    certo = executor.executar(
        "timer.alarm.cancel", {"alarme_id": marcado.dados["alarme_id"]}, cancelado=NUNCA
    )

    assert ruim.status == "erro" and "um dos dois" in ruim.motivo
    assert certo.status == "ok" and certo.aviso == ""


def test_alarme_so_existe_para_o_modelo_com_agenda(tmp_path: Path) -> None:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "au.sqlite") as auditoria:
        pdp = Pdp(catalogo=carregar_catalogo(), lar=lar, auditoria=auditoria, modo=Modo.PADRAO,
                  pasta_do_jarvis=tmp_path / "area")  # fmt: skip
        sem = ExecutorDeFerramentas(pdp=pdp, lar=lar)
        assert not [t for t in sem.catalogo_para_o_modelo() if t["id"].startswith("timer.")]
        assert sem.executar("timer.alarm.list", {}, cancelado=NUNCA).status == "negado"


def test_o_lembrete_que_vence_entra_pela_fila_de_avisos_e_vira_notificacao_do_desktop(
    tmp_path: Path,
) -> None:
    from jarvis.voz.app import Aplicativo
    from jarvis.voz.config import Configuracao

    laco = Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_saida=tmp_path / "saida.wav",
    )
    laco.abrir(com_asr=False)
    assert laco.ferramentas is not None
    falso = LancadorFalso()
    laco.ferramentas.portas().lancar = falso
    agenda = laco.ferramentas.portas().agenda
    assert agenda is not None

    try:
        agenda.agendar("tirar o bolo do forno", time.time() + 0.15)

        assert _esperar(lambda: bool(laco.dados_dos_avisos()["avisos"]))
        aviso = laco.dados_dos_avisos()["avisos"][0]
        assert aviso["tipo"] == "evento" and aviso["origem"] == "lembrete"
        assert "tirar o bolo do forno" in aviso["resumo"]
        assert any(
            c[0] == "notify-send" and "tirar o bolo do forno" in c[-1] for c in falso.chamadas
        )
    finally:
        agenda.encerrar()
