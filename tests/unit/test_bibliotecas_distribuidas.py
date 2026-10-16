"""ADR-0019: o que o produto **redistribui** cumpre a licença — conferido, não prometido.

Até a janela existir, nenhuma dependência saía desta máquina: a porta de licença só precisava
responder "isto permite uso comercial?". Com AppImage, `.deb` e `.rpm` (ADR-0020), a pergunta
passa a ser a da redistribuição — "o que esta licença me obriga a entregar junto?" —, e é essa
que estes testes cobram, item por item do registro.
"""

from __future__ import annotations

from pathlib import Path

from tools.license_gate import (
    ARQUIVO_BIBLIOTECAS,
    TIPO_BIBLIOTECA,
    conferir_bibliotecas,
    inventariar_bibliotecas,
    tabela_de_bibliotecas,
)

from jarvis.licencas import Categoria

RAIZ = Path(__file__).resolve().parents[2]

QT_NO_REGISTRO = """
[[biblioteca]]
id = "PySide6-Essentials"
versao = "6.9.3"
papel = "janela"
licenca = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
licenca_escolhida = "{escolhida}"
estado = "em_uso"
ligacao = "{ligacao}"
modificada = {modificada}
distribuida = true
fonte = "https://pypi.org/pypi/PySide6-Essentials/6.9.3/json"
data_de_acesso = "2026-10-16"
textos_de_licenca = ["licenses/texto/LGPL-3.0.txt", "licenses/texto/GPL-3.0.txt"]
"""


def _registro(tmp_path: Path, **campos: str) -> Path:
    arquivo = tmp_path / "bibliotecas.toml"
    arquivo.write_text(QT_NO_REGISTRO.format(**campos), encoding="utf-8")
    return arquivo


def test_o_registro_do_repositorio_cumpre_as_obrigacoes() -> None:
    """O que está comitado tem de passar: é o que vai dentro dos três artefatos."""
    falhas, _avisos = conferir_bibliotecas()

    assert falhas == []


def test_o_qt_esta_registrado_como_lgpl_e_nao_bloqueia() -> None:
    itens = {item.nome.split(" ")[0]: item for item in inventariar_bibliotecas()}

    qt = itens["PySide6-Essentials"]
    assert qt.tipo == TIPO_BIBLIOTECA
    assert qt.licenca == "LGPL-3.0-only"  # a escolhida, não a expressão inteira
    assert qt.categoria is Categoria.PERMISSIVA  # a régua da ADR-0011 trata LGPL assim
    assert not qt.bloqueia


def test_ligacao_estatica_em_lgpl_falha(tmp_path: Path) -> None:
    """Ligar estaticamente tira do dono o direito de re-ligar — é a obrigação central."""
    arquivo = _registro(tmp_path, escolhida="LGPL-3.0-only", ligacao="estatica", modificada="false")

    falhas, _ = conferir_bibliotecas(arquivo)

    assert any("re-ligar" in falha for falha in falhas)


def test_biblioteca_copyleft_modificada_falha(tmp_path: Path) -> None:
    arquivo = _registro(tmp_path, escolhida="LGPL-3.0-only", ligacao="dinamica", modificada="true")

    falhas, _ = conferir_bibliotecas(arquivo)

    assert any("modificada" in falha for falha in falhas)


def test_licenca_escolhida_fora_da_expressao_falha(tmp_path: Path) -> None:
    """Escolher uma permissão que a origem não publicou é inventar permissão."""
    arquivo = _registro(tmp_path, escolhida="MIT", ligacao="dinamica", modificada="false")

    falhas, _ = conferir_bibliotecas(arquivo)

    assert any("não está na expressão" in falha for falha in falhas)


def test_item_fora_do_notice_falha(tmp_path: Path) -> None:
    arquivo = tmp_path / "bibliotecas.toml"
    arquivo.write_text(
        '[[biblioteca]]\nid = "biblioteca-que-ninguem-citou"\nlicenca = "MIT"\n'
        'estado = "em_uso"\nligacao = "python"\nfonte = "https://exemplo.invalido"\n'
        'data_de_acesso = "2026-10-16"\n',
        encoding="utf-8",
    )

    falhas, _ = conferir_bibliotecas(arquivo)

    assert any("NOTICE" in falha for falha in falhas)


def test_pacote_ausente_vira_aviso_e_nao_passa_calado(tmp_path: Path) -> None:
    """ "Não dá para conferir" não pode virar "conferido": o CI roda sem o grupo `gui`."""
    arquivo = tmp_path / "bibliotecas.toml"
    arquivo.write_text(
        '[[biblioteca]]\nid = "PySide6-Essentials"\nlicenca = "MIT"\nestado = "em_uso"\n'
        'ligacao = "python"\nfonte = "https://exemplo.invalido"\ndata_de_acesso = "2026-10-16"\n'
        'arquivos_no_pacote = ["nao-existe/LICENCA"]\n',
        encoding="utf-8",
    )
    sumido = tmp_path / "sumido.toml"
    sumido.write_text(
        '[[biblioteca]]\nid = "pacote-que-nao-esta-instalado"\nlicenca = "MIT"\n'
        'estado = "em_uso"\nligacao = "python"\nfonte = "https://exemplo.invalido"\n'
        'data_de_acesso = "2026-10-16"\narquivos_no_pacote = ["qualquer/LICENCA"]\n',
        encoding="utf-8",
    )

    _, avisos = conferir_bibliotecas(sumido)

    assert any("não está instalado aqui" in aviso for aviso in avisos)


def test_o_texto_da_licenca_esta_no_repositorio() -> None:
    """A roda do PySide6 não traz o texto: ele é nosso, e os dois (LGPL e GPL) vão juntos."""
    lgpl = (RAIZ / "licenses" / "texto" / "LGPL-3.0.txt").read_text(encoding="utf-8")
    gpl = (RAIZ / "licenses" / "texto" / "GPL-3.0.txt").read_text(encoding="utf-8")

    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl
    assert "Version 3, 29 June 2007" in lgpl
    assert "GNU GENERAL PUBLIC LICENSE" in gpl


def test_texto_de_licenca_que_sumiu_do_repositorio_falha(tmp_path: Path) -> None:
    arquivo = tmp_path / "bibliotecas.toml"
    arquivo.write_text(
        '[[biblioteca]]\nid = "PySide6-Essentials"\n'
        'licenca = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"\n'
        'licenca_escolhida = "LGPL-3.0-only"\nestado = "em_uso"\nligacao = "dinamica"\n'
        'fonte = "https://exemplo.invalido"\ndata_de_acesso = "2026-10-16"\n'
        'textos_de_licenca = ["licenses/texto/NAO-EXISTE.txt"]\n',
        encoding="utf-8",
    )

    falhas, _ = conferir_bibliotecas(arquivo)

    assert any("não está no repositório" in falha for falha in falhas)


def test_a_tabela_comitada_tem_a_secao_das_bibliotecas() -> None:
    tabela = (RAIZ / "docs" / "licencas.md").read_text(encoding="utf-8")

    assert "## Bibliotecas distribuídas dentro do pacote" in tabela
    assert tabela_de_bibliotecas(ARQUIVO_BIBLIOTECAS) in tabela
    assert "LGPL-3.0-only" in tabela
