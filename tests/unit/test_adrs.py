"""Aceite F0-10: ADR com número traz hardware, `n`, data e commit; nada de suposição solta."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.adr import conferir, conferir_adr

RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "docs" / "adr"

ADRS_DE_MEDICAO = (
    "0012-licencas-verificadas-na-origem.md",
    "0013-ativacao-de-grafo-medida.md",
    "0014-d1-linguagem-e-ipc-do-nucleo.md",
)


def test_todas_as_adrs_do_repositorio_tem_procedencia() -> None:
    """Aceite (a) e (b), na parte que dá para verificar por máquina."""
    assert conferir(PASTA) == []


@pytest.mark.parametrize("nome", ADRS_DE_MEDICAO)
def test_adr_de_medicao_cita_commit_e_n(nome: str) -> None:
    texto = (PASTA / nome).read_text(encoding="utf-8")

    assert "**Data:**" in texto
    assert "Commit" in texto
    assert "`n`" in texto or " n " in texto
    assert conferir_adr(PASTA / nome) == []


def test_adr_de_d1_registra_a_lacuna_e_quem_decide() -> None:
    """O cartão F0-04 pediu proposta com a lacuna explícita; a ADR tem de dizer isso."""
    texto = (PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md").read_text(encoding="utf-8")

    assert "**Decide:** dono" in texto
    assert "lacuna" in texto.casefold()
    assert "AEC" in texto
    assert "ASR" in texto
    assert "Como invalidar esta decisão" in texto


def test_verificador_pega_adr_sem_commit(tmp_path: Path) -> None:
    """Se o verificador não acusar isto, ele não serve para o aceite (a)."""
    (tmp_path / "0099-exemplo.md").write_text(
        "# ADR-0099 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor\n"
        "**Mede:** executor\n\n"
        "## Contexto\n\nFicou em 12,3 ms p95, que é rápido.\n",
        encoding="utf-8",
    )

    problemas = [p.o_que for p in conferir(tmp_path)]

    assert any("commit" in p for p in problemas)
    assert any("hardware" in p for p in problemas)
    assert any("`n`" in p for p in problemas)


def test_verificador_pega_suposicao_sem_o_que_a_confirma(tmp_path: Path) -> None:
    (tmp_path / "0098-exemplo.md").write_text(
        "# ADR-0098 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** proposta · **Decide:** dono\n\n"
        "## Contexto\n\nIsto vai funcionar **[SUPOSIÇÃO]** e pronto.\n",
        encoding="utf-8",
    )

    problemas = [p.o_que for p in conferir(tmp_path)]

    assert any("SUPOSIÇÃO" in p for p in problemas)


def test_spec_registra_os_slos_confirmados() -> None:
    """Aceite (c): a §7 não pode continuar dizendo [SUPOSIÇÃO] no que já foi medido."""
    spec = (RAIZ / "docs" / "SPEC-v0.md").read_text(encoding="utf-8")

    linha_slo11 = next(linha for linha in spec.splitlines() if "| SLO-11 |" in linha)
    linha_slo12 = next(linha for linha in spec.splitlines() if "| SLO-12 |" in linha)

    assert "SUPOSIÇÃO" not in linha_slo11
    assert "ADR-0013" in linha_slo11
    assert "ADR-0013" in linha_slo12


def test_spec_registra_d1_com_a_proposta_e_a_lacuna() -> None:
    spec = (RAIZ / "docs" / "SPEC-v0.md").read_text(encoding="utf-8")

    assert "DECISÃO ABERTA D1" not in spec
    assert "ADR-0014" in spec
    assert "Lacuna explícita" in spec
