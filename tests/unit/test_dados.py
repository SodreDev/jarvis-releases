"""ADR-0020: o produto acha os arquivos de dado fora da árvore do repositório.

Metade das decisões do projeto mora em arquivo de dados (motores, licenças, roteamento,
pesos do S1, catálogo). Dentro da árvore, achar é trivial; instalado, três níveis acima de
`site-packages` é outra coisa — e o aplicativo morreria na primeira tela que lista motores.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis import dados
from jarvis.licencas import ARQUIVO_MODELOS
from jarvis.voz.registro import ARQUIVO_MOTORES


def test_na_arvore_os_arquivos_de_dado_sao_os_do_repositorio() -> None:
    assert ARQUIVO_MOTORES.exists() and ARQUIVO_MOTORES.name == "motores.toml"
    assert ARQUIVO_MODELOS.exists() and ARQUIVO_MODELOS.name == "modelos.toml"
    assert dados.raiz_do_repositorio() is not None


def test_a_variavel_do_empacotador_tem_precedencia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """É assim que o AppImage, o `.deb` e o `.rpm` dizem onde puseram os dados."""
    (tmp_path / "licenses").mkdir()
    (tmp_path / "licenses" / "motores.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv(dados.VARIAVEL, str(tmp_path))

    assert dados.caminho("licenses/motores.toml") == tmp_path / "licenses" / "motores.toml"
    assert dados.bases()[0] == tmp_path


def test_sem_arvore_e_sem_variavel_a_procura_cai_no_prefixo(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(dados.VARIAVEL, raising=False)
    monkeypatch.setattr(dados, "raiz_do_repositorio", lambda: None)

    assert dados.bases()[-1].as_posix().endswith("share/jarvis")


def test_arquivo_que_nao_existe_devolve_caminho_util(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mensagem de erro com caminho vazio não ajuda ninguém a consertar a instalação."""
    monkeypatch.delenv(dados.VARIAVEL, raising=False)

    achado = dados.caminho("licenses/nao-existe.toml")

    assert achado.name == "nao-existe.toml"
    assert achado.parent.name == "licenses"
