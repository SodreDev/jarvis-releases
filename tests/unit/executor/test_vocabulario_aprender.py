"""A tool `vocabulario.aprender` (ADR-0044): do pedido do modelo ao arquivo do Jarvis, e de volta.

O vocabulário fica numa pasta do teste, nunca na do dono. O PDP é o de verdade: é ele o portão para
gravar (turno do dono como origem; o sim quando o turno leu conteúdo de fora).
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.memoria import Proveniencia, TurnoCorrente
from jarvis.politica.pdp import Pdp
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST
from jarvis.voz.vocabulario import ARQUIVO_APRENDIDO, RepositorioDoVocabulario

NUNCA = lambda: False  # noqa: E731
DO_DONO = Proveniencia(
    turno=TurnoCorrente("ep-1", "não é discorde, é Discord", "user_voice"), motor="teste"
)
ARGS = {"escrita": "Discord", "ouvido": ["discorde"], "tipo": "app"}


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


def _executor(
    tmp_path: Path, auditoria: LogDeAuditoria, *, com_vocabulario: bool = True
) -> tuple[ExecutorDeFerramentas, list[str]]:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        pasta_do_jarvis=tmp_path / "area",
        session_id="01a1c000-0000-7000-8000-000000000044",
    )
    mudancas: list[str] = []
    executor = ExecutorDeFerramentas(
        pdp=pdp,
        lar=lar,
        vocabulario=RepositorioDoVocabulario(tmp_path / "config") if com_vocabulario else None,
        ao_mudar_vocabulario=lambda: mudancas.append("mudou"),
    )
    executor.preparar()
    return executor, mudancas


def _aprendidos(tmp_path: Path) -> list[dict[str, object]]:
    arquivo = tmp_path / "config" / ARQUIVO_APRENDIDO
    if not arquivo.exists():
        return []
    termos = tomllib.loads(arquivo.read_text(encoding="utf-8")).get("termo", [])
    assert isinstance(termos, list)
    return termos


def test_o_dono_corrige_o_nome_o_jarvis_anota_avisa_e_desfaz(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, mudancas = _executor(tmp_path, auditoria)

    resultado = executor.executar(
        "vocabulario.aprender", ARGS, cancelado=NUNCA, proveniencia=DO_DONO
    )

    assert resultado.status == "ok", resultado.motivo
    assert resultado.aviso == "Anotado: Discord."
    assert resultado.acao_id, "a correção tem de poder ser desfeita"
    (anotado,) = _aprendidos(tmp_path)
    assert anotado["escrita"] == "Discord" and anotado["ouvido"] == ["discorde"]
    assert mudancas == ["mudou"], "o laço não foi avisado: a correção não valeria já"

    desfeito = executor.executar("acao.desfazer", {}, cancelado=NUNCA, proveniencia=DO_DONO)

    assert desfeito.status == "ok", desfeito.motivo
    assert desfeito.dados["desfeito"] == "a correção de Discord"
    assert _aprendidos(tmp_path) == []
    assert mudancas == ["mudou", "mudou"]


def test_o_turno_que_leu_de_fora_pede_o_sim_e_so_o_dono_solta(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, _ = _executor(tmp_path, auditoria)
    executor.turno.valor = True  # o turno já leu uma página ("o certo é …" pode ser dela)
    perguntas: list[Confirmacao] = []

    def negar(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return False

    negado = executor.executar(
        "vocabulario.aprender", ARGS, cancelado=NUNCA, proveniencia=DO_DONO, confirmar=negar
    )
    assert negado.status != "ok"
    assert perguntas and "conteúdo de fora" in perguntas[0].motivo
    assert _aprendidos(tmp_path) == []

    aceito = executor.executar(
        "vocabulario.aprender",
        ARGS,
        cancelado=NUNCA,
        proveniencia=DO_DONO,
        confirmar=lambda _pergunta: True,
    )
    assert aceito.status == "ok", aceito.motivo
    assert len(_aprendidos(tmp_path)) == 1


def test_sem_o_turno_do_dono_o_pdp_nega(tmp_path: Path, auditoria: LogDeAuditoria) -> None:
    executor, _ = _executor(tmp_path, auditoria)

    resultado = executor.executar("vocabulario.aprender", ARGS, cancelado=NUNCA)

    assert resultado.status == "negado"
    assert _aprendidos(tmp_path) == []


def test_palavra_comum_como_apelido_volta_com_o_porque(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, mudancas = _executor(tmp_path, auditoria)

    resultado = executor.executar(
        "vocabulario.aprender",
        {"escrita": "Discord", "ouvido": ["o "]},
        cancelado=NUNCA,
        proveniencia=DO_DONO,
    )

    assert resultado.status == "erro" and "comum" in resultado.motivo
    assert _aprendidos(tmp_path) == [] and mudancas == []


def test_sem_vocabulario_a_tool_nao_existe_para_o_modelo(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, _ = _executor(tmp_path, auditoria, com_vocabulario=False)

    assert "vocabulario.aprender" not in {t["id"] for t in executor.catalogo_para_o_modelo()}
    resultado = executor.executar(
        "vocabulario.aprender", ARGS, cancelado=NUNCA, proveniencia=DO_DONO
    )
    assert resultado.status == "negado" and resultado.causa == "ferramenta_desligada"


def test_com_vocabulario_o_modelo_ve_a_tool_e_a_tarefa_nao_usa() -> None:
    """Aprender um nome é da conversa: uma tarefa em segundo plano não muda como o Jarvis ouve."""
    assert any("vocabulario.aprender".startswith(prefixo) for prefixo in FORA_DA_ALLOWLIST)
