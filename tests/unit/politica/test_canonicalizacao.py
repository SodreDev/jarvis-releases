"""Aceite F0-06 (c) e (f): forma de caminho, unicode e as armadilhas do Windows.

As regras de forma são lexicais, então estes testes rodam **nos dois sistemas** — é o que
permite provar o item (f) sem máquina Windows. O que exige API do Windows (handle, nome 8.3
de verdade) está marcado como não executado em docs/notas-executor-F0.md.
"""

from __future__ import annotations

import unicodedata

import pytest

from jarvis.politica.canonicalizacao import (
    CaminhoRecusado,
    Sistema,
    canonicalizar,
    normalizar_unicode,
)


def posix(caminho: str) -> str:
    return canonicalizar(caminho, Sistema.POSIX).texto


def windows(caminho: str) -> str:
    return canonicalizar(caminho, Sistema.WINDOWS).texto


# --- (c) travessia e unicode ------------------------------------------------------
def test_ponto_e_ponto_ponto_sao_resolvidos() -> None:
    assert posix("/casa/sodre/./Documentos/../Documentos/nota.txt") == (
        "/casa/sodre/Documentos/nota.txt"
    )


def test_subir_acima_da_raiz_e_recusado() -> None:
    for tentativa in ("/casa/../../etc/shadow", "../../.ssh/id_rsa", "a/../../b"):
        with pytest.raises(CaminhoRecusado, match="sobe acima da raiz"):
            posix(tentativa)


def test_duas_grafias_unicode_do_mesmo_nome_dao_o_mesmo_canonico() -> None:
    """Sem isto, `café` em NFD passa por uma negação escrita em NFC."""
    nfc = unicodedata.normalize("NFC", "/casa/sodre/café/nota.txt")
    nfd = unicodedata.normalize("NFD", "/casa/sodre/café/nota.txt")

    assert nfc != nfd
    assert posix(nfc) == posix(nfd)
    assert normalizar_unicode(nfd) == nfc


def test_byte_nulo_e_caractere_de_controle_sao_recusados() -> None:
    with pytest.raises(CaminhoRecusado, match="byte nulo"):
        posix("/casa/sodre/nota\x00.txt")
    with pytest.raises(CaminhoRecusado, match="caractere de controle"):
        posix("/casa/sodre/no\x07ta.txt")


# --- (f) Windows ------------------------------------------------------------------
def test_fluxo_de_dados_alternativo_e_recusado() -> None:
    with pytest.raises(CaminhoRecusado, match="fluxo de dados alternativo"):
        windows(r"C:\Users\sodre\a.txt:oculto")


def test_nome_8_3_e_recusado() -> None:
    with pytest.raises(CaminhoRecusado, match=r"8\.3"):
        windows(r"C:\Users\sodre\PROGRA~1\x.txt")


@pytest.mark.parametrize("nome", ["CON", "nul", "COM1", "LPT9", "con.txt", "NUL.log"])
def test_dispositivo_reservado_e_recusado(nome: str) -> None:
    with pytest.raises(CaminhoRecusado, match="dispositivo reservado"):
        windows(rf"C:\Users\sodre\{nome}")


def test_unc_e_caminho_de_dispositivo_sao_recusados() -> None:
    for tentativa in (r"\\servidor\compartilhado\x.txt", r"\\?\C:\x.txt", r"\\.\PhysicalDrive0"):
        with pytest.raises(CaminhoRecusado):
            windows(tentativa)


def test_caminho_relativo_a_unidade_e_recusado() -> None:
    with pytest.raises(CaminhoRecusado, match="relativo a unidade"):
        windows("C:nota.txt")


def test_ponto_ou_espaco_na_borda_e_recusado() -> None:
    for tentativa in (
        r"C:\Users\sodre\nota.txt.",
        r"C:\Users\sodre\nota.txt ",
        "C:\\Users\\ sodre",
    ):
        with pytest.raises(CaminhoRecusado, match="ponto ou espaço"):
            windows(tentativa)


def test_case_folding_completo_no_windows() -> None:
    """No Windows, `.SSH` e `.ssh` são a mesma pasta: a política tem de ver o mesmo caminho."""
    assert windows(r"C:\Users\Sodre\.SSH\id_rsa") == windows(r"c:\users\sodre\.ssh\ID_RSA")


def test_caminho_do_windows_mantem_a_unidade_e_separador_unico() -> None:
    assert (
        windows(r"C:\Users\sodre\Documentos\\nota.txt") == "c:\\users\\sodre\\documentos\\nota.txt"
    )


def test_caractere_invalido_do_windows_e_recusado() -> None:
    with pytest.raises(CaminhoRecusado, match="caractere inválido"):
        windows(r"C:\Users\sodre\no*ta.txt")
