"""ADR-0074 (decisão do dono, 2026-11-17): o TOTP que reconhece o dono numa chamada.

Vetores da RFC 6238 (apêndice B, SHA-1), janela ±1, uso único entre chamadas e depois de
reiniciar, bloqueio por erros. Relógio injetado; nenhum chaveiro real (a guarda é em memória)."""

from __future__ import annotations

import base64
import json
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from jarvis.chamada.totp import (
    DIGITOS,
    VARIAVEL,
    EstadoDoTotp,
    GuardaEmMemoria,
    GuardaNoChaveiro,
    SegredoInvalido,
    Veredito,
    Verificador,
    gerar_segredo,
    hotp,
    totp,
    uri_otpauth,
)

SEGREDO_DA_RFC = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("instante", "esperado"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_vetores_da_rfc_6238(instante: int, esperado: str) -> None:
    assert totp(SEGREDO_DA_RFC, instante, digitos=8) == esperado


def test_vetores_da_rfc_4226() -> None:
    esperados = ["755224", "287082", "359152", "969429", "338314"]
    assert [hotp(SEGREDO_DA_RFC, i) for i in range(5)] == esperados


def test_segredo_novo_tem_160_bits_e_e_sempre_outro() -> None:
    a, b = gerar_segredo(), gerar_segredo()
    assert a != b
    assert len(base64.b32decode(a + "=" * (-len(a) % 8))) == 20


def test_uri_otpauth_tem_o_que_o_autenticador_le() -> None:
    segredo = gerar_segredo()
    uri = urlparse(uri_otpauth(segredo))
    assert (uri.scheme, uri.netloc, uri.path) == ("otpauth", "totp", "/Jarvis:dono")
    q = parse_qs(uri.query)
    assert q["secret"] == [segredo] and q["issuer"] == ["Jarvis"]
    assert q["digits"] == [str(DIGITOS)] and q["period"] == ["30"]
    with pytest.raises(SegredoInvalido):
        uri_otpauth("não é base32!")


def _verificador(tmp_path: Path, agora: list[float]) -> Verificador:
    return Verificador(
        guarda=GuardaEmMemoria(SEGREDO_DA_RFC),
        estado=EstadoDoTotp.ler(tmp_path / "totp-estado.json"),
        relogio=lambda: agora[0],
    )


def test_aceita_a_janela_atual_e_um_passo_para_cada_lado(tmp_path: Path) -> None:
    agora = [1_000_000.0]
    for desvio in (-30, 0, 30):
        agora[0] += 120  # cada código num passo novo
        verificador = _verificador(tmp_path, agora)
        assert verificador.conferir(totp(SEGREDO_DA_RFC, agora[0] + desvio)) is Veredito.ACEITO
    agora[0] += 120
    assert _verificador(tmp_path, agora).conferir(totp(SEGREDO_DA_RFC, agora[0] + 90)) is (
        Veredito.ERRADO
    )


def test_replay_do_mesmo_codigo_e_recusado_mesmo_depois_de_reiniciar(tmp_path: Path) -> None:
    agora = [1_700_000_000.0]
    codigo = totp(SEGREDO_DA_RFC, agora[0])
    assert _verificador(tmp_path, agora).conferir(codigo) is Veredito.ACEITO
    agora[0] += 10  # mesma janela, outra chamada, outro processo
    assert _verificador(tmp_path, agora).conferir(codigo) is Veredito.REUSADO
    # um código ANTERIOR ao aceito (gravado antes, tocado agora) também não vale
    anterior = totp(SEGREDO_DA_RFC, agora[0] - 30)
    assert _verificador(tmp_path, agora).conferir(anterior) is Veredito.REUSADO


def test_estado_so_tem_numeros_e_e_privado(tmp_path: Path) -> None:
    agora = [1_700_000_000.0]
    _verificador(tmp_path, agora).conferir(totp(SEGREDO_DA_RFC, agora[0]))
    arquivo = tmp_path / "totp-estado.json"
    dados = json.loads(arquivo.read_text())
    assert set(dados) == {"ultimo_passo", "erros"}
    assert SEGREDO_DA_RFC not in arquivo.read_text()
    assert stat.S_IMODE(arquivo.stat().st_mode) == 0o600


def test_erros_demais_bloqueiam_ate_o_dono_liberar(tmp_path: Path) -> None:
    agora = [1_700_000_000.0]
    verificador = _verificador(tmp_path, agora)
    for _ in range(verificador.erros_por_dia):
        assert verificador.conferir("000000") is Veredito.ERRADO
    assert verificador.conferir(totp(SEGREDO_DA_RFC, agora[0])) is Veredito.BLOQUEADO
    verificador.liberar()
    assert verificador.conferir(totp(SEGREDO_DA_RFC, agora[0])) is Veredito.ACEITO


def test_formato_errado_nao_conta_como_erro_e_sem_segredo_nao_aceita(tmp_path: Path) -> None:
    agora = [1_700_000_000.0]
    verificador = _verificador(tmp_path, agora)
    assert verificador.conferir("12 34") is Veredito.FORMATO
    assert verificador.estado.erros == []
    vazio = Verificador(guarda=GuardaEmMemoria(), relogio=lambda: agora[0])
    assert vazio.conferir("123456") is Veredito.SEM_SEGREDO


def test_codigo_dito_com_espacos_e_tracos_vale(tmp_path: Path) -> None:
    agora = [1_700_000_000.0]
    codigo = totp(SEGREDO_DA_RFC, agora[0])
    falado = f"{codigo[:3]} - {codigo[3:]}"
    assert _verificador(tmp_path, agora).conferir(falado) is Veredito.ACEITO


def test_guarda_no_chaveiro_le_o_ambiente_primeiro() -> None:
    guarda = GuardaNoChaveiro(ambiente={VARIAVEL: SEGREDO_DA_RFC})
    assert guarda.ler() == SEGREDO_DA_RFC
