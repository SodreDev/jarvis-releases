"""A descoberta tolerante das vozes e dos estilos de um endpoint (ADR-0068), com servidor falso."""

from __future__ import annotations

import json
import socket

import pytest

from jarvis.voz import endpoint as ep
from jarvis.voz.endpoint_catalogo import descobrir, vozes_de_json
from tests.unit.voz.endpoint_falso import EndpointFalso, Rota


def _endpoint(base: str, **mudancas: object) -> ep.Endpoint:
    return ep.conferir(
        ep.Endpoint(nome="falso", base=base, prazo_s=2.0, **mudancas)  # type: ignore[arg-type]
    )


def _json(dados: object) -> Rota:
    return Rota(corpo=json.dumps(dados).encode(), tipo="application/json")


@pytest.mark.parametrize(
    ("dados", "ids"),
    [
        (["jarvis-br", "outra"], ["jarvis-br", "outra"]),
        ([{"id": "a", "name": "Voz A"}, {"voice_id": "b"}], ["a", "b"]),
        ({"voices": [{"name": "jarvis-br", "styles": ["cordial", "calmo"]}]}, ["jarvis-br"]),
        ({"vozes": {"jarvis-br": {"idioma": "pt-BR"}}}, ["jarvis-br"]),
        ({"data": [{"slug": "x", "label": "X"}]}, ["x"]),
        ({"ok": True}, []),
        ("texto", []),
        ([{"sem": "id"}, 3, None, 'a"spas'], []),
    ],
)
def test_aceita_as_formas_comuns_de_lista(dados: object, ids: list[str]) -> None:
    vozes, _ = vozes_de_json(dados)
    assert [v.id for v in vozes] == ids


def test_acha_vozes_e_estilos_na_rota_comum_sem_supor_as_outras() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/voices"] = _json(
            {
                "voices": [
                    {
                        "id": "jarvis-br",
                        "name": "Jarvis BR",
                        "language": "pt-BR",
                        "styles": ["cordial", "calmo", "urgente"],
                    },
                ]
            }
        )
        catalogo = descobrir(_endpoint(servidor.base), ambiente={"CI": "1"})
    assert [v.id for v in catalogo.vozes] == ["jarvis-br"]
    assert catalogo.vozes[0].para_dict()["portugues"] is True
    assert catalogo.estilos == ("cordial", "calmo", "urgente")
    assert catalogo.rota_das_vozes == "/voices"
    assert [p.caminho for p in servidor.pedidos] == ["/api/voices", "/voices"]
    assert all(p.metodo == "GET" and p.corpo == b"" for p in servidor.pedidos)


def test_estilos_numa_rota_propria() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/voices"] = _json(["jarvis-br"])
        servidor.rotas["/api/styles"] = _json({"styles": [{"id": "seco"}, {"name": "calmo"}]})
        catalogo = descobrir(_endpoint(servidor.base), ambiente={"CI": "1"})
    assert catalogo.estilos == ("seco", "calmo")
    assert catalogo.rota_dos_estilos == "/api/styles"


def test_servidor_que_nao_lista_nada_vira_campos_livres() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/voices"] = Rota(corpo=b"<html>oi</html>", tipo="text/html")
        catalogo = descobrir(_endpoint(servidor.base), ambiente={"CI": "1"})
    assert catalogo.vozes == () and catalogo.estilos == () and not catalogo.erro
    assert "à mão" in catalogo.frase


def test_rotas_do_endpoint_vencem_as_comuns() -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/minhas/vozes"] = _json(["a"])
        catalogo = descobrir(
            _endpoint(servidor.base, caminhos_de_vozes=("/minhas/vozes",)), ambiente={"CI": "1"}
        )
    assert [v.id for v in catalogo.vozes] == ["a"]
    assert servidor.pedidos[0].caminho == "/minhas/vozes"


def test_servidor_fora_do_ar_e_erro_dito_nao_excecao() -> None:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        porta = soquete.getsockname()[1]
    catalogo = descobrir(_endpoint(f"http://127.0.0.1:{porta}"), ambiente={"CI": "1"})
    assert catalogo.erro and "não deu" in catalogo.frase


def test_sob_ci_o_servidor_do_dono_nao_e_consultado() -> None:
    catalogo = descobrir(
        ep.conferir(ep.Endpoint(nome="x", base="http://192.168.15.9:20202")), ambiente={"CI": "1"}
    )
    assert "CI" in catalogo.erro and catalogo.tentadas == ("/api/voices",)
