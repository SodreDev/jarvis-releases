"""Vocabulário fechado de teclas, classificação de janelas, taxa e parada — tudo puro."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from jarvis.entrada import teclas
from jarvis.entrada.foco import (
    FocoDesconhecido,
    FocoPorKdotool,
    FocoPorXprop,
    Janela,
    categoria_da_janela,
    foco_do_ambiente,
)
from jarvis.entrada.limite import Interruptor, LimiteDeTaxa
from jarvis.executor.comandos import LancadorFalso, Saida


# --- teclas ---------------------------------------------------------------------------------
def test_combinacoes_do_vocabulario() -> None:
    assert teclas.interpretar("Ctrl+L").texto == "ctrl+l"
    assert teclas.interpretar(" shift + tab ".replace(" ", "")).modificadores == ("shift",)
    assert teclas.interpretar("enter").e_enter
    assert teclas.interpretar("alt+left").texto == "alt+left"


@pytest.mark.parametrize(
    "bruta",
    [
        "super+l",  # tecla do sistema
        "meta+a",
        "ctrl+alt+t",  # atalho de sistema
        "ctrl+alt+delete",
        "f5",  # fora da lista
        "printscreen",
        "ctrl+",
        "",
        "ctrl+ctrl+a",
        "a+b",
    ],
)
def test_combinacao_fora_da_lista_e_recusada(bruta: str) -> None:
    with pytest.raises(teclas.TeclaRecusada):
        teclas.interpretar(bruta)


def test_texto_valida_tamanho_e_controle() -> None:
    assert teclas.validar_texto("olá\nmundo")
    for ruim in ("", "a" * 501, "x\x00y", "x\x1by", "x\x7fy"):
        with pytest.raises(teclas.TeclaRecusada):
            teclas.validar_texto(ruim)


def test_keysyms_do_portal() -> None:
    assert teclas.keysym_do_caractere("a") == 0x61
    assert teclas.keysym_do_caractere("é") == 0xE9  # Latin-1: o próprio ponto de código
    assert teclas.keysym_do_caractere("€") == 0x01000000 + 0x20AC
    assert teclas.keysym_do_caractere("\n") == 0xFF0D
    assert teclas.keysym_da_tecla("enter") == 0xFF0D and teclas.keysym_da_tecla("l") == ord("l")


def test_codigos_do_uinput_batem_com_o_kernel() -> None:
    # valores de linux/input-event-codes.h conferidos no header desta máquina
    assert teclas.CODIGO_DE_LETRA["q"] == 16 and teclas.CODIGO_DE_LETRA["a"] == 30
    assert teclas.CODIGO_DE_LETRA["z"] == 44 and teclas.CODIGO_DE_LETRA["m"] == 50
    assert teclas.CODIGO_DE_DIGITO["1"] == 2 and teclas.CODIGO_DE_DIGITO["0"] == 11
    assert teclas.CODIGO_DE_NOME["enter"] == 28 and teclas.CODIGO_DE_NOME["delete"] == 111
    assert teclas.CODIGO_DO_MODIFICADOR == {"ctrl": 29, "shift": 42, "alt": 56}
    assert teclas.teclas_do_uinput("A") == (30, True)
    assert teclas.teclas_do_uinput("a") == (30, False)
    with pytest.raises(teclas.TeclaRecusada, match="layout"):
        teclas.teclas_do_uinput("ç")


# --- classificação de janelas ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("app", "titulo", "esperada"),
    [
        ("org.kde.konsole", "Shell", "terminal"),
        ("Alacritty", "~", "terminal"),
        ("org.keepassxc.KeePassXC", "Cofre", "senha"),
        ("org.kde.polkit-kde-authentication-agent-1", "Autenticação", "autenticacao"),
        ("firefox", "Entrar — Conta", "autenticacao"),
        ("firefox", "Nubank — Conta", "banco"),
        ("firefox", "(3) WhatsApp", "mensageiro"),
        ("chromium", "Instagram", "mensageiro"),
        ("jarvis", "Jarvis", "jarvis"),
        ("dev.sodredev.Jarvis", "qualquer", "jarvis"),
        ("org.kde.kate", "notas.txt — Kate", ""),
        ("firefox", "Wikipédia", ""),
    ],
)
def test_categoria_da_janela(app: str, titulo: str, esperada: str) -> None:
    assert categoria_da_janela(Janela(app, titulo)) == esperada


def test_foco_desconhecido_e_categoria_propria() -> None:
    assert categoria_da_janela(None) == "desconhecida"


def test_kdotool_le_a_janela_ativa_e_o_id_e_conferido_ao_ativar() -> None:
    def resposta(argv: Sequence[str]) -> Saida:
        if "getwindowclassname" in argv:
            return Saida(0, "firefox\n")
        if "getwindowname" in argv:
            return Saida(0, "Wikipédia\n")
        return Saida(0, "{1234-abcd}\n")

    lancador = LancadorFalso(respostas={"kdotool": resposta})
    foco = FocoPorKdotool(lancador)
    assert foco.atual() == Janela("firefox", "Wikipédia", "{1234-abcd}")
    assert foco.ativar(Janela("x", "y", "{1234-abcd}"))
    assert not foco.ativar(Janela("x", "y", "; rm -rf /"))  # id com lixo nunca vira argumento
    assert lancador.chamadas[-1] == ["kdotool", "windowactivate", "{1234-abcd}"]


def test_kdotool_ausente_ou_sem_resposta_e_foco_desconhecido() -> None:
    assert FocoPorKdotool(LancadorFalso(ausentes=frozenset({"kdotool"}))).atual() is None
    assert FocoPorKdotool(LancadorFalso(respostas={"kdotool": Saida(1)})).atual() is None


def test_xprop_le_a_janela_ativa_no_x11() -> None:
    def resposta(argv: Sequence[str]) -> Saida:
        if "-root" in argv:
            return Saida(0, "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4a00007\n")
        return Saida(
            0, 'WM_CLASS(STRING) = "navigator", "firefox"\n_NET_WM_NAME(UTF8_STRING) = "Início"\n'
        )

    foco = FocoPorXprop(LancadorFalso(respostas={"xprop": resposta}))
    assert foco.atual() == Janela("firefox", "Início", "0x4a00007")
    nenhuma = FocoPorXprop(
        LancadorFalso(
            respostas={"xprop": Saida(0, "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n")}
        )
    )
    assert nenhuma.atual() is None


def test_o_leitor_de_foco_depende_da_sessao() -> None:
    sim, nao = (lambda _p: True), (lambda _p: False)
    assert isinstance(foco_do_ambiente({"WAYLAND_DISPLAY": "w0"}, tem=sim), FocoPorKdotool)
    # Wayland sem kdotool: NÃO cai para xprop (que veria só o XWayland e devolveria janela velha)
    assert isinstance(foco_do_ambiente({"WAYLAND_DISPLAY": "w0"}, tem=nao), FocoDesconhecido)
    assert isinstance(foco_do_ambiente({"DISPLAY": ":0"}, tem=sim), FocoPorXprop)
    assert isinstance(foco_do_ambiente({}, tem=sim), FocoDesconhecido)


# --- taxa e parada --------------------------------------------------------------------------
def test_limite_de_taxa_deixa_passar_ate_o_teto_e_depois_diz_quanto_esperar() -> None:
    agora = [0.0]
    limite = LimiteDeTaxa(maximo=3, janela_s=10.0, relogio=lambda: agora[0])
    assert [limite.tentar() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert limite.tentar() == pytest.approx(10.0)
    agora[0] = 4.0
    assert limite.tentar() == pytest.approx(6.0)
    agora[0] = 10.0
    assert limite.tentar() == 0.0  # a primeira saiu da janela


def _parado(interruptor: Interruptor) -> bool:
    return interruptor.parado


def test_interruptor_para_na_hora_roda_os_ganchos_e_so_o_dono_solta(tmp_path: Path) -> None:
    fechou: list[str] = []
    interruptor = Interruptor(tmp_path)
    interruptor.ao_parar(lambda: fechou.append("portal"))

    def quebrado() -> None:
        raise RuntimeError("gancho quebrado")

    interruptor.ao_parar(quebrado)  # gancho quebrado não impede os outros
    interruptor.ao_parar(lambda: fechou.append("uinput"))
    assert _parado(interruptor) is False
    interruptor.parar("botão da janela")
    assert _parado(interruptor) is True and fechou == ["portal", "uinput"]
    assert interruptor.motivo == "botão da janela"
    interruptor.liberar()
    assert _parado(interruptor) is False


def test_arquivo_parada_para_a_entrada_de_fora_do_processo(tmp_path: Path) -> None:
    interruptor = Interruptor(tmp_path)
    (tmp_path / "PARADA").touch()
    assert _parado(interruptor) is True
    interruptor.liberar()
    assert not (tmp_path / "PARADA").exists() and _parado(interruptor) is False
