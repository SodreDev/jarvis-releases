"""O motor que acompanha um app até a janela abrir e a põe em foco (dono, 2026-10-20, C4; ADR-0037).

Sem janela e sem espera de verdade: o relógio é falso (`dormir` o adianta) e as janelas são uma
linha do tempo — cada uma aparece e some num instante. O gestor é simulado no laço `_rodar`: o
pedido de foco do motor vira o `ativar` das janelas falsas, como o executor faria. Prova-se o
caso do dono: o Steam pede a conta (do dono, o Jarvis espera), o jogo demora e a janela dele
aparece sozinha depois — e só ela vai para a frente; o resto (dúvida, palpite, prazo) termina
com a frase honesta.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from jarvis.executor.ferramentas import ResultadoDeFerramenta
from jarvis.executor.janelas import JanelaDoSistema, PistaDoApp
from jarvis.tarefas.foco import MotorDeFoco
from jarvis.tarefas.gestor import ErroDeTarefa, FimDaTarefa, Tarefa

DONO = "0x0100000a"


@dataclass
class Relogio:
    t: float = 0.0
    dormidas: int = 0

    def agora(self) -> float:
        return self.t

    def dormir(self, segundos: float) -> None:
        self.dormidas += 1
        self.t += segundos


@dataclass
class Janela:
    id: str
    titulo: str
    classe: str
    pid: int | None
    de: float = 0.0
    ate: float = float("inf")


@dataclass
class Tela:
    """As janelas no tempo, a do dono em foco no começo, e quem o Jarvis pôs na frente."""

    relogio: Relogio
    janelas: list[Janela]
    ativa: str = DONO
    pega_o_foco: bool = True
    """`False` = o gerenciador de janelas diz que sim e não muda nada."""
    ativadas: list[str] = field(default_factory=list)
    cega: bool = False

    def listar(self) -> list[JanelaDoSistema]:
        if self.cega:
            return []
        agora = self.relogio.t
        vivas = [j for j in self.janelas if j.de <= agora < j.ate]
        return [
            JanelaDoSistema(j.id, j.titulo, j.classe, j.pid, ativa=j.id == self.ativa)
            for j in [Janela(DONO, "Documento — Editor", "editor", 300), *vivas]
        ]

    def ativar(self, janela_id: str) -> bool:
        self.ativadas.append(janela_id)
        if self.pega_o_foco:
            self.ativa = janela_id
        return True


@dataclass
class Processos:
    pais: dict[int, int] = field(default_factory=lambda: {801: 800, 950: 940, 940: 930})
    linhas: dict[int, tuple[str, ...]] = field(
        default_factory=lambda: {930: ("/s/reaper", "SteamLaunch", "AppId=480", "--", "/s/sw")}
    )

    def pai(self, pid: int) -> int | None:
        return self.pais.get(pid)

    def executavel(self, pid: int) -> str:
        return ""

    def argumentos(self, pid: int) -> tuple[str, ...]:
        return self.linhas.get(pid, ())


KATE = PistaDoApp("Kate", ("kate",), 800, "kate", id_do_desktop="org.kde.kate")
JOGO = PistaDoApp("Spacewar", ("spacewar",), 800, "steam", jogo_do_steam="480")


def _motor(
    tela: Tela,
    pista: PistaDoApp = KATE,
    *,
    antes: frozenset[str] = frozenset(),
    prazo_s: float = 300.0,
) -> MotorDeFoco:
    return MotorDeFoco(
        pista,
        frozenset({DONO, *antes}),
        tela,
        prazo_s=prazo_s,
        relogio=tela.relogio.agora,
        dormir=tela.relogio.dormir,
        processos=Processos(),
    )


def _rodar(
    motor: MotorDeFoco,
    tela: Tela,
    *,
    cancelado: Callable[[], bool] = lambda: False,
    status: str = "ok",
) -> FimDaTarefa:
    """O gestor, sem linha: cada pedido de foco vira o `ativar` da tela, como no executor."""
    tarefa = Tarefa("t-1", "pôr em foco", "window.focus_app", {"app": "x"}, motor="foco")
    feitos: list[ResultadoDeFerramenta] = []
    for _ in range(8):
        passo = motor.proximo(tarefa, feitos, cancelado)
        if isinstance(passo, FimDaTarefa):
            return passo
        assert passo.tool_id == "window.focus_app"
        if status == "ok":
            tela.ativar(str(passo.args["janela_id"]))
        feitos.append(ResultadoDeFerramenta("window.focus_app", status, motivo="não deixou"))
    raise AssertionError("passos demais")


# --- o que vai para a frente ---------------------------------------------------------------
def test_app_rapido_vai_para_a_frente_e_o_fim_nao_vira_aviso() -> None:
    tela = Tela(Relogio(), [Janela("0x0200000b", "Sem título — Kate", "org.kde.kate", 801, de=1.5)])

    fim = _rodar(_motor(tela), tela)

    assert tela.ativadas == ["0x0200000b"] and tela.ativa == "0x0200000b"
    assert fim.resumo == "Kate abriu e está em foco"
    assert fim.aviso == "", "o dono acabou de ouvir que abriu: o fim fica no card"


def test_jogo_pelo_steam_espera_a_conta_do_dono_e_foca_o_jogo_quando_ele_aparece() -> None:
    """O caso do dono: o Steam abre, pede a conta (quem escolhe é ele), a janela do Steam vem
    depois e o jogo só aparece um minuto e meio mais tarde — pela classe ou pelo reaper."""
    relogio = Relogio()
    tela = Tela(
        relogio,
        [
            Janela("0x0300000c", "Steam - Entrar", "steam", 801, de=2, ate=40),
            Janela("0x0300000d", "Steam", "steam", 801, de=40),
            Janela("0x0400000e", "SW", "spacewar_linux", 950, de=90),
        ],
    )

    fim = _rodar(_motor(tela, JOGO), tela)

    assert tela.ativadas == ["0x0400000e"], "nem a conta nem o Steam: só o jogo"
    assert 90 <= relogio.t < 120
    assert fim.aviso == "Spacewar abriu e está em foco", "demorou: o dono ouve que abriu"


def test_janela_que_ja_abriu_em_foco_nao_e_mexida() -> None:
    tela = Tela(Relogio(), [Janela("0x0200000b", "Kate", "org.kde.kate", 801, de=0.5)])
    tela.ativa = "0x0200000b"  # o gerenciador de janelas já a pôs na frente

    fim = _rodar(_motor(tela), tela)

    assert tela.ativadas == [] and fim.resumo == "Kate abriu e está em foco"


def test_a_janela_de_abertura_some_e_o_foco_vai_para_a_do_app() -> None:
    tela = Tela(
        Relogio(),
        [
            Janela("0x0200000b", "Kate", "org.kde.kate", 801, de=1, ate=3.5),
            Janela("0x0200000c", "Sem título — Kate", "org.kde.kate", 801, de=3.8),
        ],
    )

    fim = _rodar(_motor(tela), tela)

    assert tela.ativadas == ["0x0200000b", "0x0200000c"]
    assert fim.resumo == "Kate abriu e está em foco"


def test_a_janela_que_o_app_ja_tinha_espera_a_carencia_e_perde_para_a_nova() -> None:
    velha = Janela("0x0200000a", "Documento — Kate", "org.kde.kate", 77)
    nova = Janela("0x0200000b", "Sem título — Kate", "org.kde.kate", 801, de=3)
    com_nova = Tela(Relogio(), [velha, nova])
    sem_nova = Tela(Relogio(), [velha])

    _rodar(_motor(com_nova, antes=frozenset({velha.id})), com_nova)
    _rodar(_motor(sem_nova, antes=frozenset({velha.id})), sem_nova)

    assert com_nova.ativadas == [nova.id], "a velha casa pela classe, mas a nova é a do lançamento"
    assert sem_nova.ativadas == [velha.id], "sem janela nova, o app reaproveitou a instância"
    assert sem_nova.relogio.t >= 5


# --- dúvida, palpite e prazo ---------------------------------------------------------------
def test_empate_que_dura_vira_pergunta_ao_dono_e_nada_vai_para_a_frente() -> None:
    tela = Tela(
        Relogio(),
        [
            Janela("0x0200000b", "Kate", "org.kde.kate", 801, de=1),
            Janela("0x0200000c", "Kate", "org.kde.kate", 801, de=1),
        ],
    )

    fim = _rodar(_motor(tela), tela)

    assert tela.ativadas == []
    assert "não ponho nenhuma na frente por palpite: qual delas?" in fim.resumo
    assert fim.aviso == fim.resumo, "a pergunta chega ao dono"


def test_empate_que_some_sozinho_nao_vira_pergunta() -> None:
    tela = Tela(
        Relogio(),
        [
            Janela("0x0200000b", "Kate", "org.kde.kate", 801, de=1, ate=2.5),
            Janela("0x0200000c", "Kate", "org.kde.kate", 801, de=1),
        ],
    )

    fim = _rodar(_motor(tela), tela)

    assert tela.ativadas == ["0x0200000c"] and "qual delas" not in fim.resumo


def test_janela_generica_com_o_nome_nao_vai_para_a_frente_e_o_fim_diz_por_que() -> None:
    tela = Tela(Relogio(), [Janela("0x0500000f", "Spacewar", "qualquer", 77, de=2)])

    with pytest.raises(ErroDeTarefa) as erro:
        _rodar(_motor(tela, JOGO, prazo_s=30.0), tela)

    assert tela.ativadas == []
    assert "esperei 30 s e a janela de Spacewar não apareceu" in str(erro.value)
    assert "«Spacewar»" in str(erro.value) and "sem ligação com o que eu abri" in str(erro.value)


def test_o_prazo_com_a_conta_do_steam_aberta_diz_que_ela_esperou_o_dono() -> None:
    tela = Tela(Relogio(), [Janela("0x0300000c", "Steam - Entrar", "steam", 801, de=1)])

    with pytest.raises(ErroDeTarefa, match="o Steam ficou esperando você escolher a conta"):
        _rodar(_motor(tela, JOGO, prazo_s=20.0), tela)
    assert tela.ativadas == [] and tela.relogio.t >= 20


def test_sem_ver_janela_nenhuma_o_fim_diz_que_nao_deu_para_ver() -> None:
    tela = Tela(Relogio(), [], cega=True)
    with pytest.raises(ErroDeTarefa, match="não consegui ver as janelas do sistema"):
        _rodar(_motor(tela, prazo_s=10.0), tela)


def test_foco_recusado_ou_que_nao_pega_vira_falha_com_a_frase() -> None:
    recusa = Tela(Relogio(), [Janela("0x0200000b", "Kate", "org.kde.kate", 801, de=1)])
    nao_pega = Tela(
        Relogio(), [Janela("0x0200000b", "Kate", "org.kde.kate", 801, de=1)], pega_o_foco=False
    )

    with pytest.raises(ErroDeTarefa, match="não deu para pô-la em foco: não deixou"):
        _rodar(_motor(recusa), recusa, status="erro")
    with pytest.raises(ErroDeTarefa, match="não ficou na frente"):
        _rodar(_motor(nao_pega), nao_pega)


def test_o_botao_de_parar_nao_espera_o_ciclo() -> None:
    relogio = Relogio()
    tela = Tela(relogio, [])

    fim = _rodar(_motor(tela), tela, cancelado=lambda: relogio.dormidas >= 3)

    assert fim.aviso == "" and relogio.t < 1.0, "parou na fatia, não no fim do intervalo"
