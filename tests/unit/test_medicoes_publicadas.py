"""Higiene de publicação: o que a tabela diz sem o leitor precisar do rodapé.

Achados 9 e 10 da revisão independente F0+F1. Os dois são da mesma família: número com viés
publicado ao lado de número sem viés, e veredito de SLO dado quando só o **piso de software**
foi medido. Quem lê tabela não lê rodapé — então a tabela tem de se defender sozinha.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ADR_DE_D1 = RAIZ / "docs" / "adr" / "0014-d1-linguagem-e-ipc-do-nucleo.md"
PASTA_MEDICOES = RAIZ / "docs" / "medicoes"
QUADRO_DO_DISPOSITIVO = "**Piso do dispositivo"
CABECALHO_DO_VEREDITO_TTS = "piso cabe no SLO-5?"
CABECALHO_DO_VEREDITO_BARGE_IN = "piso p95 ≤ 150? (gatilho)"
VEREDITO_CABE = "piso cabe"
VEREDITO_EXCEDE = "piso excede"


def _linhas_da_tabela_com(texto: str, cabecalho: str) -> list[str]:
    """As linhas de dados da tabela cujo cabeçalho traz este rótulo."""
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if not (linha.startswith("|") and cabecalho in linha):
            continue
        dados = []
        for adiante in linhas[i + 2 :]:
            if not adiante.startswith("|"):
                break
            dados.append(adiante)
        assert dados, f"tabela de {cabecalho!r} sem linha de dados"
        return dados
    raise AssertionError(f"nenhuma tabela com {cabecalho!r}")


def test_o_piso_do_dispositivo_nao_fica_na_tabela_dos_medidos() -> None:
    """Achado 9: 20 ms p95 na mesma coluna de 0,096 ms, sem o viés na linha, vicia a leitura.

    O MD do CSV é explícito ("limite superior grosseiro; monitor de saída ociosa"), mas quem lê
    só a tabela da ADR via 20 ms como comparável com o resto. E a decisão D1 depende da cauda:
    publicar lado a lado o que foi medido no caminho real e o que não foi é justamente o que a
    nota de viés queria evitar.
    """
    texto = ADR_DE_D1.read_text(encoding="utf-8")
    antes, marcador, quadro = texto.partition(QUADRO_DO_DISPOSITIVO)

    assert marcador, "o piso do dispositivo precisa de quadro próprio, rotulado"
    assert "dispositivo" not in antes.casefold(), (
        "o piso do dispositivo não pode aparecer na tabela dos medidos no caminho real"
    )
    assert "não medido no caminho real" in quadro
    assert "monitor" in quadro and "limite superior" in quadro, (
        "o viés tem de estar no quadro, não só no MD da medição"
    )


def test_a_coluna_de_veredito_do_tts_fala_de_piso_e_nao_de_slo() -> None:
    """Achado 10: "atinge SLO-5: sim" com p95 de 145 ms é veredito de piso, não de SLO.

    A nota "piso de software, sem fila do dispositivo" só aparecia no cabeçalho do relatório; a
    tabela trazia `sim`, e quem lê tabela conclui que o SLO-5 está fechado e desprioriza o
    F1-16. A fila do driver em USB pode custar 300–500 ms.
    """
    texto = (PASTA_MEDICOES / "f1-09-tts.md").read_text(encoding="utf-8")

    assert "atinge SLO-5?" not in texto
    for linha in _linhas_da_tabela_com(texto, CABECALHO_DO_VEREDITO_TTS):
        assert VEREDITO_CABE in linha or VEREDITO_EXCEDE in linha, linha


def test_a_coluna_de_veredito_do_barge_in_fala_de_piso_e_nao_de_slo() -> None:
    """Mesma estrutura do achado 10 no F1-10: `p95 ≤ 150? sim` lido como "SLO-2 fechado"."""
    texto = (PASTA_MEDICOES / "f1-10-barge-in.md").read_text(encoding="utf-8")

    for linha in _linhas_da_tabela_com(texto, CABECALHO_DO_VEREDITO_BARGE_IN):
        assert VEREDITO_CABE in linha or VEREDITO_EXCEDE in linha, linha


def test_o_rotulo_publicado_vem_do_gerador_e_nao_da_mao() -> None:
    """Rótulo em dois lugares vira rótulo diferente: o do arquivo é o do harness."""
    import tools.harness_barge_in as barge_in
    import tools.harness_tts as tts

    assert tts.CABECALHO_DO_VEREDITO == CABECALHO_DO_VEREDITO_TTS
    assert barge_in.CABECALHO_DO_VEREDITO == CABECALHO_DO_VEREDITO_BARGE_IN
    assert tts.VEREDITO_CABE == barge_in.VEREDITO_CABE == VEREDITO_CABE
    for excede in (tts.VEREDITO_EXCEDE, barge_in.VEREDITO_EXCEDE, barge_in.VEREDITO_EXCEDE_GATILHO):
        assert VEREDITO_EXCEDE in excede, excede
