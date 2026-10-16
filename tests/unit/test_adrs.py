"""Aceite F0-10: ADR com número traz hardware, `n`, data e commit; nada de suposição solta."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.adr import alcance_da_conferencia, conferir, conferir_adr, conferir_numeros

RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "docs" / "adr"
MEDICOES = RAIZ / "docs" / "medicoes"

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


def test_adr_de_d1_registra_a_lacuna_o_decisor_e_o_gatilho() -> None:
    """D1 foi aceita com a lacuna no texto: o gatilho de reabertura tem de ser verificável."""
    texto = (PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md").read_text(encoding="utf-8")

    assert "**Estado:** aceita" in texto
    assert "**Decide:** orquestrador" in texto  # delegação do dono, registrada
    assert "lacuna" in texto.casefold()
    assert "AEC" in texto
    assert "ASR" in texto
    assert "Gatilho de reabertura" in texto
    assert "80 ms" in texto and "150 ms" in texto
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


# --- achado 3: o número publicado tem de ser o número medido -----------------------
def test_os_numeros_da_adr_de_d1_sao_os_do_csv() -> None:
    """Achado 3 da revisão F0+F1: a tabela da ADR-0014 deixou de bater com o CSV.

    O `conferir` só olhava a ESTRUTURA da tabela (tem p50? tem p95?), então a republicação do
    commit `5feb551` (que trocou a medição de fumaça pela de n = 10 000) passou sem ninguém
    notar que a ADR continuava com os números velhos — inclusive no p99 do piso, 0,086 ms
    contra 0,290 ms medidos, que é 3,4× na cauda, justamente onde o SLO-1 dói.
    """
    assert conferir_numeros(PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md", MEDICOES) == []


def test_a_conferencia_de_numeros_cobre_a_medicao_de_d1() -> None:
    """Conferência que não confere nada passaria sempre: o alcance é parte do aceite."""
    alcance = alcance_da_conferencia(PASTA / "0014-d1-linguagem-e-ipc-do-nucleo.md", MEDICOES)

    assert alcance.csvs == ("f0-04-captura.csv",)
    assert alcance.valores >= 20, "a tabela de D1 tem seis linhas; conferir menos é vacuidade"
    assert alcance.fora == ()


def test_a_conferencia_pega_numero_editado_na_mao(tmp_path: Path) -> None:
    """Se o verificador não acusar isto, ele não serve para o achado 3."""
    medicoes = tmp_path / "medicoes"
    medicoes.mkdir()
    (medicoes / "exemplo.csv").write_text(
        "braco,execucao,n,p50_ms,p95_ms\nrapido,1,100,1.000,2.000\nrapido,2,100,1.000,2.000\n",
        encoding="utf-8",
    )
    adr = tmp_path / "0097-exemplo.md"
    adr.write_text(
        "# ADR-0097 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor\n"
        "**Mede:** executor · **Commit da medição:** `abc1234`\n\n"
        "## Contexto\n\nHardware: Ryzen, `n` = 100 frames. Medição em "
        "`docs/medicoes/exemplo.csv`.\n\n"
        "| braço | p50 | p95 |\n|---|---:|---:|\n| `rapido` | 1,000 ms | **1,500 ms** |\n",
        encoding="utf-8",
    )

    problemas = [p.o_que for p in conferir_numeros(adr, medicoes)]

    assert any("p95" in p and "1,500" in p and "2.0" in p for p in problemas), problemas


def test_csv_que_nao_identifica_a_linha_fica_fora_do_alcance_e_dito(tmp_path: Path) -> None:
    """Fora do alcance tem de aparecer, não ser silêncio: é o que impede gate vazio."""
    medicoes = tmp_path / "medicoes"
    medicoes.mkdir()
    (medicoes / "ambiguo.csv").write_text(
        "canal,execucao,com_ritmo,p50_us\nanel,1,1,22.0\nanel,1,0,9.0\n",
        encoding="utf-8",
    )
    adr = tmp_path / "0096-exemplo.md"
    adr.write_text(
        "# ADR-0096 — Exemplo\n\n"
        "**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor\n\n"
        "## Contexto\n\nMedição em `docs/medicoes/ambiguo.csv`.\n\n"
        "| canal | p50 |\n|---|---:|\n| `anel` | 22,0 µs |\n",
        encoding="utf-8",
    )

    alcance = alcance_da_conferencia(adr, medicoes)

    assert alcance.valores == 0
    assert any("mais de uma linha" in motivo for motivo in alcance.fora), alcance.fora
