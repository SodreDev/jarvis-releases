"""`jarvis --testar-chamada` (ADR-0074, fatia B) contra um servidor de som FALSO: os seis passos,
o que sai na tela (sem áudio, sem segredo) e que tudo é desfeito, mesmo quando um passo falha."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from jarvis.audio_io.misturador import NOME_DA_FONTE, Saida
from jarvis.chamada import diagnostico
from tests.unit.audio_io.test_eco_da_chamada import GrafoComSaida
from tests.unit.audio_io.test_misturador import FISICO


class Servidor(GrafoComSaida):
    """O grafo falso com `pactl info` e o estado do mudo na lista de sink-inputs."""

    def __init__(self, *, aceita_padrao: bool = True) -> None:
        super().__init__(
            [{"name": "alsa_output.pci", "properties": {"device.form_factor": "headset"}}]
        )
        self.padrao_de_saida = "alsa_output.pci"
        self.aceita_padrao = aceita_padrao

    def rodar(self, argv: Sequence[str]) -> Saida:
        args = tuple(argv)[1:]
        if args == ("info",):
            return Saida(
                0,
                "Server String: /run/user/1000/pulse/native\n"
                "Server Name: PulseAudio (on PipeWire 1.2.7)\n",
            )
        if args == ("-f", "json", "list", "sink-inputs"):
            loopback = next(
                (int(i) for i, m in self.modulos.items() if m == "module-loopback"), None
            )
            fluxos = (
                []
                if loopback is None
                else [{"index": 77, "owner_module": loopback, "mute": self.mudos.get(77, False)}]
            )
            return Saida(0, json.dumps(fluxos))
        return super().rodar(argv)


@dataclass
class Captura:
    servidor: Servidor
    parou: int = 0
    falhar: bool = False

    def iniciar(self, dispositivo: str) -> int:
        assert dispositivo == FISICO
        if self.falhar:
            raise FileNotFoundError("parec não está instalado")
        self.servidor.fluxos[61] = {
            "index": 61,
            "source": self.servidor.fontes[FISICO],
            "props": {"application.process.id": "4321"},
        }
        return 4321

    def parar(self) -> None:
        self.parou += 1
        self.servidor.fluxos.pop(61, None)


def _rodar(servidor: Servidor, captura: Captura) -> tuple[int, list[str]]:
    linhas: list[str] = []
    codigo = diagnostico.testar_chamada(servidor, linhas.append, captura, esperar=lambda _s: None)
    return codigo, linhas


def test_tudo_certo_seis_passos_e_tudo_desfeito() -> None:
    servidor = Servidor()
    captura = Captura(servidor)
    codigo, linhas = _rodar(servidor, captura)
    texto = "\n".join(linhas)
    assert codigo == 0, texto
    for trecho in (
        "PulseAudio (on PipeWire 1.2.7)",
        f"entrada padrão: {FISICO}",
        "fone na saída: sim",
        "nenhuma sobra",
        "a fonte virtual virou a entrada padrão",
        "a captura foi movida para a fonte virtual",
        "abafou e devolveu",
        f"a entrada padrão voltou: {FISICO}",
        "nada ficou carregado",
        "resultado: ",
    ):
        assert trecho in texto
    assert "FALHOU" not in texto
    assert servidor.padrao == FISICO and servidor.modulos == {} and captura.parou >= 1


def test_padrao_nao_aceito_e_captura_que_falha_aparecem_e_ainda_desfaz() -> None:
    servidor = Servidor(aceita_padrao=False)
    captura = Captura(servidor, falhar=True)
    codigo, linhas = _rodar(servidor, captura)
    texto = "\n".join(linhas)
    assert codigo == 1
    assert "FALHOU  a entrada padrão continua" in texto
    assert "FALHOU  não abri a captura de teste" in texto
    assert texto.rstrip().splitlines()[-1].startswith("resultado:")
    assert servidor.modulos == {} and servidor.padrao == FISICO


def test_sobra_de_antes_para_antes_de_mexer() -> None:
    servidor = Servidor()
    servidor.fontes[NOME_DA_FONTE] = 90
    codigo, linhas = _rodar(servidor, Captura(servidor))
    assert codigo == 1 and any("sobra de uma execução" in linha for linha in linhas)
    assert not any(c[1:2] == ("load-module",) for c in servidor.comandos)


def test_sem_pactl_diz_o_que_instalar() -> None:
    class SemPactl(Servidor):
        def rodar(self, argv: Sequence[str]) -> Saida:
            return Saida(127, "pactl não está instalado")

    codigo, linhas = _rodar(SemPactl(), Captura(Servidor()))
    assert codigo == 1 and "pulseaudio-utils" in "\n".join(linhas)


def test_no_sistema_recusa_sob_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis.audio_io.erros import DispositivoProibidoEmCI

    monkeypatch.setenv("CI", "1")
    with pytest.raises(DispositivoProibidoEmCI):
        diagnostico.testar_chamada_no_sistema(lambda _t: None)


def test_a_flag_existe_no_jarvis() -> None:
    from jarvis.gui.principal import _analisador

    assert _analisador().parse_args(["--testar-chamada"]).testar_chamada is True
