"""A porta de licença vê os motores de voz, e um motor LGPL não entra de lado (ADR-0017).

O portão de **execução** (quem barra nuvem desligada e termo vazio) é
`tests/unit/voz/test_registro.py`. Aqui é o portão de **repositório**: o que o CI imprime e
bloqueia, para ninguém descobrir num `git log` que o produto ganhou caminho de saída de dado.
"""

from __future__ import annotations

from pathlib import Path

from _pytest.capture import CaptureFixture
from tools.license_gate import (
    ARQUIVO_MOTORES,
    avisos_de_motores,
    inventariar_motores,
    main,
)

from jarvis.licencas import Categoria

MOTOR_NAO_COMERCIAL = """
data_da_verificacao = "2026-10-15"

[[motor]]
id = "tts-de-pesquisa"
papel = "tts"
onde = "local"
ligado = true
licenca_do_cliente = "CC-BY-NC-4.0"
marca_dagua = "não"
fonte = "https://exemplo.invalid/nc"
data_de_acesso = "2026-10-15"
"""

MOTOR_SEM_LICENCA = """
data_da_verificacao = "2026-10-15"

[[motor]]
id = "tts-misterioso"
papel = "tts"
onde = "local"
ligado = true
licenca_do_cliente = ""
marca_dagua = "não"
fonte = "https://exemplo.invalid/?"
data_de_acesso = "2026-10-15"
"""


def test_motores_do_repositorio_entram_no_inventario() -> None:
    nomes = {item.nome for item in inventariar_motores()}
    assert {"asr-whisper-local", "tts-piper-epitran", "tts-edge"} <= nomes
    papeis = {item.tipo for item in inventariar_motores()}
    assert papeis == {"motor/asr", "motor/tts"}


def test_cliente_nao_comercial_bloqueia_a_porta(tmp_path: Path) -> None:
    arquivo = tmp_path / "motores.toml"
    arquivo.write_text(MOTOR_NAO_COMERCIAL, encoding="utf-8")
    assert main(["--motores", str(arquivo)]) == 1
    assert all(item.bloqueia for item in inventariar_motores(arquivo))


def test_cliente_sem_licenca_declarada_bloqueia(tmp_path: Path) -> None:
    """Licença que ninguém escreveu não é permissiva por otimismo (ADR-0012)."""
    arquivo = tmp_path / "motores.toml"
    arquivo.write_text(MOTOR_SEM_LICENCA, encoding="utf-8")
    assert main(["--motores", str(arquivo)]) == 1
    item = inventariar_motores(arquivo)[0]
    assert item.categoria is Categoria.DESCONHECIDA


def test_a_porta_avisa_quem_manda_dado_para_fora(capsys: CaptureFixture[str]) -> None:
    """Aviso, não bloqueio: bloquear nuvem é em tempo de execução, com o dono presente."""
    assert main([]) == 0
    saida = capsys.readouterr().out
    assert "NUVEM: asr-groq-whisper-large-v3-turbo manda o seu áudio para Groq" in saida
    assert "NUVEM: tts-elevenlabs manda o texto que o Jarvis vai falar" in saida


def test_a_porta_avisa_o_extra_lgpl_e_os_termos_que_faltam(capsys: CaptureFixture[str]) -> None:
    assert main([]) == 0
    saida = capsys.readouterr().out
    assert "EXTRA OPCIONAL: tts-edge" in saida and "LGPL-3.0" in saida
    assert "campos de termo vazios: uso_comercial" in saida


def test_aviso_de_marca_dagua_sai_para_quem_marca(tmp_path: Path) -> None:
    arquivo = tmp_path / "motores.toml"
    arquivo.write_text(
        MOTOR_NAO_COMERCIAL.replace('marca_dagua = "não"', 'marca_dagua = "sim, PerTh"'),
        encoding="utf-8",
    )
    assert any("MARCA D'ÁGUA" in frase for frase in avisos_de_motores(arquivo))


def test_tabela_comitada_tem_a_secao_de_motores() -> None:
    assert main(["--verificar-tabela"]) == 0
    tabela = (ARQUIVO_MOTORES.parent.parent / "docs" / "licencas.md").read_text(encoding="utf-8")
    assert "## Motores de voz" in tabela
    assert "`tts-edge`" in tabela and "nuvem" in tabela
