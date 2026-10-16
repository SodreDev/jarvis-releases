"""Achado 4 da revisão F0+F1: o endereço do barramento quando o caminho é comprido.

`sun_path` tem ~108 bytes, então pasta de sessão comprida obriga o socket a sair dela. O que
estava errado não era cair para a pasta temporária: era **como**. O nome era previsível (hash
do caminho da raiz), o arquivo nascia fora de qualquer pasta 0700, e entre `unlink` e `bind`
havia corrida num diretório que qualquer usuário local escreve.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from jarvis.barramento.ipc import (
    ARQUIVO_ENDERECO,
    ARQUIVO_SOCKET,
    LIMITE_SUN_PATH,
    PREFIXO_DA_PASTA_CURTA,
    ErroDeIPC,
    conectar,
    criar_endereco,
    endereco,
    preparar_raiz,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="AF_UNIX e modo 0700 são POSIX")


def raiz_comprida(tmp_path: Path) -> Path:
    """Pasta de sessão cujo caminho passa do limite de `sun_path`."""
    raiz = tmp_path / ("sessao-" + "c" * 60) / ("subpasta-" + "d" * 60)
    raiz.mkdir(parents=True)
    assert len(str(raiz / ARQUIVO_SOCKET)) > LIMITE_SUN_PATH
    return raiz


def test_caminho_curto_mantem_o_socket_na_raiz_0700(tmp_path: Path) -> None:
    """O caso normal não muda: o socket mora na pasta de sessão, que já é 0700."""
    preparar_raiz(tmp_path)

    alvo, familia = criar_endereco(tmp_path)

    assert familia == "AF_UNIX"
    assert Path(alvo) == tmp_path / ARQUIVO_SOCKET
    assert not (tmp_path / ARQUIVO_ENDERECO).exists(), "sem desvio, sem ponteiro"


def test_caminho_comprido_vai_para_pasta_privada_com_nome_imprevisivel(tmp_path: Path) -> None:
    raiz = raiz_comprida(tmp_path)
    preparar_raiz(raiz)

    alvo, _ = criar_endereco(raiz)
    pasta = Path(alvo).parent

    assert pasta.name.startswith(PREFIXO_DA_PASTA_CURTA)
    modo = stat.S_IMODE(pasta.stat().st_mode)
    assert modo == 0o700, f"a pasta do socket nasceu {modo:o}, não 0700"
    assert len(alvo) <= LIMITE_SUN_PATH, "não serviria de nada cair para um caminho comprido"
    # O nome não pode ser derivável de fora: era o hash do caminho da raiz.
    import hashlib

    digesto = hashlib.sha256(str(raiz.resolve()).encode("utf-8")).hexdigest()[:16]
    assert digesto not in alvo, "nome previsível deixa um usuário local pré-criar o socket"
    pasta_removivel = pasta
    Path(alvo).unlink(missing_ok=True)
    pasta_removivel.rmdir()


def test_o_cliente_acha_a_pasta_privada_pelo_ponteiro_na_raiz(tmp_path: Path) -> None:
    """Nome imprevisível só funciona se quem conecta souber onde é: o ponteiro fica na raiz."""
    raiz = raiz_comprida(tmp_path)
    preparar_raiz(raiz)

    alvo, _ = criar_endereco(raiz)
    lido, familia = endereco(raiz)

    assert lido == alvo
    assert familia == "AF_UNIX"
    ponteiro = raiz / ARQUIVO_ENDERECO
    assert ponteiro.read_text(encoding="utf-8").strip() == alvo
    Path(alvo).unlink(missing_ok=True)
    Path(alvo).parent.rmdir()


def test_sem_ponteiro_o_endereco_diz_que_o_barramento_nao_subiu(tmp_path: Path) -> None:
    """Ler endereço de uma sessão que ninguém abriu é erro claro, não palpite de caminho."""
    raiz = raiz_comprida(tmp_path)
    preparar_raiz(raiz)

    with pytest.raises(ErroDeIPC, match="não iniciado"):
        endereco(raiz)


def test_servidor_e_cliente_se_acham_em_pasta_comprida(tmp_path: Path) -> None:
    """O aceite de verdade: com raiz comprida, o barramento sobe e o cliente conecta.

    O `Client` do `multiprocessing` só volta depois do desafio HMAC, que o servidor responde
    dentro do `accept` — então quem conecta roda em linha própria, senão os dois esperam um ao
    outro para sempre.
    """
    import threading

    from jarvis.barramento.ipc import Canal, ServidorDoBarramento

    raiz = raiz_comprida(tmp_path)
    servidor = ServidorDoBarramento(raiz)
    do_cliente: list[Canal] = []
    erro: list[BaseException] = []

    def ligar() -> None:
        try:
            do_cliente.append(conectar(raiz, "ui", tentativas=20, espera=0.05))
        except BaseException as falha:  # o teste reporta a falha, não a engole
            erro.append(falha)

    linha = threading.Thread(target=ligar, name="cliente", daemon=True)
    linha.start()
    try:
        aceito = servidor.aceitar()
        try:
            assert aceito.receber(timeout=2.0) == {"registro": "ui"}
        finally:
            aceito.fechar()
    finally:
        linha.join(timeout=10.0)
        for canal in do_cliente:
            canal.fechar()
        servidor.fechar()

    assert not erro, f"cliente não conectou: {erro}"
    assert not (raiz / ARQUIVO_ENDERECO).exists(), "fechar o servidor limpa o desvio"
