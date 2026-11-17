"""ADR-0074, fatia 1: a fonte virtual que assume o lugar do microfone — só com executor FALSO.

Nenhum `pactl`, `pw-cli` ou `systemctl` de verdade roda: o executor falso responde de um grafo
em memória e anota os comandos. O executor do sistema recusa rodar sob CI (a suíte força
`CI=1`). As pastas de configuração são temporárias: nada toca o `~/.config` do dono."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jarvis.audio_io.erros import DispositivoProibidoEmCI
from jarvis.audio_io.misturador import (
    NOME_DA_FONTE,
    ErroDoMisturador,
    ExecutorDoSistema,
    Instalacao,
    Misturador,
    Saida,
    config_pipewire,
    config_wireplumber,
)

FISICO = "alsa_input.usb-Microfone_do_Dono-00.mono-fallback"
PID_DO_JARVIS = 4242


@dataclass
class GrafoFalso:
    """Um pipewire-pulse de mentira: fontes, fluxos de captura e módulos."""

    padrao: str = FISICO
    fontes: dict[str, int] = field(default_factory=lambda: {FISICO: 50})
    fluxos: dict[int, dict[str, Any]] = field(default_factory=dict)
    modulos: dict[str, str] = field(default_factory=dict)
    comandos: list[tuple[str, ...]] = field(default_factory=list)
    falhar_em: str = ""
    aceita_padrao: bool = True
    reverte: set[int] = field(default_factory=set)
    """Fluxos de app que voltam sozinhos ao físico depois de movidos."""

    def rodar(self, argv: Sequence[str]) -> Saida:
        comando = tuple(argv)
        self.comandos.append(comando)
        if self.falhar_em and self.falhar_em in " ".join(comando):
            return Saida(1, "Falha: módulo não carregou")
        if comando[0] != "pactl":
            return Saida(0)
        args = comando[1:]
        if args == ("get-default-source",):
            return Saida(0, self.padrao + "\n")
        if args[0] == "set-default-source":
            if args[1] in self.fontes and (self.aceita_padrao or args[1] == FISICO):
                self.padrao = args[1]
            return Saida(0)
        if args[0] == "load-module":
            indice = str(500 + len(self.modulos))
            self.modulos[indice] = args[1]
            if args[1] == "module-remap-source":
                self.fontes[NOME_DA_FONTE] = 90
            if args[1] == "module-loopback":
                self.fluxos[8] = {"index": 8, "source": 50, "owner_module": int(indice)}
            return Saida(0, indice + "\n")
        if args[0] == "unload-module":
            self.modulos.pop(args[1], None)
            if not any(m == "module-remap-source" for m in self.modulos.values()):
                self.fontes.pop(NOME_DA_FONTE, None)
            return Saida(0)
        if args[:3] == ("-f", "json", "list"):
            if args[3] == "sources":
                return Saida(
                    0, json.dumps([{"index": i, "name": n} for n, i in self.fontes.items()])
                )
            return Saida(
                0,
                json.dumps(
                    [
                        {
                            "index": f["index"],
                            "source": f["source"],
                            "owner_module": f.get("owner_module"),
                            "properties": f.get("props", {}),
                        }
                        for f in self.fluxos.values()
                    ]
                ),
            )
        if args[0] == "move-source-output":
            fluxo, destino = int(args[1]), args[2]
            if fluxo in self.fluxos:
                self.fluxos[fluxo]["source"] = self.fontes[destino]
            return Saida(0)
        return Saida(0)

    def app(self, indice: int, nome: str, pid: int) -> None:
        self.fluxos[indice] = {
            "index": indice,
            "source": self.fontes[FISICO],
            "props": {"application.name": nome, "application.process.id": str(pid)},
        }

    def onde(self, indice: int) -> int:
        return int(self.fluxos[indice]["source"])


def _ligado() -> tuple[GrafoFalso, Misturador]:
    grafo = GrafoFalso()
    grafo.app(11, "Discord", 100)
    grafo.app(12, "Chromium (WhatsApp Web)", 200)
    grafo.app(13, "Jarvis (ouve o microfone real)", PID_DO_JARVIS)
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    misturador.ligar()
    return grafo, misturador


def test_ligar_cria_a_fonte_vira_padrao_e_move_so_os_apps(tmp_path: Path) -> None:
    grafo, misturador = _ligado()
    carregados = [c[2] for c in grafo.comandos if c[1:2] == ("load-module",)]
    assert carregados == ["module-null-sink", "module-loopback", "module-remap-source"]
    assert grafo.padrao == NOME_DA_FONTE
    fonte = grafo.fontes[NOME_DA_FONTE]
    assert grafo.onde(11) == fonte and grafo.onde(12) == fonte, "Discord e navegador movidos"
    assert grafo.onde(13) == grafo.fontes[FISICO], "o Jarvis continua ouvindo o microfone REAL"
    assert grafo.onde(8) == grafo.fontes[FISICO], "o loopback continua no físico"
    assert misturador.ligado and misturador.avisos == []


def test_app_que_reverte_e_movido_de_novo_ate_o_teto_e_avisa() -> None:
    grafo, misturador = _ligado()
    for _ in range(5):
        grafo.fluxos[11]["source"] = grafo.fontes[FISICO]  # o Discord volta ao físico
        misturador.mover()
    movimentos = [c for c in grafo.comandos if c[1:3] == ("move-source-output", "11")]
    assert len(movimentos) == 3
    assert any("volta sozinho" in a for a in misturador.avisos)


def test_desligar_devolve_fluxos_padrao_e_descarrega_na_ordem_inversa() -> None:
    grafo, misturador = _ligado()
    del grafo.fluxos[12]  # o navegador fechou no meio
    misturador.desligar()
    assert grafo.onde(11) == grafo.fontes[FISICO]
    assert grafo.padrao == FISICO
    descarregados = [c[2] for c in grafo.comandos if c[1:2] == ("unload-module",)]
    assert descarregados == ["502", "501", "500"]
    assert grafo.modulos == {} and not misturador.ligado
    assert not any(
        c[1:3] == ("move-source-output", "12") and c[3] == FISICO for c in grafo.comandos
    )


def test_falha_no_meio_desfaz_o_que_criou() -> None:
    grafo = GrafoFalso(falhar_em="module-remap-source")
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    with pytest.raises(ErroDoMisturador, match="load-module"):
        misturador.ligar()
    assert grafo.modulos == {}, "o sink e o loopback criados foram descarregados"
    assert grafo.padrao == FISICO and not misturador.ligado


def test_servidor_que_nao_aceita_o_padrao_vira_aviso_e_o_move_continua() -> None:
    grafo = GrafoFalso(aceita_padrao=False)
    grafo.app(11, "Discord", 100)
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    misturador.ligar()
    assert any("padrão" in a for a in misturador.avisos)
    assert grafo.onde(11) == grafo.fontes[NOME_DA_FONTE]


def test_executor_do_sistema_recusa_sob_ci() -> None:
    with pytest.raises(DispositivoProibidoEmCI):
        ExecutorDoSistema().rodar(("pactl", "info"))


# --- modo instalado ---------------------------------------------------------------------------
def test_configs_geradas_trocam_a_identidade_sem_tocar_etc() -> None:
    pipewire = config_pipewire(FISICO, "Microfone do Dono")
    wireplumber = config_wireplumber(FISICO, "Microfone do Dono")
    assert f'node.name = "{FISICO}"' in pipewire and "media.class = Audio/Source" in pipewire
    assert f'target.object = "{FISICO}.jarvis-direto"' in pipewire
    assert f'node.name = "{FISICO}.jarvis-direto"' in wireplumber
    assert "(direto, só o Jarvis)" in wireplumber
    assert "/etc" not in pipewire + wireplumber and "node.disabled" not in wireplumber


def test_instalar_so_com_sim_guarda_copia_e_desfaz(tmp_path: Path) -> None:
    grafo = GrafoFalso()
    pw, wp = tmp_path / "pipewire.conf.d", tmp_path / "wireplumber.conf.d"
    wp.mkdir()
    (wp / "50-jarvis-microfone.conf").write_text("o que o dono tinha antes\n")
    instalacao = Instalacao(executor=grafo, pasta_pipewire=pw, pasta_wireplumber=wp)
    with pytest.raises(ErroDoMisturador, match="sim do dono"):
        instalacao.instalar(FISICO, "Microfone do Dono", confirmado=False)
    assert not (pw / "50-jarvis-microfone.conf").exists() and grafo.comandos == []
    assert len(instalacao.previa(FISICO, "Microfone do Dono")) == 2

    instalacao.instalar(FISICO, "Microfone do Dono", confirmado=True)
    assert "Gerado pelo Jarvis" in (pw / "50-jarvis-microfone.conf").read_text()
    assert grafo.comandos[-1] == (
        "systemctl",
        "--user",
        "restart",
        "wireplumber",
        "pipewire",
        "pipewire-pulse",
    )
    instalacao.desinstalar()
    assert not (pw / "50-jarvis-microfone.conf").exists()
    assert (wp / "50-jarvis-microfone.conf").read_text() == "o que o dono tinha antes\n"
