"""A trilha de diagnóstico: só metadados, redigida, curta, rotativa e legível pelo diagnóstico."""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.trilha import (
    ARQUIVO,
    TrilhaDeDiagnostico,
    codigo_do_motivo,
    eventos_do_ultimo_turno,
    resumo_do_ultimo_turno,
)


def _linhas(pasta: Path) -> list[dict[str, object]]:
    return [json.loads(linha) for linha in (pasta / ARQUIVO).read_text("utf-8").splitlines()]


def test_texto_e_redigido_e_cortado_e_numero_fica_como_esta(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path, relogio=lambda: 10.0)
    trilha.novo_turno("t-1", motor="eco")
    trilha.evento(
        "ferramenta", tool_id="x", ms=12.5, motivo="chave sk-abcdefghijklmnopqrstuv " + "a" * 400
    )
    evento = _linhas(tmp_path)[1]
    assert evento["turno"] == "t-1" and evento["ms"] == 12.5
    motivo = str(evento["motivo"])
    assert "sk-abcdefghijklmnopqrstuv" not in motivo and "[REDIGIDO:" in motivo
    assert len(motivo) <= 161


def test_gira_o_arquivo_e_guarda_so_as_copias_combinadas(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path, tamanho_maximo=300, copias=2)
    for i in range(40):
        trilha.evento("ferramenta", tool_id=f"t{i}", motivo="m" * 40)
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert nomes == [ARQUIVO, f"{ARQUIVO}.1", f"{ARQUIVO}.2"]
    assert all(p.stat().st_size <= 300 for p in tmp_path.iterdir())


def test_disco_que_falha_nao_derruba_o_turno(tmp_path: Path) -> None:
    arquivo_no_lugar_da_pasta = tmp_path / "ocupado"
    arquivo_no_lugar_da_pasta.write_text("não sou pasta", "utf-8")
    TrilhaDeDiagnostico(arquivo_no_lugar_da_pasta).evento("ferramenta", tool_id="x")


def test_o_resumo_e_do_ultimo_turno_com_ferramenta_permissao_e_fim(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.novo_turno("t-velho", motor="eco")
    trilha.evento("ferramenta", tool_id="velha", status="ok")
    trilha.novo_turno("t-novo", motor="claude")
    trilha.evento(
        "ferramenta",
        tool_id="browser.click",
        status="erro",
        ms=40.0,
        pdp="allow",
        motivo="a página não deixou (alvo_ausente): não achei",
        codigo=codigo_do_motivo("a página não deixou (alvo_ausente): não achei"),
    )
    trilha.evento(
        "permissao", tool_id="sites.open", origem="pdp", motivo="leu terceiros", resposta="não"
    )
    trilha.evento("turno.fim", fim="concluido", ms_total=900.0, ferramentas=2)

    assert [e["turno"] for e in eventos_do_ultimo_turno(tmp_path)] == ["t-novo"] * 4
    texto = "\n".join(resumo_do_ultimo_turno(tmp_path))
    assert "motor claude" in texto and "velha" not in texto
    assert "browser.click: erro em 40 ms (PDP allow) [alvo_ausente]" in texto
    assert "pediu permissão para sites.open (pdp): leu terceiros → não" in texto
    assert "fim: concluido" in texto and "total 900 ms" in texto


def test_sem_trilha_o_resumo_diz_que_nao_ha_turno(tmp_path: Path) -> None:
    assert "nenhum turno" in resumo_do_ultimo_turno(tmp_path / "nada")[0]
