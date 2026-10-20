"""A imagem que vai ao motor (a tela da aba, ADR-0032): tipo e tamanho tirados dos bytes."""

from __future__ import annotations

import base64

import pytest

from jarvis.imagem import ImagemInvalida, da_url_de_dados, dimensoes
from tests.imagens import jpeg_de_cabecalho, png


def test_o_tamanho_sai_do_cabecalho_do_png_e_do_jpeg() -> None:
    assert dimensoes(png(4, 3)) == ("image/png", 4, 3)
    assert dimensoes(jpeg_de_cabecalho(1280, 720)) == ("image/jpeg", 1280, 720)
    with pytest.raises(ImagemInvalida):
        dimensoes(b"GIF89a....")


def test_a_captura_e_conferida_pelos_bytes_e_nao_pelo_que_a_url_diz() -> None:
    dados = png(4, 3)
    url = "data:image/jpeg;base64," + base64.b64encode(dados).decode()  # diz jpeg, é png
    imagem = da_url_de_dados(url, "tela:ab1")
    assert (imagem.id, imagem.tipo, imagem.largura, imagem.altura) == (
        "tela:ab1",
        "image/png",
        4,
        3,
    )
    assert base64.b64decode(imagem.em_base64()) == dados


@pytest.mark.parametrize(
    "url",
    [
        None,
        "https://exemplo.org/a.png",  # não é captura
        "data:text/html;base64,PGh0bWw+",
        "data:image/png,naoebase64",
        "data:image/png;base64,@@@",
        "data:image/png;base64," + base64.b64encode(b"nem png nem jpeg").decode(),
        "data:image/png;base64," + "A" * (8 * 1024 * 1024),  # passa do que o motor aceita
    ],
)
def test_o_que_nao_e_imagem_legivel_e_recusado(url: object) -> None:
    with pytest.raises(ImagemInvalida):
        da_url_de_dados(url, "tela:x")
