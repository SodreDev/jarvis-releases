"""Cartão F1-14 com os processos de verdade: a rede cai, o microfone cai para PTT.

O que só aparece aqui: o caminho inteiro da degradação atravessando três processos — o `s2`
detecta no adaptador, a `ui` desliga a escuta contínua e mostra a frase, o `audio-io` **fecha a
fonte**, e o `agentd` diz o aviso uma vez. A rede é derrubada por arquivo (sonda injetada),
nunca mexendo no firewall da máquina, que é o que o cartão manda.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from jarvis.agentd.aviso import avisos_falados
from jarvis.barramento import LogDeEventos, Tipo
from jarvis.barramento.envelope import Envelope
from jarvis.microfone import Modo, ler_estado
from jarvis.rede import (
    VARIAVEL_ARQUIVO,
    VARIAVEL_BACKEND,
    frase_de_queda,
    ler_degradacao,
)
from jarvis.s2.__main__ import call_id_do_turno
from jarvis.supervisao import Supervisor
from jarvis.ui.atalhos import VARIAVEL_ARQUIVO as VARIAVEL_TECLA
from jarvis.ui.atalhos import VARIAVEL_BACKEND as VARIAVEL_ATALHO
from jarvis.ui.painel import ARQUIVO_TELA

LIMITE = 60.0
ESPERA = 25.0
SERVICO = "o serviço de raciocínio"


@pytest.fixture
def supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Supervisor]:
    monkeypatch.setenv(VARIAVEL_BACKEND, "injetada")
    monkeypatch.setenv(VARIAVEL_ARQUIVO, str(tmp_path / "rede"))
    monkeypatch.setenv(VARIAVEL_ATALHO, "falso")
    monkeypatch.setenv(VARIAVEL_TECLA, str(tmp_path / "tecla"))
    rede(tmp_path, ligada=True)
    tecla(tmp_path, apertada=False)
    supervisor = Supervisor(raiz=tmp_path / "exec")
    yield supervisor
    supervisor.parar_tudo()


def rede(base: Path, *, ligada: bool) -> None:
    """Derruba e levanta a rede por arquivo — sem tocar no firewall de ninguém."""
    arquivo = base / "rede"
    temporario = arquivo.with_name("rede.tmp")
    temporario.write_text("1" if ligada else "0", encoding="utf-8")
    temporario.replace(arquivo)


def tecla(base: Path, *, apertada: bool) -> None:
    """A tecla do PTT, apertada de fora dos processos (backend falso do F1-13)."""
    arquivo = base / "tecla"
    temporario = arquivo.with_name("tecla.tmp")
    temporario.write_text("1" if apertada else "0", encoding="utf-8")
    temporario.replace(arquivo)


def esperar(condicao: Callable[[], bool], descricao: str, *, limite: float = ESPERA) -> None:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.05)
    raise AssertionError(f"não aconteceu em {limite}s: {descricao}")


def envelopes(raiz: Path) -> list[Envelope]:
    arquivo = raiz / "eventos.sqlite"
    if not arquivo.exists():
        return []
    with LogDeEventos(arquivo) as log:
        return [r.envelope for r in log.ler()]


def tipos(raiz: Path) -> list[Tipo]:
    return [e.type for e in envelopes(raiz)]


def tela(raiz: Path) -> str:
    caminho = raiz / ARQUIVO_TELA
    return caminho.read_text(encoding="utf-8").strip() if caminho.exists() else ""


def test_rede_cai_microfone_cai_para_ptt_e_a_ui_diz(supervisor: Supervisor) -> None:
    raiz = supervisor.raiz
    base = raiz.parent
    # `--muitos-turnos`: o esqueleto fecha UM turno (F0-03), e este teste precisa de um
    # segundo — o que o dono fala por PTT **com a rede fora**, que é o pedido que cai.
    supervisor.iniciar("agentd", "--muitos-turnos", "--timeout", str(LIMITE))
    supervisor.esperar_barramento()
    supervisor.iniciar("s2", "--rede", "--timeout", str(LIMITE))
    for nome in ("policy", "executor", "memoryd"):
        supervisor.iniciar(nome, "--timeout", str(LIMITE))
    supervisor.iniciar("ui", "--microfone", "--modo", "escuta", "--timeout", str(LIMITE))
    supervisor.iniciar(
        "audio-io",
        "--capturar",
        "--controle-de-microfone",
        "--emitir-fala",
        "--timeout",
        str(LIMITE),
    )

    # Com rede, a cadeia inteira anda e o microfone fica aberto (escuta contínua).
    esperar(lambda: ler_estado(raiz).aberta, "a escuta contínua abrir a fonte")
    esperar(lambda: Tipo.TOOL_CALL_REQUESTED in tipos(raiz), "o s2 pedir a tool com rede")
    pedidos_com_rede = tipos(raiz).count(Tipo.TOOL_CALL_REQUESTED)
    assert ler_degradacao(raiz).ativa is False

    rede(base, ligada=False)

    esperar(lambda: ler_degradacao(raiz).ativa, "o adaptador do s2 declarar a degradação")
    esperar(lambda: not ler_estado(raiz).aberta, "o microfone cair para PTT e fechar a fonte")
    esperar(lambda: frase_de_queda(SERVICO) in tela(raiz), "a ui dizer o que deixou de funcionar")
    esperar(lambda: len(avisos_falados(raiz)) == 1, "o agentd dizer o aviso por voz")
    time.sleep(2.0)  # tempo de sobra para o aviso repetir, se fosse repetir

    assert ler_estado(raiz).modo is Modo.PTT, "escuta contínua desligada, PTT ligado"
    assert len(avisos_falados(raiz)) == 1, "o aviso por voz não se repete em loop (aceite (e))"
    assert avisos_falados(raiz)[0].frase == frase_de_queda(SERVICO)

    # O dono continua falando, agora por PTT e sem rede: o pedido CAI e fica registrado como
    # descartado. É o pedido que a volta da rede não pode ressuscitar. Espera-se um descarte
    # **novo**: o turno que caiu junto com a rede já pode estar na lista, e aí "a lista não está
    # vazia" passaria sem o turno do PTT ter acontecido.
    antes_do_ptt = len(ler_degradacao(raiz).descartados)
    tecla(base, apertada=True)
    esperar(lambda: ler_estado(raiz).aberta, "o PTT abrir a fonte com a rede fora")
    esperar(
        lambda: len(ler_degradacao(raiz).descartados) > antes_do_ptt,
        "o pedido do turno falado no PTT cair e ser descartado",
    )
    tecla(base, apertada=False)
    esperar(lambda: not ler_estado(raiz).aberta, "soltar a tecla fechar a fonte")
    descartados = ler_degradacao(raiz).descartados
    pedidos_sem_rede = tipos(raiz).count(Tipo.TOOL_CALL_REQUESTED)

    assert pedidos_sem_rede == pedidos_com_rede, "sem rede, nenhum pedido novo entra no barramento"

    rede(base, ligada=True)

    esperar(lambda: not ler_degradacao(raiz).ativa, "a volta da rede limpar a degradação")
    esperar(lambda: ler_estado(raiz).aberta, "a volta restaurar a escuta contínua")
    # A escuta que volta ouve de verdade: a fonte sintética reaberta tem fala, e fala nova é
    # turno novo — que tem de ser atendido, senão a volta deixou o Jarvis surdo. Até o defeito
    # do `call_id` (ver `call_id_do_turno`), esse turno era recusado como se fosse o que caiu,
    # e era isso que fazia "nenhum pedido depois da volta" parecer verdade.
    esperar(
        lambda: tipos(raiz).count(Tipo.TOOL_CALL_REQUESTED) > pedidos_com_rede,
        "um turno novo, falado depois da volta, ser atendido",
    )
    time.sleep(1.0)  # tempo de sobra para um pedido velho ressuscitar, se fosse ressuscitar

    trilha = envelopes(raiz)
    pedidos = [e for e in trilha if e.type is Tipo.TOOL_CALL_REQUESTED]
    transcricoes = {call_id_do_turno(e): e for e in trilha if e.type is Tipo.FINAL_TRANSCRIPT}
    epoch_que_caiu = max(transcricoes[c].epoch for c in descartados)
    ids = [str(p.payload["call_id"]) for p in pedidos]
    depois_da_volta = pedidos[pedidos_com_rede:]

    assert not set(ids) & set(descartados), (
        "a volta da rede não pode ressuscitar pedido velho (§3.3 regra 5, aceite (c))"
    )
    assert len(set(ids)) == len(ids), "cada pedido é de um turno: nenhum call_id se repete"
    for pedido in depois_da_volta:
        origem = transcricoes[str(pedido.payload["call_id"])]
        assert pedido.epoch == origem.epoch > epoch_que_caiu, (
            "depois da volta, só turno nascido depois do último que caiu vira pedido"
        )
    assert ler_degradacao(raiz).descartados == descartados, (
        "a lista de descartados sobrevive à volta: é ela que impede o ressuscitar"
    )
    assert len(avisos_falados(raiz)) == 1, "a volta não repete o aviso por voz"
    assert supervisor.vivo("s2") and supervisor.vivo("ui") and supervisor.vivo("audio-io")
