"""O estilo do endpoint de voz trocado pela fala do dono, no laço (ADR-0068)."""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.endpoint import Endpoint, MotorComReservaDeRede, MotorTtsEndpoint, conferir
from tests.unit.voz.endpoint_falso import EndpointFalso, Rota
from tests.unit.voz.test_endpoint import Reserva, pcm


def _aplicativo(tmp_path: Path, motor: object) -> Aplicativo:
    aplicativo = Aplicativo(
        configuracao=Configuracao(tts="tts-endpoint"),
        raiz=tmp_path,
        escrever_na_tela=lambda _linha: None,
        ambiente={"CI": "1", "XDG_CONFIG_HOME": str(tmp_path / "xdg")},
    )
    aplicativo._tts = motor  # type: ignore[assignment]
    return aplicativo


def test_fala_mais_calmo_troca_o_estilo_do_proximo_trecho_e_grava(tmp_path: Path) -> None:
    gravados: list[str] = []
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts"] = Rota(corpo=pcm(240))
        principal = MotorTtsEndpoint(
            endpoint=conferir(
                Endpoint(
                    nome="falso",
                    base=servidor.base,
                    estilo="cordial",
                    estilos=("cordial", "calmo", "urgente"),
                )
            ),
            nuvem_ligada=["tts-endpoint"],
            ambiente={"CI": "1"},
        )
        principal.abrir()
        motor = MotorComReservaDeRede(principal=principal, fabricar_reserva=Reserva)
        aplicativo = _aplicativo(tmp_path, motor)

        def gravar(estilo: str) -> str:
            gravados.append(estilo)
            return "salvo"

        aplicativo.ao_mudar_estilo = gravar
        assert aplicativo._pedir_estilo("abre o Discord") == ""
        # O que aconteceu vai ao Jarvis como dado (ADR-0070); a confirmação falada é dele.
        evento = aplicativo._pedir_estilo("Jarvis, fala mais calmo")
        assert "«calmo»" in evento and "Certo" not in evento
        motor.sintetizar("tudo bem")
    assert gravados == ["calmo"]
    assert aplicativo.configuracao.estilo_endpoint == "calmo"
    assert json.loads(servidor.pedidos[-1].corpo)["style"] == "calmo"


def test_sem_endpoint_nada_e_pedido_de_estilo(tmp_path: Path) -> None:
    aplicativo = _aplicativo(tmp_path, Reserva())
    assert aplicativo._pedir_estilo("fala mais calmo") == ""


def test_a_janela_troca_a_voz_e_o_estilo_com_a_conversa_aberta(tmp_path: Path) -> None:
    principal = MotorTtsEndpoint(
        endpoint=conferir(Endpoint(nome="x", base="http://127.0.0.1:1", voz="a", estilo="cordial"))
    )
    motor = MotorComReservaDeRede(principal=principal, fabricar_reserva=Reserva)
    aplicativo = _aplicativo(tmp_path, motor)
    aplicativo.atualizar_voz_do_endpoint(voz="b", estilo="seco")
    assert (principal.voz, principal.estilo) == ("b", "seco")
    aplicativo.atualizar_voz_do_endpoint(voz="", estilo="")
    assert (principal.voz, principal.estilo) == ("a", "cordial")
