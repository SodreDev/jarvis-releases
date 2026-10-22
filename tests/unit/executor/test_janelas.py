"""As janelas do sistema e a evidência de qual é a do app aberto (dono, 2026-10-20, C4; ADR-0037).

Sem janela nenhuma: o `kdotool`, o `wmctrl` e o `xprop` são um `LancadorFalso`, e os processos
(pai, executável, linha de comando) são um dicionário. O que se prova: a lista sai com a janela
em primeiro plano marcada; só a evidência (PID, jogo do Steam, classe, executável) põe uma janela
em foco — nome no título e janela nova não bastam —; empate é dúvida; a janela de entrar na conta
do Steam é do dono; e o ambiente escolhe quem lista como a entrada virtual escolhe.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.comandos import LancadorFalso, Saida, ambiente_do_programa
from jarvis.executor.janelas import (
    EstadoDasJanelas,
    JanelaDoSistema,
    JanelasPorKdotool,
    JanelasPorWmctrl,
    PistaDoApp,
    ProcessosDoProc,
    avaliar,
    descendente,
    estado_do_kwin,
    focar,
    foco_para_o_modelo,
    janelas_do_ambiente,
    jogo_do_steam,
    listar_para_o_modelo,
)

U1 = "{11111111-1111-1111-1111-111111111111}"
U2 = "{22222222-2222-2222-2222-222222222222}"
U3 = "{33333333-3333-3333-3333-333333333333}"
U4 = "{44444444-4444-4444-4444-444444444444}"
U5 = "{55555555-5555-5555-5555-555555555555}"
U6 = "{66666666-6666-6666-6666-666666666666}"
U7 = "{77777777-7777-7777-7777-777777777777}"


# --- quem lista ----------------------------------------------------------------------------
def _kwin(ativa: str = U3, **mudar: dict[str, Any]) -> str:
    """A resposta da `CONSULTA_DO_KWIN` no formato que o KWin 6.7.5 virtual deu (dois monitores,
    2026-10-21): o Brave (Wayland) e outro Brave (XWayland) no principal, o Jarvis ativo no
    segundo, a área de trabalho do Plasma em cada monitor, um app minimizado e um noutra área de
    trabalho."""
    janelas = {
        U1: {
            "titulo": "YouTube - Brave",
            "classe": "brave-browser",
            "pid": 4001,
            "tela": "DP-1",
            "pilha": 4,
        },
        U2: {
            "titulo": "G1 - Brave",
            "classe": "brave-browser",
            "pid": 4002,
            "tela": "DP-1",
            "pilha": 3,
        },
        U3: {"titulo": "Jarvis", "classe": "jarvis", "pid": 4003, "tela": "HDMI-A-1", "pilha": 5},
        U4: {
            "titulo": "Área de trabalho",
            "classe": "plasmashell",
            "pid": 900,
            "tela": "DP-1",
            "pilha": 0,
            "normal": False,
        },
        U5: {
            "titulo": "Área de trabalho",
            "classe": "plasmashell",
            "pid": 900,
            "tela": "HDMI-A-1",
            "pilha": 1,
            "normal": False,
        },
        U6: {
            "titulo": "Discord",
            "classe": "discord",
            "pid": 4006,
            "tela": "HDMI-A-1",
            "pilha": 9,
            "minimizada": True,
        },
        U7: {
            "titulo": "Steam",
            "classe": "steam",
            "pid": 4007,
            "tela": "DP-1",
            "pilha": 8,
            "nesta_mesa": False,
        },
    }
    for janela_id, campos in mudar.items():
        janelas[janela_id] |= campos
    base = {"minimizada": False, "normal": True, "nesta_mesa": True}
    dados = {
        "versao": 1,
        "ativa": ativa,
        "tela_ativa": "HDMI-A-1",
        "telas": [
            {"nome": "DP-1", "x": 0, "y": 0, "largura": 2560, "altura": 1440},
            {"nome": "HDMI-A-1", "x": 2560, "y": 0, "largura": 1920, "altura": 1080},
        ],
        "janelas": [{"id": i} | base | c for i, c in janelas.items()],
    }
    return json.dumps(dados) + "\n"


def test_o_kwin_diz_numa_chamada_a_ativa_o_monitor_e_a_da_frente_de_cada_monitor() -> None:
    """O caso do dono (2026-10-21): o Brave na frente do monitor principal e o Jarvis ativo no
    outro. A leitura de antes só sabia a ativa — o Brave era «segundo plano»."""
    lancar = LancadorFalso(respostas={"kdotool": Saida(0, _kwin())})

    estado = JanelasPorKdotool(lancar).estado()

    assert estado is not None and len(lancar.chamadas) == 1
    assert lancar.chamadas[0][:3] == ["kdotool", "kwinscript", "--inline"]
    assert [(m.nome, m.principal) for m in estado.monitores] == [
        ("DP-1", True),
        ("HDMI-A-1", False),
    ]
    assert estado.ativa is not None and estado.ativa.titulo == "Jarvis"
    assert estado.ativa.monitor == "HDMI-A-1" and not estado.ativa.principal
    frente = estado.da_frente("DP-1")
    assert frente is not None and frente.titulo == "YouTube - Brave" and frente.principal
    segundo = estado.da_frente("HDMI-A-1")
    assert segundo is not None and segundo.titulo == "Jarvis", (
        "o Discord minimizado está mais alto na pilha, mas não está à vista"
    )
    steam = next(j for j in estado.janelas if j.titulo == "Steam")
    assert not steam.na_frente and not steam.visivel, "noutra área de trabalho não está na frente"
    assert not any(j.na_frente for j in estado.janelas if j.classe == "plasmashell")


def test_sem_janela_ativa_a_lista_continua_vindo() -> None:
    """No KWin virtual, com tudo minimizado o `getactivewindow` estoura em `null` e a busca
    encadeada de antes devolvia lista vazia («não vejo janela nenhuma»)."""
    estado = JanelasPorKdotool(LancadorFalso(respostas={"kdotool": Saida(0, _kwin(ativa=""))}))

    lido = estado.estado()

    assert lido is not None and lido.ativa is None and len(lido.janelas) == 7
    assert foco_para_o_modelo(_Porta(lido))["sem_foco"].startswith("nenhuma janela está ativa")


@pytest.mark.parametrize(
    "bruto",
    [
        "não é json\n",
        json.dumps({"janelas": [{"id": "rm -rf"}]}),
        json.dumps({"telas": [{"nome": "DP-1; x"}], "janelas": []}),
        json.dumps({"janelas": "nada"}),
    ],
)
def test_resposta_fora_do_formato_nao_vira_estado(bruto: str) -> None:
    assert estado_do_kwin(bruto) is None


@dataclass
class _Porta:
    """Uma porta que já tem o estado (para as funções do modelo)."""

    lido: EstadoDasJanelas | None
    ativadas: list[str] = field(default_factory=list)

    def estado(self) -> EstadoDasJanelas | None:
        return self.lido

    def listar(self) -> list[JanelaDoSistema]:
        return list(self.lido.janelas) if self.lido is not None else []

    def ativar(self, janela_id: str) -> bool:
        self.ativadas.append(janela_id)
        return True


def test_a_resposta_de_em_foco_diz_a_ativa_e_a_da_frente_do_principal() -> None:
    lido = estado_do_kwin(_kwin())
    assert lido is not None

    resposta = foco_para_o_modelo(_Porta(lido))

    assert resposta["foco"] == {
        "id": U3,
        "app": "jarvis",
        "titulo": "Jarvis",
        "monitor": "HDMI-A-1",
        "principal": False,
    }
    principal, segundo = resposta["monitores"]
    assert principal["principal"] and not principal["do_teclado"]
    assert principal["na_frente"]["titulo"] == "YouTube - Brave"
    assert principal["na_frente"]["app"] == "brave-browser"
    assert segundo["do_teclado"] and segundo["na_frente"]["titulo"] == "Jarvis"


def test_a_lista_do_modelo_traz_o_monitor_e_a_da_frente_primeiro() -> None:
    lido = estado_do_kwin(_kwin())
    assert lido is not None

    lista = listar_para_o_modelo(_Porta(lido))

    titulos = [j["titulo"] for j in lista["janelas"]]
    assert titulos[:2] == ["Jarvis", "YouTube - Brave"], "a ativa e a da frente primeiro"
    assert "Área de trabalho" not in titulos, "a casca do desktop não é janela de app"
    brave = next(j for j in lista["janelas"] if j["titulo"] == "YouTube - Brave")
    assert brave["monitor"] == "DP-1" and brave["principal"] and brave["na_frente_do_monitor"]
    discord = next(j for j in lista["janelas"] if j["titulo"] == "Discord")
    assert discord["minimizada"] is True
    assert lista["monitores"] == [
        {"monitor": "DP-1", "principal": True},
        {"monitor": "HDMI-A-1", "principal": False},
    ]


def test_kdotool_sem_kwinscript_vale_a_busca_encadeada_e_nao_pergunta_de_novo() -> None:
    def kdotool(argv: Sequence[str]) -> Saida:
        if argv[1] == "kwinscript":
            return Saida(2, "", "error: unexpected argument 'kwinscript' found")
        if argv[1] == "getactivewindow":
            return Saida(0, U2 + "\n")
        saida = [U1, U2, "Documento — Editor", "Spacewar", "org.kde.kate", "steam_app_480"]
        return Saida(0, "\n".join([*saida, "812", "0"]) + "\n")

    lancar = LancadorFalso(respostas={"kdotool": kdotool})
    porta = JanelasPorKdotool(lancar)

    janelas = porta.listar()
    porta.listar()

    assert janelas == [
        JanelaDoSistema(U1, "Documento — Editor", "org.kde.kate", 812, ativa=False),
        JanelaDoSistema(U2, "Spacewar", "steam_app_480", None, ativa=True),
    ]
    assert [c[1] for c in lancar.chamadas].count("kwinscript") == 1, "lembra que não tem"
    assert foco_para_o_modelo(porta)["aviso"].startswith("esta leitura não diz o monitor")


def test_na_busca_encadeada_sem_janela_ativa_a_lista_vem_assim_mesmo() -> None:
    def kdotool(argv: Sequence[str]) -> Saida:
        if argv[1] == "kwinscript":
            return Saida(2, "", "error: unexpected argument 'kwinscript' found")
        if argv[1] == "getactivewindow":  # o `null` do KWin: «Cannot read property…»
            return Saida(1, "", "ERROR: Script error: TypeError: Cannot read property")
        return Saida(0, "\n".join([U1, "Documento — Editor", "org.kde.kate", "812"]) + "\n")

    janelas = JanelasPorKdotool(LancadorFalso(respostas={"kdotool": kdotool})).listar()

    assert janelas == [JanelaDoSistema(U1, "Documento — Editor", "org.kde.kate", 812)]


def test_titulo_com_quebra_de_linha_desalinha_e_vale_o_caminho_lento() -> None:
    def kdotool(argv: Sequence[str]) -> Saida:
        if argv[1] == "kwinscript":
            return Saida(2, "", "error: unexpected argument 'kwinscript' found")
        if "getwindowid" in argv:  # o título «linha 1\nlinha 2» desalinha os blocos
            return Saida(0, "\n".join([U1, "linha 1", "linha 2", "kate", "812"]) + "\n")
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


@pytest.mark.parametrize(
    ("programa", "ambiente", "esperado"),
    [
        ("kdotool", {"XDG_CURRENT_DESKTOP": "KDE", "PATH": "/usr/bin"}, "6"),
        ("kdotool", {"XDG_CURRENT_DESKTOP": "KDE", "KDE_SESSION_VERSION": "6"}, None),
        ("kdotool", {"XDG_CURRENT_DESKTOP": "GNOME"}, None),
        ("wmctrl", {"XDG_CURRENT_DESKTOP": "KDE"}, None),
    ],
)
def test_o_kdotool_ganha_a_versao_do_kde_quando_ela_nao_chegou_ao_jarvis(
    programa: str, ambiente: dict[str, str], esperado: str | None
) -> None:
    """O kdotool 0.3 sai com «Unsupported KDE version» sem `KDE_SESSION_VERSION=6`."""
    filho = ambiente_do_programa(programa, ambiente)
    if esperado is None:
        assert filho is None, "o mesmo ambiente do Jarvis"
    else:
        assert filho is not None and filho["KDE_SESSION_VERSION"] == esperado
        assert filho["PATH"] == "/usr/bin", "o resto do ambiente fica como estava"


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
