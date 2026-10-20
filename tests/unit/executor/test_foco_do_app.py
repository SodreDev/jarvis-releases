"""Abrir um app põe o foco nele quando a janela abrir (dono, 2026-10-20, Lote C, C4; ADR-0037).

Ponta a ponta no executor de verdade — PDP, catálogo, auditoria e o gestor de tarefas —, com as
janelas e o lançador falsos (nenhum app abre, nenhuma janela do dono muda). `apps.launch` devolve
na hora e uma tarefa acompanha; o foco que ela pede passa pelo PDP como qualquer `window.focus_app`;
de dentro de uma tarefa não nasce outra; e, sem como ver as janelas, tudo fica como antes.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.executor.desfazer import Contaminacao
from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.janelas import JanelaDoSistema
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.executor.nativas import Nativas
from jarvis.politica.abertura import nome_de_app
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.tarefas import foco
from jarvis.tarefas.gestor import EstadoDaTarefa, GestorDeTarefas, Tarefa

NUNCA = lambda: False  # noqa: E731
DONO = "0x0100000a"
KATE = "0x0200000b"
PID = 4242


class TelaViva:
    """As janelas de agora (a do dono em foco); `abrir` é o app desenhando a janela dele."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self.janelas = [JanelaDoSistema(DONO, "Documento — Editor", "editor", 300)]
        self.ativa = DONO
        self.ativadas: list[str] = []

    def listar(self) -> list[JanelaDoSistema]:
        with self._trava:
            return [
                JanelaDoSistema(j.id, j.titulo, j.classe, j.pid, ativa=j.id == self.ativa)
                for j in self.janelas
            ]

    def ativar(self, janela_id: str) -> bool:
        with self._trava:
            self.ativadas.append(janela_id)
            self.ativa = janela_id
        return True

    def abrir(self, janela: JanelaDoSistema) -> None:
        with self._trava:
            self.janelas.append(janela)


@pytest.fixture(autouse=True)
def rapido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Os intervalos do motor em centésimos: a lógica é a mesma, o teste não espera segundos."""
    monkeypatch.setattr(foco, "INTERVALOS_S", (0.02,))
    monkeypatch.setattr(foco, "INTERVALO_MAXIMO_S", 0.02)
    monkeypatch.setattr(foco, "CARENCIA_S", 0.05)
    monkeypatch.setattr(foco, "ASSENTAR_S", 0.05)
    monkeypatch.setattr(foco, "FATIA_S", 0.01)


@pytest.fixture
def tela() -> TelaViva:
    return TelaViva()


@pytest.fixture
def executor(tmp_path: Path, tela: TelaViva) -> Iterator[ExecutorDeFerramentas]:
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "kate.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Kate\nExec=kate\n", "utf-8"
    )
    registro = RegistroDeApps.montar(["kate"], pastas=[str(apps)])
    lar = tmp_path / "casa"
    lar.mkdir()

    def lancar(app: App) -> int:  # o app desenha a janela um instante depois de abrir
        janela = JanelaDoSistema(KATE, "Sem título — Kate", "kate", PID)
        threading.Timer(0.03, tela.abrir, args=(janela,)).start()
        return PID

    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            apps_autorizados=frozenset(
                nome_de_app(n) for a in registro.autorizados.values() for n in a.nomes
            ),
        )
        executor = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            registro_de_apps=registro,
            lancar_app=lancar,
            nativas=Nativas(lar=lar, janelas=tela),
        )
        executor.preparar()
        executor.tarefas = GestorDeTarefas(executor=executor, confirmar=lambda _p, _c: False)
        yield executor
        executor.tarefas.encerrar()


def _tarefa(executor: ExecutorDeFerramentas, tarefa_id: str) -> Tarefa:
    assert executor.tarefas is not None and executor.tarefas.esperar(tarefa_id, 5.0)
    return executor.tarefas.tarefas[tarefa_id]


def test_abrir_o_app_devolve_na_hora_e_a_tarefa_poe_a_janela_dele_em_foco(
    executor: ExecutorDeFerramentas, tela: TelaViva
) -> None:
    resultado = executor.executar("apps.launch", {"nome": "kate"}, cancelado=NUNCA)

    assert resultado.status == "ok", resultado.motivo
    assert resultado.dados["foco"].startswith("acompanhando")
    tarefa = _tarefa(executor, str(resultado.dados["tarefa_do_foco"]))
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA, tarefa.motivo
    assert tarefa.aviso == "", "abriu na hora: o fim fica no card, sem aviso falado"
    assert tela.ativadas == [KATE] and tela.ativa == KATE
    linhas = [
        (r["tool_id"], r["veredito"], r["resultado"])
        for r in executor.pdp.auditoria._con.execute(
            "SELECT d.tool_id, d.veredito, r.resultado FROM audit_log d"
            " LEFT JOIN audit_result r ON r.decision_id = d.decision_id ORDER BY d.rowid"
        )
    ]
    assert linhas == [("apps.launch", "allow", "ok"), ("window.focus_app", "allow", "ok")]


def test_de_dentro_de_uma_tarefa_abrir_o_app_nao_cria_outra(
    executor: ExecutorDeFerramentas,
) -> None:
    resultado = executor.executar(
        "apps.launch", {"nome": "kate"}, cancelado=NUNCA, contaminacao=Contaminacao()
    )

    assert resultado.status == "ok" and "foco" not in resultado.dados
    assert executor.tarefas is not None and executor.tarefas.tarefas == {}


def test_sem_como_ver_as_janelas_abrir_o_app_e_como_antes(
    executor: ExecutorDeFerramentas,
) -> None:
    executor.portas().janelas = None

    resultado = executor.executar("apps.launch", {"nome": "kate"}, cancelado=NUNCA)

    assert resultado.status == "ok" and dict(resultado.dados) == {"app": "Kate", "pid": PID}


def test_com_o_teto_de_tarefas_cheio_o_app_abre_e_o_resultado_diz_que_nao_acompanha(
    executor: ExecutorDeFerramentas,
) -> None:
    assert executor.tarefas is not None
    executor.tarefas.maximo_ao_mesmo_tempo = 0

    resultado = executor.executar("apps.launch", {"nome": "kate"}, cancelado=NUNCA)

    assert resultado.status == "ok" and resultado.dados["pid"] == PID
    assert resultado.dados["foco"].startswith("não vou acompanhar a janela: já há 0 tarefas")


def test_focar_pelo_id_passa_pelo_pdp_e_so_vale_o_id_da_lista_de_agora(
    executor: ExecutorDeFerramentas, tela: TelaViva
) -> None:
    tela.abrir(JanelaDoSistema(KATE, "Sem título — Kate", "kate", PID))

    certo = executor.executar(
        "window.focus_app", {"app": "Kate", "janela_id": KATE}, cancelado=NUNCA
    )
    sumida = executor.executar(
        "window.focus_app", {"app": "Kate", "janela_id": "0x0900000f"}, cancelado=NUNCA
    )
    torto = executor.executar(
        "window.focus_app", {"app": "Kate", "janela_id": "1; reboot"}, cancelado=NUNCA
    )

    assert certo.status == "ok" and certo.dados["janela_id"] == KATE
    assert sumida.status == "erro" and "não está mais aberta" in sumida.motivo
    assert torto.status == "erro" and "fora do contrato" in torto.motivo
    assert tela.ativadas == [KATE]


def test_focar_pelo_id_sem_como_ver_as_janelas_diz_o_que_falta(
    executor: ExecutorDeFerramentas,
) -> None:
    executor.portas().janelas = None

    resultado = executor.executar(
        "window.focus_app", {"app": "Kate", "janela_id": KATE}, cancelado=NUNCA
    )

    assert resultado.status == "erro" and "kdotool" in resultado.motivo


def test_a_lista_de_janelas_diz_qual_esta_em_primeiro_plano(
    executor: ExecutorDeFerramentas,
) -> None:
    resultado = executor.executar("window.list", {}, cancelado=NUNCA)

    assert resultado.status == "ok"
    assert resultado.dados["janelas"] == [
        {"id": DONO, "app": "editor", "titulo": "Documento — Editor", "primeiro_plano": True}
    ]
