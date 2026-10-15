"""Suíte de TOCTOU do cartão F0-06, itens (a), (b), (d) e (e).

Tudo em pasta temporária: nenhum teste toca o lar do dono. O que se prova aqui é que a
decisão vale sobre o **descritor**, então trocar o caminho no meio da operação não muda o
objeto aberto — e quando a troca acontece, a abertura falha em vez de escapar.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from jarvis.politica.descritor import (
    AberturaRecusada,
    abrir_raiz,
    openat2_disponivel,
)


@pytest.fixture(params=[False, True], ids=["openat2", "componente-a-componente"])
def forcar_fallback(request: pytest.FixtureRequest) -> bool:
    """Os dois caminhos de abertura precisam ter a mesma garantia."""
    return bool(request.param)


def montar(tmp_path: Path) -> tuple[Path, Path]:
    raiz = tmp_path / "raiz"
    fora = tmp_path / "fora"
    (raiz / "sub").mkdir(parents=True)
    fora.mkdir()
    (raiz / "sub" / "dentro.txt").write_text("conteúdo de dentro", encoding="utf-8")
    (fora / "segredo.txt").write_text("conteúdo de fora", encoding="utf-8")
    return raiz, fora


def test_openat2_existe_nesta_maquina_ou_o_fallback_cobre() -> None:
    """Registro do que foi exercitado aqui: se `openat2` falta, o outro caminho é o que vale."""
    assert isinstance(openat2_disponivel(), bool)


def test_abre_arquivo_dentro_da_raiz(tmp_path: Path, forcar_fallback: bool) -> None:
    raiz, _ = montar(tmp_path)
    with abrir_raiz(raiz) as aberta:
        aberta.forcar_fallback = forcar_fallback
        with aberta.abrir("sub/dentro.txt") as alvo:
            assert os.read(alvo.fd, 64).decode("utf-8") == "conteúdo de dentro"


def test_link_simbolico_para_fora_e_recusado(tmp_path: Path, forcar_fallback: bool) -> None:
    raiz, fora = montar(tmp_path)
    (raiz / "atalho.txt").symlink_to(fora / "segredo.txt")
    (raiz / "pasta_atalho").symlink_to(fora)

    with abrir_raiz(raiz) as aberta:
        aberta.forcar_fallback = forcar_fallback
        with pytest.raises(AberturaRecusada):
            aberta.abrir("atalho.txt")
        with pytest.raises(AberturaRecusada):
            aberta.abrir("pasta_atalho/segredo.txt")


def test_toctou_troca_de_link_simbolico_em_corrida(tmp_path: Path, forcar_fallback: bool) -> None:
    """Aceite (a): com um componente alternando entre pasta e link, nada escapa da raiz."""
    raiz, fora = montar(tmp_path)
    # `fora/x.txt` existe de propósito: se a abertura seguisse o link, abriria este arquivo.
    (fora / "x.txt").write_text("ESCAPOU", encoding="utf-8")
    identidade_de_fora = (fora / "x.txt").stat()
    (raiz / "mutante").mkdir()
    (raiz / "mutante" / "x.txt").write_text("conteúdo de dentro", encoding="utf-8")

    parar = threading.Event()
    trocas = {"n": 0}

    def trocar() -> None:
        pasta = raiz / "mutante"
        while not parar.is_set():
            try:
                for item in pasta.iterdir():
                    item.unlink()
                pasta.rmdir()
                (raiz / "mutante").symlink_to(fora)
                trocas["n"] += 1
                (raiz / "mutante").unlink()
                pasta.mkdir()
                (pasta / "x.txt").write_text("conteúdo de dentro", encoding="utf-8")
            except OSError:
                continue

    trocador = threading.Thread(target=trocar, name="trocador", daemon=True)
    trocador.start()
    escapes = 0
    recusas = 0
    try:
        with abrir_raiz(raiz) as aberta:
            aberta.forcar_fallback = forcar_fallback
            for _ in range(400):
                try:
                    with aberta.abrir("mutante/x.txt") as alvo:
                        # Escape é identidade, não conteúdo: o trocador recria o arquivo de
                        # dentro o tempo todo, e um arquivo recém-criado pode estar vazio.
                        mesmo_inode = (
                            alvo.identidade.device == identidade_de_fora.st_dev
                            and alvo.identidade.inode == identidade_de_fora.st_ino
                        )
                        if mesmo_inode or os.read(alvo.fd, 64) == b"ESCAPOU":
                            escapes += 1
                except AberturaRecusada:
                    recusas += 1
                except OSError:
                    recusas += 1
    finally:
        parar.set()
        trocador.join(timeout=5)

    assert escapes == 0, f"{escapes} aberturas escaparam da raiz"
    assert trocas["n"] > 0, "o trocador não conseguiu correr: o teste não provou nada"


def test_hardlink_para_fora_da_raiz_e_recusado(tmp_path: Path, forcar_fallback: bool) -> None:
    """Aceite (b): o caminho está dentro, o inode não — caminho não prova conteúdo."""
    raiz, fora = montar(tmp_path)
    os.link(fora / "segredo.txt", raiz / "parece_nosso.txt")

    with abrir_raiz(raiz) as aberta:
        aberta.forcar_fallback = forcar_fallback
        with pytest.raises(AberturaRecusada, match="hardlink"):
            aberta.abrir("parece_nosso.txt")


def test_raiz_trocada_por_outro_objeto_e_recusada(tmp_path: Path) -> None:
    """Aceite (d): mesma string, outro inode — é o que um ponto de montagem trocado faz."""
    raiz, _ = montar(tmp_path)
    with abrir_raiz(raiz) as aberta:
        assert aberta.ainda_e_a_mesma()

        raiz.rename(tmp_path / "raiz-antiga")
        (tmp_path / "raiz").mkdir()
        (tmp_path / "raiz" / "sub").mkdir()
        (tmp_path / "raiz" / "sub" / "dentro.txt").write_text("outro", encoding="utf-8")

        assert not aberta.ainda_e_a_mesma()
        with pytest.raises(AberturaRecusada, match="não é mais o objeto autorizado"):
            aberta.abrir("sub/dentro.txt")


def test_raiz_apagada_no_meio_da_operacao(tmp_path: Path) -> None:
    """Aceite (e): a raiz desaparece entre duas chamadas — recusa com motivo, não exceção crua."""
    raiz, _ = montar(tmp_path)
    with abrir_raiz(raiz) as aberta:
        aberta.abrir("sub/dentro.txt").fechar()

        (raiz / "sub" / "dentro.txt").unlink()
        (raiz / "sub").rmdir()
        raiz.rmdir()

        assert not aberta.ainda_e_a_mesma()
        with pytest.raises(AberturaRecusada):
            aberta.abrir("sub/dentro.txt")


def test_caminho_absoluto_ou_com_ponto_ponto_nao_e_aceito(tmp_path: Path) -> None:
    raiz, _ = montar(tmp_path)
    with abrir_raiz(raiz) as aberta:
        for tentativa in ("/etc/shadow", "../fora/segredo.txt", "sub/../../fora/segredo.txt"):
            with pytest.raises(AberturaRecusada, match="não é relativo à raiz"):
                aberta.abrir(tentativa)


def test_identidade_do_arquivo_e_conferida(tmp_path: Path) -> None:
    raiz, _ = montar(tmp_path)
    with abrir_raiz(raiz) as aberta, aberta.abrir("sub/dentro.txt") as alvo:
        real = (raiz / "sub" / "dentro.txt").stat()
        assert alvo.identidade.device == real.st_dev
        assert alvo.identidade.inode == real.st_ino
