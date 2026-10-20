"""As janelas do sistema e a evidência de qual é a do app aberto (dono, 2026-10-20, C4; ADR-0037).

Sem janela nenhuma: o `kdotool`, o `wmctrl` e o `xprop` são um `LancadorFalso`, e os processos
(pai, executável, linha de comando) são um dicionário. O que se prova: a lista sai com a janela
em primeiro plano marcada; só a evidência (PID, jogo do Steam, classe, executável) põe uma janela
em foco — nome no título e janela nova não bastam —; empate é dúvida; a janela de entrar na conta
do Steam é do dono; e o ambiente escolhe quem lista como a entrada virtual escolhe.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from jarvis.executor.comandos import LancadorFalso, Saida
from jarvis.executor.janelas import (
    JanelaDoSistema,
    JanelasPorKdotool,
    JanelasPorWmctrl,
    PistaDoApp,
    ProcessosDoProc,
    avaliar,
    descendente,
    focar,
    janelas_do_ambiente,
    jogo_do_steam,
    listar_para_o_modelo,
)

U1 = "{11111111-1111-1111-1111-111111111111}"
U2 = "{22222222-2222-2222-2222-222222222222}"
U3 = "{33333333-3333-3333-3333-333333333333}"


# --- quem lista ----------------------------------------------------------------------------
def test_o_kdotool_lista_tudo_numa_chamada_so_com_a_janela_ativa_marcada() -> None:
    saida = "\n".join(
        [U1, U2, "Documento — Editor", "Spacewar", "org.kde.kate", "steam_app_480", "812", "0", U2]
    )
    lancar = LancadorFalso(respostas={"kdotool": Saida(0, saida + "\n")})

    janelas = JanelasPorKdotool(lancar).listar()

    assert janelas == [
        JanelaDoSistema(U1, "Documento — Editor", "org.kde.kate", 812, ativa=False),
        JanelaDoSistema(U2, "Spacewar", "steam_app_480", None, ativa=True),
    ]
    assert len(lancar.chamadas) == 1, "uma chamada por ciclo, não uma por janela"
    assert lancar.chamadas[0][:4] == ["kdotool", "search", "--class", "."]


def test_titulo_com_quebra_de_linha_desalinha_e_vale_o_caminho_lento() -> None:
    def kdotool(argv: Sequence[str]) -> Saida:
        if "getwindowid" in argv:  # o título «linha 1\nlinha 2» desalinha os blocos
            return Saida(0, "\n".join([U1, "linha 1", "linha 2", "kate", "812", U1]) + "\n")
        respostas = {
            ("search", "--class", "."): U1,
            ("getactivewindow",): U1,
            ("getwindowname", U1): "linha 1",
            ("getwindowclassname", U1): "kate",
            ("getwindowpid", U1): "812",
        }
        return Saida(0, respostas[tuple(argv[1:])] + "\n")

    janelas = JanelasPorKdotool(LancadorFalso(respostas={"kdotool": kdotool})).listar()

    assert janelas == [JanelaDoSistema(U1, "linha 1", "kate", 812, ativa=True)]


def test_o_wmctrl_lista_com_pid_e_classe_e_o_xprop_diz_a_ativa() -> None:
    lancar = LancadorFalso(
        respostas={
            "wmctrl": Saida(
                0,
                "0x03a00003  0 812    kate.Kate             maquina Documento — Editor\n"
                "0x01e00004 -1 700    plasmashell.plasmashell maquina Painel\n"
                "0x04200007  0 0      steam_app_480.steam_app_480 maquina Spacewar\n"
                "0x04400001  0 901    xterm.XTerm           maquina N/A\n",
            ),
            "xprop": Saida(0, "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4200007, 0x0\n"),
        }
    )

    janelas = JanelasPorWmctrl(lancar).listar()

    assert janelas == [
        JanelaDoSistema("0x03a00003", "Documento — Editor", "Kate", 812, ativa=False),
        JanelaDoSistema("0x04200007", "Spacewar", "steam_app_480", None, ativa=True),
        JanelaDoSistema("0x04400001", "", "XTerm", 901, ativa=False),  # título que ele não leu
    ]


def test_sem_o_programa_a_lista_e_vazia_e_o_foco_nao_acontece() -> None:
    ausente = LancadorFalso(ausentes=frozenset({"kdotool", "wmctrl", "xprop"}))
    assert JanelasPorKdotool(ausente).listar() == []
    assert JanelasPorWmctrl(ausente).listar() == []
    assert not JanelasPorKdotool(ausente).ativar(U1)
    assert not JanelasPorWmctrl(ausente).ativar("0x03a00003")


@pytest.mark.parametrize("porta", [JanelasPorKdotool, JanelasPorWmctrl])
@pytest.mark.parametrize("janela_id", ["1; reboot", "--help", "0x", "{abc}", ""])
def test_id_que_nao_e_de_janela_nem_chega_ao_programa(porta: type, janela_id: str) -> None:
    lancar = LancadorFalso()
    assert not porta(lancar).ativar(janela_id)
    assert lancar.chamadas == []


@pytest.mark.parametrize(
    ("ambiente", "instalados", "esperado"),
    [
        (
            {"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "KDE"},
            {"kdotool"},
            JanelasPorKdotool,
        ),
        ({"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "KDE"}, {"wmctrl", "xprop"}, None),
        ({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "GNOME"}, {"kdotool"}, None),
        ({"DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "KDE"}, {"kdotool", "wmctrl"}, JanelasPorKdotool),
        ({"DISPLAY": ":0"}, {"wmctrl", "xprop"}, JanelasPorWmctrl),
        ({"DISPLAY": ":0"}, {"wmctrl"}, None),
        ({}, {"kdotool", "wmctrl", "xprop"}, None),
    ],
)
def test_o_ambiente_escolhe_quem_ve_as_janelas_como_na_entrada_virtual(
    ambiente: dict[str, str], instalados: set[str], esperado: type | None
) -> None:
    porta = janelas_do_ambiente(ambiente, LancadorFalso(), tem=instalados.__contains__)
    assert (type(porta) if porta is not None else None) is esperado


# --- as window.* com a porta ---------------------------------------------------------------
@dataclass
class JanelasFalsas:
    janelas: list[JanelaDoSistema]
    ativadas: list[str] = field(default_factory=list)

    def listar(self) -> list[JanelaDoSistema]:
        return list(self.janelas)

    def ativar(self, janela_id: str) -> bool:
        self.ativadas.append(janela_id)
        return True


def test_focar_pelo_id_confere_na_lista_e_pelo_nome_escolhe_o_codigo() -> None:
    porta = JanelasFalsas(
        [
            JanelaDoSistema(U1, "Documento — Editor", "org.kde.kate", 812, ativa=True),
            JanelaDoSistema(U2, "Spacewar", "steam_app_480", 900),
        ]
    )

    assert focar(porta, "Spacewar", U2)["janela_id"] == U2
    assert focar(porta, "kate")["janela_id"] == U1  # já em foco: não mexe
    with pytest.raises(ValueError, match="não está mais aberta"):
        focar(porta, "Spacewar", U3)
    assert porta.ativadas == [U2]


def test_a_lista_do_modelo_diz_o_primeiro_plano_e_tira_a_casca_do_desktop() -> None:
    porta = JanelasFalsas(
        [
            JanelaDoSistema(U1, "Documento — Editor", "org.kde.kate", 812, ativa=True),
            JanelaDoSistema(U2, "Área de trabalho", "plasmashell", 700),
            JanelaDoSistema(U3, "", "org.kde.kwin", 701),
        ]
    )
    assert listar_para_o_modelo(porta) == {
        "janelas": [
            {
                "id": U1,
                "app": "org.kde.kate",
                "titulo": "Documento — Editor",
                "primeiro_plano": True,
            }
        ]
    }


# --- os processos --------------------------------------------------------------------------
@dataclass
class ProcessosFalsos:
    pais: dict[int, int] = field(default_factory=dict)
    executaveis: dict[int, str] = field(default_factory=dict)
    linhas: dict[int, tuple[str, ...]] = field(default_factory=dict)

    def pai(self, pid: int) -> int | None:
        return self.pais.get(pid)

    def executavel(self, pid: int) -> str:
        return self.executaveis.get(pid, "")

    def argumentos(self, pid: int) -> tuple[str, ...]:
        return self.linhas.get(pid, ())


def test_descendente_sobe_pelos_pais_e_o_jogo_vem_do_reaper_do_steam() -> None:
    processos = ProcessosFalsos(
        pais={903: 902, 902: 901, 901: 500, 500: 1},
        linhas={901: ("/home/d/.steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=480", "--")},
    )
    assert descendente(903, 901, processos.pai)
    assert not descendente(903, 77, processos.pai)
    assert jogo_do_steam(903, processos) == "480"
    assert jogo_do_steam(500, processos) == ""


def test_o_proc_de_verdade_le_o_proprio_processo() -> None:
    proc = ProcessosDoProc()
    assert proc.pai(os.getpid()) == os.getppid()
    assert proc.executavel(os.getpid()).startswith("python")
    assert proc.argumentos(os.getpid())
    assert proc.pai(2**30) is None and proc.executavel(2**30) == ""


def test_a_pista_le_o_jogo_do_steam_e_a_classe_do_desktop(tmp_path: Path) -> None:
    desktop = tmp_path / "jogo.desktop"
    desktop.write_text("[Desktop Entry]\nName=Jogo\nStartupWMClass=JogoBom\n", "utf-8")

    jogo = PistaDoApp.do_app("Spacewar", ("spacewar",), ("steam", "steam://rungameid/480"), 7)
    outro = PistaDoApp.do_app("Jogo", (), ("steam", "-applaunch", "570"), 7, arquivo=desktop)
    kate = PistaDoApp.do_app("Kate", (), ("kate", "-b"), 7, id_do_desktop="org.kde.kate")

    assert (jogo.jogo_do_steam, outro.jogo_do_steam, outro.classe_do_desktop) == (
        "480",
        "570",
        "JogoBom",
    )
    assert "steam" not in jogo.classes, "num jogo, o steam é o lançador"
    assert kate.classes == {"org.kde.kate", "kate"}


# --- a evidência ---------------------------------------------------------------------------
def _j(
    janela_id: str, titulo: str, classe: str, pid: int | None, ativa: bool = False
) -> JanelaDoSistema:
    return JanelaDoSistema(janela_id, titulo, classe, pid, ativa)


KATE = PistaDoApp("Kate", ("kate", "editor kate"), 800, "kate", "", "org.kde.kate")
JOGO = PistaDoApp("Spacewar", ("spacewar",), 800, "steam", jogo_do_steam="480")
PROCESSOS = ProcessosFalsos(
    pais={801: 800, 950: 940, 940: 930, 930: 600},
    executaveis={812: "firefox", 700: "python3"},
    linhas={930: ("/s/reaper", "SteamLaunch", "AppId=480", "--", "/s/jogo")},
)


@pytest.mark.parametrize(
    ("janelas", "pista", "esperado", "razoes"),
    [
        # o PID: a janela é do processo lançado (ou de um filho dele)
        ([_j(U1, "Sem título", "x", 801)], KATE, U1, {"pid", "nova"}),
        # a classe do app (o app_id do Wayland é o id do .desktop) com a janela nova
        ([_j(U1, "Sem título", "org.kde.kate", 77)], KATE, U1, {"classe", "nova"}),
        # nome no título e janela nova, sem ligação com o lançado: palpite, não foca
        ([_j(U1, "Kate", "outra", 77)], KATE, None, set()),
        # classe genérica (python3) não diz qual app é
        ([_j(U1, "Kate", "python3", 700)], PistaDoApp("Kate", (), 800, "python3"), None, set()),
        # o jogo pela classe que o Steam/Proton dá
        ([_j(U1, "Spacewar", "steam_app_480", 77)], JOGO, U1, {"jogo do Steam", "nova", "título"}),
        # o jogo nativo pelo reaper do Steam com o AppId, acima do processo da janela
        ([_j(U1, "SW", "spacewar_linux", 950)], JOGO, U1, {"jogo do Steam", "nova"}),
        # a janela do Steam que descende do lançado não é o jogo (o PID não vale num jogo)
        ([_j(U1, "Spacewar", "steamwebhelper", 801)], JOGO, None, set()),
        # abrir o próprio Steam: a janela dele é o alvo
        (
            [_j(U1, "Steam", "steam", 801)],
            PistaDoApp("Steam", ("steam",), 800, "steam"),
            U1,
            {"pid", "classe", "nova", "título"},
        ),
        # a casca do desktop nunca é o app
        ([_j(U1, "Kate", "plasmashell", 801)], KATE, None, set()),
    ],
)
def test_so_a_evidencia_poe_uma_janela_em_foco(
    janelas: list[JanelaDoSistema],
    pista: PistaDoApp,
    esperado: str | None,
    razoes: set[str],
) -> None:
    leitura = avaliar(janelas, pista, frozenset(), processos=PROCESSOS)
    assert (leitura.alvo.janela.id if leitura.alvo else None) == esperado
    if leitura.alvo is not None:
        assert set(leitura.alvo.razoes) == razoes


def test_a_janela_generica_com_o_nome_fica_como_fraca_para_a_mensagem_honesta() -> None:
    leitura = avaliar([_j(U1, "Spacewar", "qualquer", 77)], JOGO, frozenset(), processos=PROCESSOS)
    assert leitura.alvo is None and [e.janela.id for e in leitura.fracas] == [U1]


def test_empate_entre_fortes_e_duvida_e_nenhuma_e_escolhida() -> None:
    leitura = avaliar(
        [_j(U1, "Kate", "org.kde.kate", 801), _j(U2, "Kate", "org.kde.kate", 801)],
        KATE,
        frozenset(),
        processos=PROCESSOS,
    )
    assert leitura.alvo is None and {e.janela.id for e in leitura.duvida} == {U1, U2}


def test_a_janela_de_entrar_na_conta_do_steam_e_do_dono() -> None:
    leitura = avaliar(
        [_j(U1, "Steam - Entrar", "steam", 801), _j(U2, "Steam", "steam", 801)],
        JOGO,
        frozenset(),
        processos=PROCESSOS,
    )
    assert leitura.alvo is None and leitura.duvida == () and leitura.conta_do_steam


def test_a_janela_que_ja_existia_so_vale_depois_da_carencia() -> None:
    velha = _j(U1, "Documento — Kate", "org.kde.kate", 77)
    nova = _j(U2, "Sem título — Kate", "org.kde.kate", 801)

    cedo = avaliar([velha], KATE, frozenset({U1}), processos=PROCESSOS, velhas_valem=False)
    depois = avaliar([velha], KATE, frozenset({U1}), processos=PROCESSOS)
    com_a_nova = avaliar([velha, nova], KATE, frozenset({U1}), processos=PROCESSOS)

    assert cedo.alvo is None
    assert depois.alvo is not None and depois.alvo.janela.id == U1  # o app reaproveitou a instância
    assert com_a_nova.alvo is not None and com_a_nova.alvo.janela.id == U2


def test_a_instancia_que_ja_rodava_vale_pelo_executavel() -> None:
    """O Firefox aberto recebe o pedido e abre a janela nova no processo antigo (sem PID)."""
    firefox = PistaDoApp("Firefox", ("firefox",), 800, "firefox")
    leitura = avaliar(
        [_j(U1, "Nova aba — Mozilla Firefox", "outra-classe", 812)],
        firefox,
        frozenset(),
        processos=PROCESSOS,
    )
    assert leitura.alvo is not None and set(leitura.alvo.razoes) == {"executável", "nova", "título"}
