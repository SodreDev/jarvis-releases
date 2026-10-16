"""Higiene de publicação: o que a tabela diz sem o leitor precisar do rodapé.

Achados 9 e 10 da revisão independente F0+F1. Os dois são da mesma família: número com viés
publicado ao lado de número sem viés, e veredito de SLO dado quando só o **piso de software**
foi medido. Quem lê tabela não lê rodapé — então a tabela tem de se defender sozinha.
"""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ADR_DE_D1 = RAIZ / "docs" / "adr" / "0014-d1-linguagem-e-ipc-do-nucleo.md"
QUADRO_DO_DISPOSITIVO = "**Piso do dispositivo"


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
