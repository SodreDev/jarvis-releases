"""STT por endpoint HTTP configurável (pedido do dono, 2026-11-14): só a opção. Sem microfone, sem
rede de fora: o servidor é um `http.server` em 127.0.0.1 dentro do teste, e a reserva é falsa."""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from jarvis.voz import app, stt_endpoint
from jarvis.voz.config import ASR_ENDPOINT, Configuracao, ler
from jarvis.voz.endpoint import EndpointInvalido
from jarvis.voz.interface import Hipotese
from jarvis.voz.stt_endpoint import (
    EndpointStt,
    MotorAsrEndpoint,
    de_dados,
    diagnostico,
    escolher,
    extrair_texto,
    montar_pedido,
)

FALA = b"\x01\x00" * 1600


def _endpoint(**campos: Any) -> EndpointStt:
    return stt_endpoint.conferir(EndpointStt(nome="meu stt", base="http://127.0.0.1:9", **campos))


def test_multipart_leva_o_wav_no_campo_e_os_extras() -> None:
    endpoint = _endpoint(campos=(("model", "whisper-1"), ("language", "pt")))
    corpo, tipo = montar_pedido(endpoint, FALA, fronteira="LIMITE")
    assert tipo == "multipart/form-data; boundary=LIMITE"
    assert b'name="model"\r\n\r\nwhisper-1' in corpo
    assert b'name="file"; filename="fala.wav"' in corpo and b"RIFF" in corpo
    assert corpo.endswith(b"--LIMITE--\r\n")


def test_binario_e_base64() -> None:
    corpo, tipo = montar_pedido(_endpoint(envio="binario", formato="pcm"), FALA)
    assert (corpo, tipo) == (FALA, "application/octet-stream")
    corpo, tipo = montar_pedido(_endpoint(envio="base64", campo_do_audio="audio_b64"), FALA)
    dados = json.loads(corpo)
    assert tipo == "application/json"
    assert base64.b64decode(dados["audio_b64"]).startswith(b"RIFF")


@pytest.mark.parametrize(
    ("caminho", "resposta", "texto"),
    [
        ("text", b'{"text": " oi jarvis "}', "oi jarvis"),
        ("results.0.transcript", b'{"results": [{"transcript": "bom dia"}]}', "bom dia"),
        ("", b"texto puro\n", "texto puro"),
    ],
)
def test_o_texto_sai_pelo_caminho_do_json(caminho: str, resposta: bytes, texto: str) -> None:
    assert extrair_texto(_endpoint(campo_do_texto=caminho), resposta) == texto


def test_campo_que_nao_existe_diz_o_que_ha() -> None:
    with pytest.raises(EndpointInvalido, match="transcription"):
        extrair_texto(_endpoint(campo_do_texto="text"), b'{"transcription": "x"}')


@pytest.mark.parametrize(
    "bruto",
    [
        {"nome": "x", "base": "ftp://h"},
        {"nome": "x", "base": "http://u:s@h"},
        {"nome": "x", "base": "http://h", "envio": "telepatia"},
        {"nome": "x", "base": "http://h", "autenticacao": "bearer"},
        {"nome": "x", "base": "http://h", "api_key": "sk-abcdefghijklmnop"},
        {"nome": "x", "base": "http://h", "campos": {"token": "x"}},
        {"nome": "x", "base": "http://h", "campo_errado": 1},
    ],
)
def test_configuracao_ruim_e_recusada_com_o_campo(bruto: dict[str, Any]) -> None:
    with pytest.raises(EndpointInvalido):
        de_dados(bruto)


def test_o_do_dono_vence_pelo_nome_e_o_exemplo_existe(tmp_path: Path) -> None:
    arquivo = tmp_path / "stt-endpoints.toml"
    arquivo.write_text(
        '[[endpoint]]\nnome = "Meu Servidor"\nbase = "http://10.0.0.2:5000"\ncaminho = "/stt"\n'
        'envio = "binario"\nformato = "pcm"\ncampo_do_texto = "texto"\n',
        encoding="utf-8",
    )
    assert escolher("", arquivo=tmp_path / "nada.toml").nome.startswith("Whisper local")
    meu = escolher("meu servidor", arquivo=arquivo)
    assert (meu.base, meu.envio, meu.campo_do_texto) == ("http://10.0.0.2:5000", "binario", "texto")


class _Reserva:
    def __init__(self) -> None:
        self.ouviu = 0

    def transcrever(self, amostras: bytes) -> Hipotese:
        self.ouviu += 1
        return Hipotese("pelo local", 0.9)


def test_endpoint_fora_a_reserva_local_transcreve_e_volta_depois(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agora = [0.0]
    falhar = [True]

    def transcrever(*_: Any, **__: Any) -> str:
        if falhar[0]:
            raise ConnectionError("recusou")
        return "pelo endpoint"

    monkeypatch.setattr(stt_endpoint, "transcrever", transcrever)
    reserva = _Reserva()
    avisos: list[str] = []
    motor = MotorAsrEndpoint(
        endpoint=_endpoint(),
        reserva=lambda: reserva,
        relogio=lambda: agora[0],
        ao_avisar=avisos.append,
    )

    assert motor.transcrever(FALA).texto == "pelo local"
    assert motor.transcrever(FALA).texto == "pelo local"  # dentro do prazo: nem tenta
    falhar[0] = False
    agora[0] = stt_endpoint.RETENTAR_EM_S + 1
    assert motor.transcrever(FALA).texto == "pelo endpoint"
    assert reserva.ouviu == 2
    assert len(avisos) == 2 and "fora" in avisos[0] and "voltou" in avisos[1]


class _Servidor(BaseHTTPRequestHandler):
    recebidos: ClassVar[list[tuple[str, bytes]]] = []

    def do_POST(self) -> None:
        tamanho = int(self.headers.get("Content-Length", "0"))
        _Servidor.recebidos.append((self.headers.get("Content-Type", ""), self.rfile.read(tamanho)))
        corpo = json.dumps({"text": "abre o navegador"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *_: Any) -> None:
        return


@pytest.fixture
def servidor() -> Iterator[str]:
    _Servidor.recebidos = []
    http = HTTPServer(("127.0.0.1", 0), _Servidor)
    linha = threading.Thread(target=http.serve_forever, daemon=True)
    linha.start()
    yield f"http://127.0.0.1:{http.server_address[1]}"
    http.shutdown()
    http.server_close()


def test_o_pedido_de_verdade_vai_em_multipart_e_volta_o_texto(servidor: str) -> None:
    endpoint = stt_endpoint.conferir(EndpointStt(nome="teste", base=servidor, caminho="/v1/t"))

    texto = stt_endpoint.transcrever(endpoint, FALA, ambiente={})

    assert texto == "abre o navegador"
    tipo, corpo = _Servidor.recebidos[0]
    assert tipo.startswith("multipart/form-data; boundary=") and b"RIFF" in corpo


def test_o_diagnostico_nao_tem_segredo_e_diz_cada_fato(servidor: str, tmp_path: Path) -> None:
    arquivo = tmp_path / "stt-endpoints.toml"
    arquivo.write_text(
        f'[[endpoint]]\nnome = "teste"\nbase = "{servidor}"\ncaminho = "/t"\n'
        'autenticacao = "bearer"\nvariavel_de_ambiente = "JARVIS_STT_ENDPOINT_API_KEY"\n',
        encoding="utf-8",
    )
    segredo = "chave-de-teste-1234567890"
    linhas = diagnostico(
        "teste", arquivo=arquivo, ambiente={"JARVIS_STT_ENDPOINT_API_KEY": segredo}
    )
    assert any(linha.startswith("pedido: ok") for linha in linhas)
    assert "chave: definida" in linhas
    assert segredo not in "\n".join(linhas)


def test_a_configuracao_guarda_o_endpoint_e_o_asr_local_nao_muda(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text(f'asr = "{ASR_ENDPOINT}"\nendpoint_stt = "Meu Servidor"\n', encoding="utf-8")
    configuracao = ler(arquivo)
    assert (configuracao.asr, configuracao.endpoint_stt) == (ASR_ENDPOINT, "Meu Servidor")
    assert Configuracao().asr == "asr-whisper-local"


def test_desligado_em_nuvem_ligada_ouve_pelo_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escolher o endpoint não liga nada: sem `asr-endpoint` em `nuvem_ligada`, o local ouve."""
    abertos: list[str] = []

    class WhisperFalso:
        def __init__(self, **_: Any) -> None:
            abertos.append("local")

        def abrir(self) -> None:
            return

    monkeypatch.setattr(app, "MotorWhisper", WhisperFalso)
    monkeypatch.setattr(
        app, "o_que_falta", lambda motor, *_a, **_k: "" if motor != ASR_ENDPOINT else "desligado"
    )
    motor = app.motor_de_asr(
        Configuracao(asr=ASR_ENDPOINT), raiz=Path(), cancelado=lambda: False, ambiente={}
    )
    assert isinstance(motor, WhisperFalso) and abertos == ["local"]
