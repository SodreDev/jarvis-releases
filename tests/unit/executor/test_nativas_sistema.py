"""Sistema, volume, brilho, mídia, janelas, área de transferência e notificação (item 4, grupo 1).

Nenhum teste toca o desktop do dono: o lançador é o falso (`LancadorFalso`), que grava cada `argv`
— e é isso que se confere: o programa é da lista, o argumento é tipado, nada de shell.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor import desktop, sistema
from jarvis.executor.comandos import (
    PROGRAMAS,
    ComandoRecusado,
    LancadorFalso,
    Saida,
    executar,
)
from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.executor.janelas import JanelasPorWmctrl
from jarvis.executor.nativas import Nativas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731
SEGUNDA = datetime(2026, 10, 19, 14, 35, 10).astimezone()


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
        executor = ExecutorDeFerramentas(pdp=pdp, lar=lar)
        executor.preparar()
        yield executor


def _com(executor: ExecutorDeFerramentas, falso: LancadorFalso, **extra: Any) -> LancadorFalso:
    executor.nativas = Nativas(lar=executor.lar, lancar=falso, agora=lambda: SEGUNDA, **extra)
    return falso


def _rodar(executor: ExecutorDeFerramentas, tool: str, args: dict[str, Any], **kw: Any) -> Any:
    return executor.executar(tool, args, cancelado=NUNCA, **kw)


# --- a porta de comandos ------------------------------------------------------------
def test_so_programa_da_lista_roda_e_sem_shell() -> None:
    with pytest.raises(ComandoRecusado):
        executar(["rm", "-rf", "/"])
    with pytest.raises(ComandoRecusado):
        executar(["bash", "-c", "echo oi"])
    with pytest.raises(ComandoRecusado):
        executar([])
    assert {"bash", "sh", "rm", "python", "ssh", "sudo", "curl"}.isdisjoint(PROGRAMAS)


def test_argumento_com_byte_nulo_e_recusado() -> None:
    with pytest.raises(ComandoRecusado):
        executar(["notify-send", "oi\x00"])


def test_programa_ausente_vira_frase_e_nao_traceback(executor: ExecutorDeFerramentas) -> None:
    _com(executor, LancadorFalso(ausentes=frozenset({"wpctl", "pactl"})))

    resultado = _rodar(executor, "system.volume.get", {})

    assert resultado.status == "erro" and "não está instalado" in resultado.motivo


# --- hora ------------------------------------------------------------
def test_hora_e_data_saem_escritas_para_falar(executor: ExecutorDeFerramentas) -> None:
    _com(executor, LancadorFalso())

    r = _rodar(executor, "system.clock.now", {})

    assert r.status == "ok" and r.aviso == ""
    assert r.dados["hora"] == "14:35"
    assert r.dados["data_por_extenso"] == "segunda-feira, 19 de outubro de 2026"


# --- estado da máquina ------------------------------------------------------------
def _arvore(raiz: Path, *, bateria: bool = True) -> None:
    (raiz / "proc").mkdir(parents=True)
    (raiz / "proc/meminfo").write_text("MemTotal: 16000000 kB\nMemAvailable: 4000000 kB\n")
    (raiz / "proc/stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    (raiz / "sys/class/net/lo").mkdir(parents=True)
    (raiz / "sys/class/net/lo/operstate").write_text("unknown")
    (raiz / "sys/class/net/wlan0/wireless").mkdir(parents=True)
    (raiz / "sys/class/net/wlan0/operstate").write_text("up\n")
    (raiz / "sys/class/net/eth0").mkdir(parents=True)
    (raiz / "sys/class/net/eth0/operstate").write_text("down\n")
    if bateria:
        bat = raiz / "sys/class/power_supply/BAT0"
        bat.mkdir(parents=True)
        (bat / "type").write_text("Battery\n")
        (bat / "capacity").write_text("63\n")
        (bat / "status").write_text("Discharging\n")
        ac = raiz / "sys/class/power_supply/AC"
        ac.mkdir()
        (ac / "type").write_text("Mains\n")
        (ac / "online").write_text("0\n")


def test_estado_da_maquina_le_bateria_rede_memoria_cpu_e_disco(
    executor: ExecutorDeFerramentas, tmp_path: Path
) -> None:
    falsa = tmp_path / "raiz-falsa"
    _arvore(falsa)
    amostras = iter(["cpu  100 0 100 800 0 0 0 0 0 0\n", "cpu  150 0 150 900 0 0 0 0 0 0\n"])

    def dormir(_s: float) -> None:  # entre as duas amostras o "tempo" da CPU anda
        (falsa / "proc/stat").write_text(next(amostras))

    (falsa / "proc/stat").write_text(next(amostras))
    _com(executor, LancadorFalso(), raiz_do_sistema=falsa, dormir=dormir)

    d = _rodar(executor, "system.machine.status", {}).dados

    assert d["bateria"] == {"porcentagem": 63, "estado": "Discharging", "na_tomada": False}
    assert d["rede"] == {"conectada": True, "interfaces": [{"interface": "wlan0", "tipo": "wifi"}]}
    assert d["memoria"] == {"total_gb": 15.3, "usada_gb": 11.4, "usada_pct": 75}
    assert d["cpu"]["uso_pct"] == 50
    assert d["disco"]["total_gb"] > 0


def test_sem_bateria_ele_diz_que_nao_tem_em_vez_de_inventar(
    executor: ExecutorDeFerramentas, tmp_path: Path
) -> None:
    falsa = tmp_path / "raiz-falsa"
    _arvore(falsa, bateria=False)
    _com(executor, LancadorFalso(), raiz_do_sistema=falsa, dormir=lambda _s: None)

    d = _rodar(executor, "system.machine.status", {}).dados

    assert "bateria" not in d and "não tem bateria" in d["observacao"]


# --- volume ------------------------------------------------------------
def _wpctl(volume: float, mudo: bool = False) -> Saida:
    return Saida(0, f"Volume: {volume:.2f}{' [MUTED]' if mudo else ''}\n")


def test_volume_atual_e_definir_nivel_com_argv_fixo(executor: ExecutorDeFerramentas) -> None:
    falso = _com(executor, LancadorFalso({"wpctl": _wpctl(0.45)}))

    lido = _rodar(executor, "system.volume.get", {})
    assert lido.dados == {"volume_pct": 45, "mudo": False}

    feito = _rodar(executor, "system.volume.set", {"nivel": 60})
    assert feito.status == "ok" and feito.aviso == "", "volume é livre: sem aviso"
    assert [
        "wpctl",
        "set-volume",
        "-l",
        "1.0",
        "@DEFAULT_AUDIO_SINK@",
        "0.60",
    ] in falso.chamadas


def test_volume_delta_soma_e_nunca_passa_de_cem_nem_abaixo_de_zero(
    executor: ExecutorDeFerramentas,
) -> None:
    falso = _com(executor, LancadorFalso({"wpctl": _wpctl(0.95)}))

    _rodar(executor, "system.volume.set", {"delta": 30})

    sets = [c for c in falso.chamadas if c[1] == "set-volume"]
    assert sets[-1][-1] == "1.00"


def test_volume_exige_um_pedido_e_nao_aceita_dois_nem_fora_da_faixa(
    executor: ExecutorDeFerramentas,
) -> None:
    _com(executor, LancadorFalso({"wpctl": _wpctl(0.3)}))

    assert _rodar(executor, "system.volume.set", {}).status == "erro"
    assert _rodar(executor, "system.volume.set", {"nivel": 10, "delta": 5}).status == "erro"
    fora = _rodar(executor, "system.volume.set", {"nivel": 150})
    assert fora.status == "erro" and "fora do contrato" in fora.motivo


def test_volume_mudo_e_pactl_de_reserva(executor: ExecutorDeFerramentas) -> None:
    falso = _com(
        executor,
        LancadorFalso(
            {"pactl": lambda argv: Saida(0, "Volume: front-left: 32768 /  50% / -18.06 dB\n")},
            ausentes=frozenset({"wpctl"}),
        ),
    )

    r = _rodar(executor, "system.volume.set", {"nivel": 40, "mudo": True})

    assert r.status == "ok"
    assert ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "40%"] in falso.chamadas
    assert ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"] in falso.chamadas


# --- brilho ------------------------------------------------------------
def _powerdevil(argv: Sequence[str]) -> Saida:
    return Saida(0, "(int32 1000,)\n" if argv[-1].endswith("brightnessMax") else "(int32 500,)\n")


def test_brilho_pelo_powerdevil_do_kde(executor: ExecutorDeFerramentas) -> None:
    falso = _com(executor, LancadorFalso({"gdbus": _powerdevil}))

    r = _rodar(executor, "system.brightness.set", {"nivel": 80})

    assert r.dados == {"brilho_pct": 80}
    ultimo = falso.chamadas[-1]
    assert ultimo[-2].endswith("setBrightness") and ultimo[-1] == "800"


def test_brilho_nunca_apaga_a_tela_e_cai_no_brightnessctl(
    executor: ExecutorDeFerramentas,
) -> None:
    falso = _com(
        executor,
        LancadorFalso(
            {"brightnessctl": Saida(0, "Current brightness: 12 (1%)\n")},
            ausentes=frozenset({"gdbus"}),
        ),
    )

    r = _rodar(executor, "system.brightness.set", {"nivel": 0})

    assert r.status == "ok"
    assert ["brightnessctl", "set", "1%"] in falso.chamadas, "o mínimo é 1%"


# --- mídia ------------------------------------------------------------
def test_midia_pelo_playerctl(executor: ExecutorDeFerramentas) -> None:
    falso = _com(executor, LancadorFalso({"playerctl": Saida(0)}))

    r = _rodar(executor, "media.player.control", {"acao": "alternar"})

    assert r.status == "ok" and falso.chamadas == [["playerctl", "play-pause"]]


def test_midia_cai_no_mpris_e_escolhe_o_que_esta_tocando(executor: ExecutorDeFerramentas) -> None:
    nomes = (
        "(['org.freedesktop.DBus', 'org.mpris.MediaPlayer2.firefox.instance1', "
        "'org.mpris.MediaPlayer2.spotify'],)\n"
    )

    def gdbus(argv: Sequence[str]) -> Saida:
        if "ListNames" in argv[-1]:
            return Saida(0, nomes)
        if argv[-1] == "PlaybackStatus":
            tocando = "spotify" in argv[argv.index("--dest") + 1]
            return Saida(0, f"(<'{'Playing' if tocando else 'Paused'}'>,)\n")
        return Saida(0, "()\n")

    falso = _com(executor, LancadorFalso({"gdbus": gdbus}, ausentes=frozenset({"playerctl"})))

    r = _rodar(executor, "media.player.control", {"acao": "proxima"})

    assert r.dados["player"] == "spotify" and r.dados["via"] == "mpris"
    assert falso.chamadas[-1][-1] == "org.mpris.MediaPlayer2.Player.Next"


def test_midia_sem_player_diz_que_nao_ha_e_acao_fora_do_enum_e_recusada(
    executor: ExecutorDeFerramentas,
) -> None:
    _com(
        executor,
        LancadorFalso(
            {"gdbus": Saida(0, "(['org.freedesktop.DBus'],)\n")}, ausentes=frozenset({"playerctl"})
        ),
    )

    assert "nenhum player" in _rodar(executor, "media.player.control", {"acao": "tocar"}).motivo
    assert _rodar(executor, "media.player.control", {"acao": "formatar"}).status == "erro"
    assert (
        _rodar(executor, "media.player.control", {"acao": "tocar", "player": "x; rm"}).status
        == "erro"
    )


def test_estado_da_midia_le_titulo_e_artista(executor: ExecutorDeFerramentas) -> None:
    def gdbus(argv: Sequence[str]) -> Saida:
        if "ListNames" in argv[-1]:
            return Saida(0, "(['org.mpris.MediaPlayer2.spotify'],)\n")
        if argv[-1] == "PlaybackStatus":
            return Saida(0, "(<'Playing'>,)\n")
        return Saida(
            0, "(<{'xesam:title': <'Águas de Março'>, 'xesam:artist': <['Elis Regina']>}>,)\n"
        )

    _com(executor, LancadorFalso({"gdbus": gdbus}))

    d = _rodar(executor, "media.player.status", {}).dados

    assert d["players"] == [
        {
            "player": "spotify",
            "estado": "Playing",
            "titulo": "Águas de Março",
            "artista": "Elis Regina",
        }
    ]


# --- janelas ------------------------------------------------------------
WMCTRL = (
    "0x03a00003 -1 desktop.plasmashell host Área de trabalho\n"
    "0x04200004  0 navigator.firefox host Wikipédia — Mozilla Firefox\n"
    "0x05600001  0 kate.Kate host notas.md — Kate\n"
    "0x05600009  0 kate.Kate host outro.md — Kate\n"
)


def test_listar_focar_e_escolher_a_janela_pela_lista_real(executor: ExecutorDeFerramentas) -> None:
    falso = _com(executor, LancadorFalso({"wmctrl": Saida(0, WMCTRL)}))

    listadas = _rodar(executor, "window.list", {}).dados["janelas"]
    assert [j["app"] for j in listadas] == ["firefox", "Kate", "Kate"], "o painel não é janela"

    r = _rodar(executor, "window.focus_app", {"app": "firefox"})

    assert r.dados["app"] == "firefox"
    assert ["wmctrl", "-i", "-a", "0x04200004"] in falso.chamadas, (
        "o id veio da lista, não do modelo"
    )
    assert r.aviso == "", "focar é livre"


def test_app_inexistente_ou_ambiguo_volta_com_a_frase(executor: ExecutorDeFerramentas) -> None:
    _com(
        executor,
        LancadorFalso(
            {"wmctrl": Saida(0, WMCTRL + "0x07 0 nautilus.Nautilus h notas — Arquivos\n")}
        ),
    )

    assert "nenhuma janela" in _rodar(executor, "window.focus_app", {"app": "gimp"}).motivo
    ambiguo = _rodar(executor, "window.focus_app", {"app": "notas"})
    assert ambiguo.status == "erro" and "Diga qual" in ambiguo.motivo


def test_fechar_a_janela_e_como_o_x_e_nao_pergunta(executor: ExecutorDeFerramentas) -> None:
    """ADR-0042: fechar a janela é livre — quem pergunta se salva é o próprio app, como no X. Era a
    `window.close_app`, perigosa, que perguntava sempre."""
    lxp = (
        "0x03a00003 -1 1001 desktop.plasmashell host Área de trabalho\n"
        "0x05600001  0 2002 kate.Kate host notas.md — Kate\n"
    )
    falso = LancadorFalso(
        {
            "wmctrl": Saida(0, lxp),
            "xprop": Saida(0, "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x5600001"),
        }
    )
    instantes = iter(range(100))
    _com(
        executor,
        falso,
        janelas=JanelasPorWmctrl(falso),
        processos=SemProcessos(),
        dormir=lambda _s: None,
        relogio=lambda: float(next(instantes)),
    )
    perguntas: list[Confirmacao] = []

    def nao(p: Confirmacao) -> bool:
        perguntas.append(p)
        return False

    fechou = _rodar(executor, "window.close", {"app": "kate"}, confirmar=nao)

    assert fechou.status == "ok" and not perguntas, "fechar a janela não pede o sim"
    assert ["wmctrl", "-i", "-c", "0x05600001"] in falso.chamadas
    # A lista falsa não muda: a janela "continua aberta", e a resposta diz o que pode ser.
    assert fechou.dados["fechada"] is False and "perguntando se salva" in fechou.dados["nota"]


class SemProcessos:
    """A tabela de processos vazia: o teste não lê o /proc da máquina."""

    def listar(self) -> list[Any]:
        return []

    def ler(self, _pid: int) -> None:
        return None

    def argumentos(self, _pid: int) -> tuple[str, ...]:
        return ()


# --- área de transferência ------------------------------------------------------------
def test_area_de_transferencia_le_sem_segredo_e_marca_o_turno_como_de_terceiros(
    executor: ExecutorDeFerramentas,
) -> None:
    _com(
        executor,
        LancadorFalso({"xclip": Saida(0, "meu token: abc123def456ghi e o resto do texto")}),
        ambiente={},
    )

    r = _rodar(executor, "clipboard.text.read", {})

    assert "abc123def456ghi" not in r.dados["texto"] and r.dados["segredos_ocultados"] >= 1
    assert executor.contaminado is True, "o que se copiou pode ter vindo de uma página"


def test_escrever_na_area_avisa_e_desfazer_devolve_o_texto_anterior(
    executor: ExecutorDeFerramentas,
) -> None:
    atual = {"texto": "texto antigo"}

    def xclip(argv: Sequence[str]) -> Saida:
        return Saida(0, atual["texto"]) if "-o" in argv else Saida(0)

    falso = _com(executor, LancadorFalso({"xclip": xclip}), ambiente={})

    r = _rodar(executor, "clipboard.text.write", {"texto": "novo texto"})

    assert r.status == "ok" and r.aviso == "Copiei o texto para a área de transferência."
    assert ["xclip", "-selection", "clipboard", "<<novo texto"] in falso.chamadas
    desfeita = _rodar(executor, "acao.desfazer", {})
    assert desfeita.status == "ok"
    assert falso.chamadas[-1] == ["xclip", "-selection", "clipboard", "<<texto antigo"]


def test_no_wayland_usa_wl_copy_e_wl_paste(executor: ExecutorDeFerramentas) -> None:
    falso = _com(
        executor,
        LancadorFalso({"wl-paste": Saida(0, "oi")}),
        ambiente={"WAYLAND_DISPLAY": "wayland-0"},
    )

    _rodar(executor, "clipboard.text.read", {})
    _rodar(executor, "clipboard.text.write", {"texto": "x"})

    programas = {c[0] for c in falso.chamadas}
    assert programas == {"wl-paste", "wl-copy"}


# --- notificação ------------------------------------------------------------
def test_notificacao_usa_dois_tracos_e_titulo_nao_vira_opcao(
    executor: ExecutorDeFerramentas,
) -> None:
    falso = _com(executor, LancadorFalso())

    r = _rodar(
        executor, "notify.desktop.send", {"titulo": "--urgency=critical", "texto": "chá pronto"}
    )

    assert r.status == "ok"
    argv = falso.chamadas[-1]
    assert argv[:3] == ["notify-send", "--app-name=Jarvis", "--expire-time=8000"]
    assert argv[3] == "--" and argv[4] == "--urgency=critical", "depois do `--` é só texto"


def test_o_modelo_so_ve_estas_tools_nativas_no_catalogo(executor: ExecutorDeFerramentas) -> None:
    ids = {t["id"] for t in executor.catalogo_para_o_modelo()}

    assert {
        "system.clock.now", "system.machine.status", "system.volume.get", "system.volume.set",
        "system.brightness.set", "media.player.control", "media.player.status", "window.list",
        "window.focus_app", "window.close", "apps.quit", "clipboard.text.read",
        "clipboard.text.write",
        "notify.desktop.send", "web.buscar", "web.ler", "files.create_dir", "files.copy",
        "files.move",
    } <= ids  # fmt: skip
    assert not [i for i in ids if i.startswith("timer.")], "sem agenda ligada, sem alarme"
    assert desktop.PREFIXO_MPRIS and sistema.SINK
