"""ADR-0020: o peso do modelo não vai no pacote — e o que chega é conferido.

Nenhum teste aqui baixa 63 MB da internet: o servidor é um `http.server` em porta efêmera em
`127.0.0.1`, que é a mesma regra do resto do produto sob `CI=1`.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jarvis.voz.modelos import (
    ArquivoDeModelo,
    Descarga,
    ModeloRecusado,
    baixar,
    descarga_da_voz,
    descargas,
)
from jarvis.voz.nuvem import NuvemRealProibidaEmCI

CONTEUDO = b"peso de mentira, mas com hash de verdade" * 64


class ServidorDePesos(ThreadingHTTPServer):
    """Serve bytes fixos, e conta quantos pedidos recebeu."""

    corpo: bytes = CONTEUDO
    pedidos: int = 0


class Mao(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        servidor = self.server
        assert isinstance(servidor, ServidorDePesos)
        servidor.pedidos += 1
        self.send_response(200)
        self.send_header("Content-Length", str(len(servidor.corpo)))
        self.end_headers()
        self.wfile.write(servidor.corpo)

    def log_message(self, formato: str, *args: object) -> None:
        return None


@pytest.fixture
def servidor() -> Iterator[ServidorDePesos]:
    httpd = ServidorDePesos(("127.0.0.1", 0), Mao)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def descarga_de(servidor: ServidorDePesos, destino: Path, *, sha256: str = "") -> Descarga:
    porta = servidor.server_address[1]
    return Descarga(
        id="exemplo/voz",
        papel="tts",
        licenca="MIT",
        destino=destino,
        arquivos=(
            ArquivoDeModelo(
                nome="voz.onnx",
                bytes=len(CONTEUDO),
                sha256=sha256 or hashlib.sha256(CONTEUDO).hexdigest(),
                url=f"http://127.0.0.1:{porta}/voz.onnx",
            ),
        ),
    )


def test_baixa_confere_e_grava(servidor: ServidorDePesos, tmp_path: Path) -> None:
    descarga = descarga_de(servidor, tmp_path / "vozes")
    progresso: list[tuple[str, int, int]] = []

    escritos = baixar(
        descarga, ao_progresso=lambda n, lidos, total: progresso.append((n, lidos, total))
    )

    assert [c.name for c in escritos] == ["voz.onnx"]
    assert (tmp_path / "vozes" / "voz.onnx").read_bytes() == CONTEUDO
    assert descarga.completa
    assert progresso and progresso[-1][1] == len(CONTEUDO)


def test_hash_diferente_apaga_o_arquivo_e_diz_o_que_esperava(
    servidor: ServidorDePesos, tmp_path: Path
) -> None:
    """Peso trocado no caminho é exatamente o que não se descobre por acidente."""
    descarga = descarga_de(servidor, tmp_path / "vozes", sha256="0" * 64)

    with pytest.raises(ModeloRecusado, match="não confere com o registro"):
        baixar(descarga)

    assert list((tmp_path / "vozes").iterdir()) == [], "sobrou arquivo de um download recusado"


def test_servidor_que_manda_mais_do_que_o_declarado_e_recusado(
    servidor: ServidorDePesos, tmp_path: Path
) -> None:
    descarga = descarga_de(servidor, tmp_path / "vozes")
    servidor.corpo = CONTEUDO * 2

    with pytest.raises(ModeloRecusado, match="mais do que"):
        baixar(descarga)

    assert list((tmp_path / "vozes").iterdir()) == []


def test_o_que_ja_esta_no_disco_nao_e_baixado_de_novo(
    servidor: ServidorDePesos, tmp_path: Path
) -> None:
    descarga = descarga_de(servidor, tmp_path / "vozes")
    baixar(descarga)
    pedidos = servidor.pedidos

    assert baixar(descarga) == []
    assert servidor.pedidos == pedidos


def test_sob_ci_so_base_local(tmp_path: Path) -> None:
    """A voz de verdade mora no Hugging Face: sob `CI=1` isso é recusado, como toda nuvem."""
    descarga = descarga_da_voz("pt_BR-faber-medium", pasta=tmp_path)
    assert descarga is not None

    with pytest.raises(NuvemRealProibidaEmCI):
        baixar(descarga)


def test_o_registro_declara_a_voz_com_tamanho_e_hash() -> None:
    descarga = descarga_da_voz("pt_BR-faber-medium")

    assert descarga is not None
    assert descarga.licenca == "MIT"
    assert len(descarga.arquivos) == 2, "a voz do piper são dois arquivos: o .onnx e o .json"
    assert descarga.tamanho == "63.2 MB", "o tamanho dito ao dono é o do registro"
    for arquivo in descarga.arquivos:
        assert len(arquivo.sha256) == 64, arquivo.nome
        assert arquivo.url.startswith("https://huggingface.co/")
    assert descarga.arquivos[0].tamanho == "63.2 MB"


def test_a_frase_diz_o_tamanho_e_o_destino(tmp_path: Path) -> None:
    descarga = descarga_da_voz("pt_BR-faber-medium", pasta=tmp_path)
    assert descarga is not None

    frase = descarga.frase()

    assert "MB" in frase and str(tmp_path) in frase
    assert "MIT" in frase


def test_toda_descarga_do_registro_tem_hash_e_tamanho() -> None:
    for descarga in descargas():
        assert descarga.arquivos, descarga.id
        for arquivo in descarga.arquivos:
            assert arquivo.bytes > 0 and len(arquivo.sha256) == 64, f"{descarga.id}/{arquivo.nome}"
