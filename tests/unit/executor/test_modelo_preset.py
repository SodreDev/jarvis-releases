"""`modelo.preset` pelo executor e pelo atalho do código (ADR-0056): o dono diz "usa o preset
rápido", o preset fica ativo, o Jarvis avisa, e o dono desfaz. Preset de provedor desligado e
pedido vindo de conteúdo de fora não passam."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.politica.atalho import ContextoDoAtalho, Regra, achar
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.memoria import Proveniencia, TurnoCorrente
from jarvis.politica.pdp import Pdp
from jarvis.provedores.presets import FonteDePresets, TrocaPorVoz
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST
from jarvis.voz.config import Configuracao

NUNCA = lambda: False  # noqa: E731
DO_DONO = Proveniencia(turno=TurnoCorrente("ep-1", "usa o preset rápido", "user_voice"), motor="t")


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


def _executor(
    tmp_path: Path, auditoria: LogDeAuditoria, ligados: set[str]
) -> tuple[ExecutorDeFerramentas, FonteDePresets]:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        pasta_do_jarvis=tmp_path / "area",
        session_id="01a1c000-0000-7000-8000-000000000056",
    )
    fonte = FonteDePresets(pasta=tmp_path / "config", configuracao=Configuracao())
    executor = ExecutorDeFerramentas(
        pdp=pdp,
        lar=lar,
        presets=TrocaPorVoz(fonte, ligado=lambda p: p in ligados or p == "conversa-eco"),
    )
    executor.preparar()
    return executor, fonte


def test_o_dono_troca_o_preset_ouve_o_aviso_e_desfaz(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, fonte = _executor(tmp_path, auditoria, {"conversa-groq"})

    feito = executor.executar(
        "modelo.preset", {"nome": "rapido"}, cancelado=NUNCA, proveniencia=DO_DONO
    )

    assert feito.status == "ok", feito.motivo
    assert feito.aviso == "Preset rápido ativo."
    assert fonte.atuais().ativo("cerebro").nome == "rápido"  # type: ignore[union-attr]
    desfeito = executor.executar("acao.desfazer", {}, cancelado=NUNCA, proveniencia=DO_DONO)
    assert desfeito.status == "ok", desfeito.motivo
    assert desfeito.dados["desfeito"] == "a troca para o preset rápido"
    assert fonte.atuais().ativo("cerebro").da_configuracao  # type: ignore[union-attr]


def test_preset_de_nuvem_desligada_volta_como_erro_com_o_caminho(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, fonte = _executor(tmp_path, auditoria, set())
    feito = executor.executar(
        "modelo.preset", {"nome": "rápido"}, cancelado=NUNCA, proveniencia=DO_DONO
    )
    assert feito.status != "ok"
    assert "desligado" in feito.motivo and "janela" in feito.motivo
    assert fonte.atuais().ativo("cerebro").da_configuracao  # type: ignore[union-attr]


def test_turno_que_leu_de_fora_pede_o_sim_e_sem_origem_nega(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, _ = _executor(tmp_path, auditoria, {"conversa-groq"})
    executor.turno.valor = True
    perguntas: list[Confirmacao] = []

    def negar(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return False

    negado = executor.executar(
        "modelo.preset", {"nome": "rápido"}, cancelado=NUNCA, proveniencia=DO_DONO, confirmar=negar
    )
    assert negado.status != "ok" and perguntas
    assert "conteúdo de fora" in perguntas[0].motivo
    sem_origem = executor.executar("modelo.preset", {"nome": "rápido"}, cancelado=NUNCA)
    assert sem_origem.status != "ok"


def test_sem_presets_a_ferramenta_nao_existe_e_tarefa_nao_troca(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor, _ = _executor(tmp_path, auditoria, set())
    assert "modelo.preset" in {t["id"] for t in executor.catalogo_para_o_modelo()}
    executor.presets = None
    assert "modelo.preset" not in {t["id"] for t in executor.catalogo_para_o_modelo()}
    assert not executor.disponivel("modelo.preset")
    assert any("modelo.preset".startswith(prefixo) for prefixo in FORA_DA_ALLOWLIST)


@pytest.mark.parametrize(
    ("fala", "nome"),
    [
        ("usa o preset rápido", "rapido"),
        ("Jarvis, troca para o preset Claude, por favor", "claude"),
        ("ativa o preset visão groq", "visao groq"),
    ],
)
def test_o_atalho_do_codigo_acha_a_troca(fala: str, nome: str) -> None:
    contexto = ContextoDoAtalho(disponivel=lambda tool_id: True, app=lambda _: None)
    atalho = achar(fala, contexto)
    assert atalho is not None and atalho.regra is Regra.TROCAR_PRESET
    assert atalho.tool_id == "modelo.preset" and atalho.args == {"nome": nome}
    sem_a_ferramenta = ContextoDoAtalho(disponivel=lambda tool_id: False, app=lambda _: None)
    assert achar(fala, sem_a_ferramenta) is None
