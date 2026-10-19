"""O backend `uinput` com um dispositivo falso: bytes e `ioctl` conferidos, kernel nenhum tocado."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import pytest

from jarvis.entrada import uinput
from jarvis.entrada.porta import EntradaIndisponivel
from jarvis.entrada.teclas import TeclaRecusada


@dataclass
class DispositivoFalso(uinput.Dispositivo):
    aberto: bool = False
    ioctls: list[tuple[int, int | bytes]] = field(default_factory=list)
    escritas: list[bytes] = field(default_factory=list)
    nao_abre: bool = False
    falha_no_create: bool = False

    def __init__(self, nao_abre: bool = False, falha_no_create: bool = False) -> None:
        self.caminho = "falso"
        self.aberto = False
        self.ioctls = []
        self.escritas = []
        self.nao_abre = nao_abre
        self.falha_no_create = falha_no_create

    def abrir(self) -> None:
        if self.nao_abre:
            raise EntradaIndisponivel("sem acesso a /dev/uinput (Permission denied)")
        self.aberto = True

    def ioctl(self, pedido: int, argumento: int | bytes = 0) -> None:
        if self.falha_no_create and pedido == uinput.UI_DEV_CREATE:
            raise OSError("recusado")
        self.ioctls.append((pedido, argumento))

    def escrever(self, dados: bytes) -> None:
        self.escritas.append(dados)

    def fechar(self) -> None:
        self.aberto = False

    def eventos(self) -> list[tuple[int, int, int]]:
        formato = struct.Struct(uinput.FORMATO_DO_EVENTO)
        saida = []
        for bruto in self.escritas:
            assert len(bruto) == formato.size == 24
            _s, _u, tipo, codigo, valor = formato.unpack(bruto)
            saida.append((tipo, codigo, valor))
        return saida


def _backend(**falhas: bool) -> tuple[uinput.EntradaPorUinput, DispositivoFalso]:
    dispositivo = DispositivoFalso(**falhas)
    return uinput.EntradaPorUinput(dispositivo, dormir=lambda _s: None), dispositivo


def test_numeros_dos_ioctl_batem_com_o_header_do_kernel() -> None:
    # valores de linux/uinput.h para 64 bits, conferidos pela fórmula _IOC
    assert uinput.UI_DEV_CREATE == 0x5501 and uinput.UI_DEV_DESTROY == 0x5502
    assert uinput.UI_DEV_SETUP == 0x405C5503
    assert uinput.UI_SET_EVBIT == 0x40045564
    assert uinput.UI_SET_KEYBIT == 0x40045565 and uinput.UI_SET_RELBIT == 0x40045566
    assert uinput.TAMANHO_DO_SETUP == 92


def test_cria_o_dispositivo_com_nome_proprio_antes_do_primeiro_evento() -> None:
    backend, dispositivo = _backend()
    backend.clicar("esquerdo", 1)
    pedidos = [p for p, _ in dispositivo.ioctls]
    assert pedidos[-2:] == [uinput.UI_DEV_SETUP, uinput.UI_DEV_CREATE]
    setup = dict(dispositivo.ioctls)[uinput.UI_DEV_SETUP]
    assert isinstance(setup, bytes) and len(setup) == 92
    assert b"Jarvis (entrada virtual)" in setup
    assert (uinput.UI_SET_KEYBIT, 0x110) in dispositivo.ioctls  # botão esquerdo declarado
    # só cria uma vez
    backend.clicar("esquerdo", 1)
    assert [p for p, _ in dispositivo.ioctls].count(uinput.UI_DEV_CREATE) == 1


def test_clique_e_apertar_e_soltar_com_sincronizacao() -> None:
    backend, dispositivo = _backend()
    backend.clicar("direito", 2)
    eventos = dispositivo.eventos()
    teclas = [(c, v) for t, c, v in eventos if t == uinput.EV_KEY]
    assert teclas == [(0x111, 1), (0x111, 0)] * 2
    assert eventos.count((uinput.EV_SYN, uinput.SYN_REPORT, 0)) == 4


def test_mover_quebra_em_passos_e_soma_o_deslocamento_exato() -> None:
    backend, dispositivo = _backend()
    backend.mover(130, -75)
    rel = [(c, v) for t, c, v in dispositivo.eventos() if t == uinput.EV_REL]
    assert sum(v for c, v in rel if c == uinput.REL_X) == 130
    assert sum(v for c, v in rel if c == uinput.REL_Y) == -75
    assert max(abs(v) for _, v in rel) <= uinput.PASSO_DO_PONTEIRO


def test_digitar_usa_shift_so_nas_maiusculas() -> None:
    backend, dispositivo = _backend()
    backend.digitar("Oi 1\n")
    teclas = [(c, v) for t, c, v in dispositivo.eventos() if t == uinput.EV_KEY]
    assert teclas == [
        (42, 1), (24, 1), (24, 0), (42, 0),  # Shift+o
        (23, 1), (23, 0),  # i
        (57, 1), (57, 0),  # espaço
        (2, 1), (2, 0),  # 1
        (28, 1), (28, 0),  # Enter
    ]  # fmt: skip


def test_texto_com_caractere_de_layout_nao_sai_nem_pela_metade() -> None:
    backend, dispositivo = _backend()
    with pytest.raises(TeclaRecusada, match="layout"):
        backend.digitar("abc ç")
    assert dispositivo.escritas == [] and dispositivo.ioctls == []  # nem o dispositivo nasceu


def test_modificador_nunca_fica_preso() -> None:
    backend, dispositivo = _backend()
    backend.pressionar(("ctrl", "shift"), "l")
    teclas = [(c, v) for t, c, v in dispositivo.eventos() if t == uinput.EV_KEY]
    assert teclas == [(29, 1), (42, 1), (38, 1), (38, 0), (42, 0), (29, 0)]


def test_sem_permissao_no_uinput_a_frase_diz_o_que_o_dono_faz() -> None:
    backend, _ = _backend(nao_abre=True)
    with pytest.raises(EntradaIndisponivel, match="uinput"):
        backend.mover(1, 1)


def test_kernel_que_recusa_criar_fecha_e_avisa() -> None:
    backend, dispositivo = _backend(falha_no_create=True)
    with pytest.raises(EntradaIndisponivel, match="kernel recusou"):
        backend.mover(1, 1)
    assert not dispositivo.aberto


def test_fechar_destroi_o_dispositivo() -> None:
    backend, dispositivo = _backend()
    backend.clicar("meio", 1)
    backend.fechar()
    assert dispositivo.ioctls[-1][0] == uinput.UI_DEV_DESTROY and not dispositivo.aberto
