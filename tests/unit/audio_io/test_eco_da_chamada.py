"""ADR-0074, decisão do dono de 2026-11-17: «uso fone às vezes» — `fone` sim/não/auto. Sem fone, o
microfone real fica mudo na mistura enquanto o Jarvis fala; com fone, a voz também toca nele e nada
é abafado. Só executor FALSO: nenhum `pactl` de verdade."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest

from jarvis.audio_io.misturador import (
    Misturador,
    PoliticaDeEco,
    Saida,
    fone_na_saida,
    politica_de_eco,
)
from tests.unit.audio_io.test_misturador import PID_DO_JARVIS, GrafoFalso


class GrafoComSaida(GrafoFalso):
    """O grafo falso com a saída padrão e o fluxo do loopback na mistura."""

    sinks: list[dict[str, Any]]
    padrao_de_saida: str = "alsa_output.pci.analog-stereo"
    mudos: dict[int, bool]

    def __init__(self, sinks: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.sinks = sinks or []
        self.mudos = {}

    def rodar(self, argv: Sequence[str]) -> Saida:
        args = tuple(argv)[1:]
        if args == ("get-default-sink",):
            self.comandos.append(tuple(argv))
            return Saida(0, self.padrao_de_saida + "\n")
        if args == ("-f", "json", "list", "sinks"):
            self.comandos.append(tuple(argv))
            return Saida(0, json.dumps(self.sinks))
        if args == ("-f", "json", "list", "sink-inputs"):
            self.comandos.append(tuple(argv))
            loopback = next(
                (int(i) for i, m in self.modulos.items() if m == "module-loopback"), None
            )
            fluxos = [] if loopback is None else [{"index": 77, "owner_module": loopback}]
            return Saida(0, json.dumps(fluxos))
        if args[:1] == ("set-sink-input-mute",):
            self.comandos.append(tuple(argv))
            self.mudos[int(args[1])] = args[2] == "1"
            return Saida(0)
        return super().rodar(argv)


def _sink(nome: str, *, forma: str = "", porta: str = "", tipo: str = "") -> dict[str, Any]:
    props = {"device.form_factor": forma} if forma else {}
    sink: dict[str, Any] = {"name": nome, "properties": props}
    if porta:
        sink["active_port"] = porta
        sink["ports"] = [{"name": porta, "type": tipo}, {"name": "outra", "type": "Speaker"}]
    return sink


SAIDA = "alsa_output.pci.analog-stereo"


@pytest.mark.parametrize(
    ("sink", "esperado"),
    [
        (_sink(SAIDA, forma="headset"), True),
        (_sink(SAIDA, forma="headphone"), True),
        (_sink(SAIDA, forma="speaker"), False),
        (_sink(SAIDA, porta="analog-output-headphones", tipo="Headphones"), True),
        (_sink(SAIDA, porta="analog-output-speaker", tipo="Speaker"), False),
        (_sink(SAIDA, porta="x", tipo="Unknown"), None),
        (_sink(SAIDA), None),
        (_sink("outro-sink", forma="headset"), None),
    ],
)
def test_fone_na_saida_pelo_que_o_sistema_diz(sink: dict[str, Any], esperado: bool | None) -> None:
    assert fone_na_saida(GrafoComSaida([sink])) is esperado


def test_fone_na_saida_sem_resposta_e_none() -> None:
    class Quebrado(GrafoComSaida):
        def rodar(self, argv: Sequence[str]) -> Saida:
            return Saida(1, "sem servidor")

    assert fone_na_saida(Quebrado()) is None


@pytest.mark.parametrize(
    ("fone", "detectado", "politica"),
    [
        ("sim", None, PoliticaDeEco(True, False, True)),
        ("sim", False, PoliticaDeEco(True, False, True)),
        ("nao", True, PoliticaDeEco(False, True, False)),
        ("auto", True, PoliticaDeEco(True, False, True)),
        ("auto", False, PoliticaDeEco(False, True, False)),
        ("auto", None, PoliticaDeEco(False, True, None)),  # na dúvida, sem fone (sem eco)
    ],
)
def test_politica_de_eco(fone: str, detectado: bool | None, politica: PoliticaDeEco) -> None:
    assert politica_de_eco(fone, detectado) == politica


def _ligado(grafo: GrafoComSaida) -> Misturador:
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    misturador.ligar()
    return misturador


def test_sem_fone_o_mic_real_fica_mudo_so_durante_a_fala() -> None:
    grafo = GrafoComSaida([_sink(SAIDA, forma="speaker")])
    misturador = _ligado(grafo)
    politica = politica_de_eco("auto", fone_na_saida(grafo))
    with misturador.enquanto_fala(politica):
        assert grafo.mudos == {77: True} and misturador.abafado
    assert grafo.mudos == {77: False} and not misturador.abafado


def test_o_mic_volta_mesmo_se_a_fala_falhar() -> None:
    grafo = GrafoComSaida()
    misturador = _ligado(grafo)
    with pytest.raises(RuntimeError), misturador.enquanto_fala(politica_de_eco("nao", None)):
        raise RuntimeError("o TTS caiu")
    assert grafo.mudos == {77: False}


def test_com_fone_nada_e_abafado() -> None:
    grafo = GrafoComSaida([_sink(SAIDA, forma="headset")])
    misturador = _ligado(grafo)
    with misturador.enquanto_fala(politica_de_eco("auto", fone_na_saida(grafo))):
        pass
    assert grafo.mudos == {}
    assert not any(c[1:2] == ("set-sink-input-mute",) for c in grafo.comandos)


def test_desligado_ou_sem_o_fluxo_nao_derruba_a_fala() -> None:
    grafo = GrafoComSaida()
    desligado = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    with desligado.enquanto_fala(politica_de_eco("nao", None)):
        pass
    assert grafo.mudos == {}

    class SemFluxo(GrafoComSaida):
        def rodar(self, argv: Sequence[str]) -> Saida:
            if tuple(argv)[1:] == ("-f", "json", "list", "sink-inputs"):
                return Saida(0, "[]")
            return super().rodar(argv)

    sem = SemFluxo()
    misturador = _ligado(sem)
    with misturador.enquanto_fala(politica_de_eco("nao", None)):
        pass
    assert sem.mudos == {} and any("abafar" in a for a in misturador.avisos)


def test_desligar_esquece_o_mudo() -> None:
    grafo = GrafoComSaida()
    misturador = _ligado(grafo)
    misturador.abafar(True)
    misturador.desligar()
    assert not misturador.abafado and not misturador.ligado
