"""A ligação das `input.*` ao laço de voz: opt-in do dono e parada compartilhada."""

from __future__ import annotations

from pathlib import Path

from jarvis.entrada.escolha import EntradaComReserva, backend_do_ambiente
from jarvis.entrada.porta import EntradaIndisponivel
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao, escrever, ler

BASE = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco", acesso="padrao")


def _app(tmp_path: Path, **mudancas: object) -> Aplicativo:
    raiz = tmp_path / "sessao"
    raiz.mkdir(parents=True, exist_ok=True)
    return Aplicativo(
        configuracao=BASE.com(**mudancas),
        raiz=raiz,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "WAYLAND_DISPLAY": "wayland-9"},
        lar=tmp_path / "casa",
    )


def test_padrao_desligado_as_input_nao_aparecem(tmp_path: Path) -> None:
    assert BASE.entrada_virtual is False and BASE.entrada_uinput is False
    ids = {t["id"] for t in _app(tmp_path)._montar_ferramentas().catalogo_para_o_modelo()}
    assert not {i for i in ids if i.startswith("input.")}


def test_ligada_o_modelo_ve_as_quatro_tools_e_o_controle_sobrevive_a_remontagem(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path, entrada_virtual=True)
    primeiro = app._montar_ferramentas()
    ids = {t["id"] for t in primeiro.catalogo_para_o_modelo()}
    assert {"input.mouse.move", "input.mouse.click", "input.key.type", "input.key.press"} <= ids
    assert "input.acao_sensivel" not in ids
    segundo = app._montar_ferramentas()
    assert primeiro.entrada is segundo.entrada  # não reabre o diálogo do sistema
    assert primeiro.entrada is not None
    assert primeiro.entrada.interruptor is app.interruptor_de_entrada


def test_o_botao_de_parar_bloqueia_a_entrada_e_a_parada_fecha_o_backend(tmp_path: Path) -> None:
    app = _app(tmp_path, entrada_virtual=True)
    ferramentas = app._montar_ferramentas()
    assert ferramentas.entrada is not None
    app.interruptor_de_entrada.parar("botão da janela")
    resultado = ferramentas.executar("input.mouse.click", {}, cancelado=lambda: False)
    assert resultado.status == "erro" and "só o dono a libera" in resultado.motivo
    app.interruptor_de_entrada.liberar()
    assert not app.interruptor_de_entrada.parado


def test_configuracao_volta_igual(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    escrever(BASE.com(entrada_virtual=True, entrada_uinput=True), arquivo)
    lido = ler(arquivo)
    assert lido.entrada_virtual is True and lido.entrada_uinput is True


class _Falso:
    def __init__(self, nome: str, indisponivel: bool = False) -> None:
        self.nome = nome
        self.indisponivel = indisponivel
        self.cliques = 0

    def mover(self, dx: int, dy: int) -> None: ...

    def clicar(self, botao: str, vezes: int) -> None:
        if self.indisponivel:
            raise EntradaIndisponivel(f"{self.nome} fora")
        self.cliques += 1

    def digitar(self, texto: str) -> None: ...

    def pressionar(self, modificadores: tuple[str, ...], tecla: str) -> None: ...

    def fechar(self) -> None: ...


def test_wayland_tenta_o_portal_e_cai_para_o_uinput_so_se_o_dono_ligou() -> None:
    portal, reserva = _Falso("portal", indisponivel=True), _Falso("uinput")
    wayland = {"WAYLAND_DISPLAY": "w0"}
    ligado = backend_do_ambiente(
        wayland, uinput_liberado=True, portal=lambda: portal, uinput=lambda: reserva
    )
    ligado.clicar("esquerdo", 1)
    assert (portal.cliques, reserva.cliques, ligado.nome) == (0, 1, "uinput")

    sem_reserva = backend_do_ambiente(
        wayland, uinput_liberado=False, portal=lambda: portal, uinput=lambda: reserva
    )
    assert isinstance(sem_reserva, EntradaComReserva)
    try:
        sem_reserva.clicar("esquerdo", 1)
    except EntradaIndisponivel as erro:
        assert "portal fora" in str(erro)
    else:  # pragma: no cover
        raise AssertionError("deveria ter recusado")
    assert reserva.cliques == 1  # a reserva desligada não foi usada de novo


def test_x11_prefere_o_uinput_porque_o_portal_do_plasma_so_existe_no_wayland() -> None:
    portal, reserva = _Falso("portal"), _Falso("uinput")
    backend = backend_do_ambiente(
        {"DISPLAY": ":0"}, uinput_liberado=True, portal=lambda: portal, uinput=lambda: reserva
    )
    backend.clicar("esquerdo", 1)
    assert (portal.cliques, reserva.cliques) == (0, 1)
