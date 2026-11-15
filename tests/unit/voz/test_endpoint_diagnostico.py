"""O teste do endpoint que o dono roda e manda a saída (ADR-0068) — contra servidor falso."""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.voz import endpoint as ep
from jarvis.voz.cli import main as jarvis_voz
from jarvis.voz.endpoint_diagnostico import alvo_do_teste, diagnosticar
from jarvis.voz.nuvem import NuvemRealProibidaEmCI
from tests.unit.voz.endpoint_falso import EndpointFalso, Rota
from tests.unit.voz.test_endpoint import pcm

SEM_ARQUIVO_DO_DONO = Path(__file__).with_name("nao-existe-tts-endpoints.toml")
SEGREDO = "chave-do-endpoint-de-teste-que-nao-pode-vazar-0123"
OPENAPI = {
    "openapi": "3.1.0",
    "paths": {
        "/api/tts": {
            "post": {
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Pedido"}}
                    }
                }
            }
        },
        "/api/tts/stream": {},
        "/api/voices": {},
    },
    "components": {
        "schemas": {
            "Pedido": {
                "required": ["text"],
                "properties": {
                    "text": {"type": "string"},
                    "voice": {"type": "string"},
                    "style": {"type": "string", "enum": ["cordial", "calmo"]},
                },
            }
        }
    },
}


def _servidor_completo(servidor: EndpointFalso) -> None:
    servidor.rotas["/openapi.json"] = Rota(
        corpo=json.dumps(OPENAPI).encode(), tipo="application/json"
    )
    servidor.rotas["/api/voices"] = Rota(
        corpo=json.dumps([{"id": "jarvis-br", "styles": ["cordial", "calmo"]}]).encode(),
        tipo="application/json",
    )
    servidor.rotas["/api/tts"] = Rota(corpo=pcm(24000, valor=4000))
    servidor.rotas["/api/tts/stream"] = Rota(corpo=pcm(24000, valor=4000), pedacos=4, chunked=True)


def _endpoint(base: str, **mudancas: object) -> ep.Endpoint:
    """O preset do dono, com a base do servidor falso (o IP dele nunca é tocado)."""
    preset = ep.escolher("", arquivo=SEM_ARQUIVO_DO_DONO)
    return ep.conferir(replace(preset, base=base, **mudancas))  # type: ignore[arg-type]


def test_o_teste_completo_diz_tudo_e_termina_ok() -> None:
    linhas: list[str] = []
    with EndpointFalso() as servidor:
        _servidor_completo(servidor)
        codigo = diagnosticar(_endpoint(servidor.base), linhas.append, ambiente={"CI": "1"})
    saida = "\n".join(linhas)
    assert codigo == 0, saida
    assert "resolver 127.0.0.1: 127.0.0.1" in saida
    assert "conectar 127.0.0.1" in saida and ": ok em" in saida
    assert "text*:string" in saida and "style:string ['cordial', 'calmo']" in saida
    assert "vozes: jarvis-br" in saida and "estilos: cordial, calmo" in saida
    assert "síntese POST /api/tts: 200" in saida and "stream POST /api/tts/stream: 200" in saida
    assert "1.00 s em PCM16 16 kHz" in saida
    assert "RESULTADO: ok" in saida
    corpos = [json.loads(p.corpo) for p in servidor.pedidos if p.metodo == "POST"]
    assert all(c["text"] == "Teste de voz do Jarvis." for c in corpos)


def test_a_chave_nao_aparece_nem_quando_o_servidor_a_devolve() -> None:
    linhas: list[str] = []
    ambiente = {"CI": "1", "MINHA_TTS_API_KEY": SEGREDO}
    with EndpointFalso() as servidor:
        servidor.rotas["/api/tts"] = Rota(status=401, corpo=f"chave {SEGREDO} recusada".encode())
        endpoint = _endpoint(
            servidor.base,
            caminho_stream="",
            autenticacao="bearer",
            variavel_de_ambiente="MINHA_TTS_API_KEY",
        )
        codigo = diagnosticar(endpoint, linhas.append, ambiente=ambiente)
    saida = "\n".join(linhas)
    assert codigo == 1
    assert SEGREDO not in saida
    assert "MINHA_TTS_API_KEY: definida (ambiente)" in saida
    assert "FALHOU" in saida


def test_servidor_desligado_diz_o_que_conferir() -> None:
    with socket.socket() as soquete:
        soquete.bind(("127.0.0.1", 0))
        porta = soquete.getsockname()[1]
    linhas: list[str] = []
    assert (
        diagnosticar(_endpoint(f"http://127.0.0.1:{porta}"), linhas.append, ambiente={"CI": "1"})
        == 1
    )
    assert "FALHOU" in linhas[-1] and "escutando em" in linhas[-1]


def test_sob_ci_o_servidor_do_dono_nao_e_tocado() -> None:
    with pytest.raises(NuvemRealProibidaEmCI):
        diagnosticar(
            ep.escolher("", arquivo=SEM_ARQUIVO_DO_DONO), lambda _l: None, ambiente={"CI": "1"}
        )


def test_alvo_por_url_usa_o_preset_com_outra_base(tmp_path: Path) -> None:
    ambiente = {"XDG_CONFIG_HOME": str(tmp_path)}
    endpoint = alvo_do_teste("http://127.0.0.1:5000", ambiente=ambiente)
    assert endpoint.base == "http://127.0.0.1:5000" and endpoint.caminho == "/api/tts"
    assert alvo_do_teste("", ambiente=ambiente).nome == "JARVIS-BR (phonon-web)"


def test_pela_linha_de_comando(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ambiente = {"CI": "1", "XDG_CONFIG_HOME": str(tmp_path)}
    with EndpointFalso() as servidor:
        _servidor_completo(servidor)
        codigo = jarvis_voz(["--testar-endpoint", servidor.base], ambiente=ambiente)
    saida = capsys.readouterr().out
    assert codigo == 0 and "RESULTADO: ok" in saida
    assert jarvis_voz(["--testar-endpoint", "não existe"], ambiente=ambiente) == 2
