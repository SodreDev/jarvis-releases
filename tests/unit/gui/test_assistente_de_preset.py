"""Configurar provedor sem confusão (dono, 2026-10-30): ligou o Groq num preset e o Jarvis «não
deixou por causa de outros modos». Causa medida: o «ligar» da janela valia só para a janela — a
conversa aberta congelava a nuvem ao abrir e recusava com «está desligado … (ADR-0017)». Aqui, na
janela offscreen e no roteador do cérebro, sem rede e sem chave de verdade:

- o assistente curto mostra cada passo (provedor → chave → nuvem → modelo → esforço → papel →
  salvar) com ✓ ou o que falta e como destravar;
- ligar na janela vale **na hora** para o cérebro da conversa (a mesma fonte de presets);
- cada bloqueio do portão vira frase com o quê, o porquê e o como, e uma curta para a voz;
- o Groq com visão entra num preset de visão em poucos passos.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui.ponte import Ponte
from jarvis.provedores.bloqueio import bloqueio_do_preset
from jarvis.provedores.interface import Papel, ProvedorIndisponivel
from jarvis.provedores.nucleo import Provedores
from jarvis.provedores.presets import FonteDePresets, Preset
from jarvis.provedores.roteador import MotorDosPresets
from jarvis.s2.motor import Contexto, Fim, Mensagem, Modo, MotivoDoFim, Texto
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.interface import nunca_cancelado
from jarvis.voz.registro import MotorRecusado
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
)
from tests.unit.gui.test_modelos_na_janela import (  # noqa: F401 — `ambiente` é fixture
    _esperar,
    _item,
    _ponte,
    ambiente,
)

GROQ = "conversa-groq"
VISAO_DO_GROQ = "qwen/qwen3.8-27b"


def _passos(lista: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {p["passo"]: p for p in lista}


def test_o_assistente_diz_o_que_falta_em_cada_passo_e_como_destravar(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None, aplicativo: QGuiApplication
) -> None:
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos
    modelos.abrirProvedor(GROQ)
    _esperar(aplicativo, 2.0, ate=lambda: modelos.falta != "")

    passos = _passos(modelos.conferir(GROQ, VISAO_DO_GROQ, "low", "visao", "", 0))
    assert passos["provedor"]["ok"] and "Groq" in passos["provedor"]["frase"]
    # sem chaveiro (CI): a chave não existe — a frase diz o nome da variável e onde guardar
    assert not passos["chave"]["ok"] and "JARVIS_GROQ_API_KEY" in passos["chave"]["frase"]
    assert not passos["nuvem"]["ok"] and "li o aviso — ligar Groq" in passos["nuvem"]["frase"]
    assert passos["modelo"]["ok"] and passos["esforço"]["ok"]
    assert passos["papel"]["ok"], passos["papel"]  # o qwen do Groq vê imagem (registro)
    assert not passos["salvar"]["ok"] and "salvar preset" in passos["salvar"]["frase"]

    modelos.ligarProvedor(GROQ, True)
    passos = _passos(modelos.conferir(GROQ, VISAO_DO_GROQ, "low", "visao", "visão groq", 1))
    assert passos["nuvem"]["ok"] and passos["salvar"]["ok"]
    assert modelos.aviso.startswith("Groq ligado — vale já")


def test_esforco_que_o_modelo_nao_aceita_e_visao_sem_ver_sao_ditos(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None
) -> None:
    modelos = cast(Any, _ponte(tmp_path, ambiente)).modelos
    passos = _passos(modelos.conferir(GROQ, "openai/gpt-oss-20b", "xhigh", "visao", "x", 0))
    assert not passos["esforço"]["ok"] and "não vale para este modelo" in passos["esforço"]["frase"]
    assert not passos["papel"]["ok"] and "não vê imagem" in passos["papel"]["frase"]
    assert modelos.conferir("", "", "", "", "", 0)[0]["frase"].startswith("escolha um provedor")


def test_ligar_na_janela_vale_na_hora_para_o_cerebro_da_conversa(
    tmp_path: Path, ambiente: dict[str, str], sem_chaveiro: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conversa já aberta: antes, só reabrindo. O cérebro lê a nuvem da mesma fonte da janela."""
    tela = cast(Any, _ponte(tmp_path, ambiente))
    fonte: FonteDePresets = tela.modelos.fonte
    provedores = Provedores(ligados=frozenset(), ambiente=ambiente)

    class _Motor:
        nome = "groq falso"
        aceita_imagem = False

        @property
        def onde(self) -> Any:
            from jarvis.voz.interface import Onde

            return Onde.NUVEM

        def gerar(self, contexto: Contexto, modo: Modo, cancelado: Any) -> Any:
            yield Texto("Oi.")
            yield Fim(MotivoDoFim.CONCLUIDO)

    class _Provedor:
        def motor(self, *_a: Any) -> _Motor:
            return _Motor()

    monkeypatch.setattr(Provedores, "abrir", lambda _self, _identificador: _Provedor())
    roteador = MotorDosPresets(fonte=fonte, provedores=provedores)
    fonte.gravar(
        fonte.atuais().com_preset(
            Preset("rápido", Papel.CEREBRO, GROQ, "openai/gpt-oss-20b", "low")
        )
    )
    fonte.gravar(fonte.atuais().com_ativo(Papel.CEREBRO, "rápido"))
    contexto = Contexto(sistema="s", mensagens=(Mensagem("dono", "oi"),))

    recusado = list(roteador.gerar(contexto, Modo.RAPIDO, nunca_cancelado))
    assert isinstance(recusado[0], Texto) and "desligado" in recusado[0].texto
    assert isinstance(recusado[-1], Fim) and recusado[-1].motivo is MotivoDoFim.ERRO
    assert "Como destravar:" in recusado[-1].detalhe and "ADR" not in recusado[-1].detalhe

    tela.modelos.ligarProvedor(GROQ, True)  # o clique na janela, com a conversa aberta

    respondido = list(roteador.gerar(contexto, Modo.RAPIDO, nunca_cancelado))
    assert [d.texto for d in respondido if isinstance(d, Texto)] == ["Oi."]
    assert roteador.codigo == "conversa-groq/openai/gpt-oss-20b"

    tela.modelos.ligarProvedor(GROQ, False)  # desligar também vale na hora
    de_novo = list(roteador.gerar(contexto, Modo.RAPIDO, nunca_cancelado))
    assert isinstance(de_novo[-1], Fim) and de_novo[-1].motivo is MotivoDoFim.ERRO


@pytest.mark.parametrize(
    ("erro", "codigo", "trecho"),
    [
        (MotorRecusado("motor 'conversa-groq' é de nuvem e está desligado"), "nuvem_desligada",
         "li o aviso — ligar"),
        (SegredoAusente("JARVIS_GROQ_API_KEY ausente"), "sem_chave", "Chaves de API"),
        (MotorRecusado("licença 'x' não é permissiva"), "licenca", "registro"),
        (MotorRecusado("o modelo 'a b' não tem a forma de um id de modelo"), "modelo_invalido",
         "da lista"),
        (MotorRecusado("esforço 'xx' não existe (low, medium)"), "esforco_invalido", "esforço"),
        (ProvedorIndisponivel("codex não está nesta máquina"), "provedor_indisponivel",
         "outro preset"),
    ],
)  # fmt: skip
def test_cada_bloqueio_diz_o_que_por_que_e_como(erro: Exception, codigo: str, trecho: str) -> None:
    preset = Preset("rápido", Papel.CEREBRO, GROQ, "openai/gpt-oss-20b", "low")
    bloqueio = bloqueio_do_preset(preset, erro, Provedores())
    assert bloqueio.codigo == codigo
    frase = bloqueio.frase()
    assert "Por quê:" in frase and "Como destravar:" in frase and trecho in frase
    assert "ADR" not in frase and "rápido" in frase
    assert 0 < len(bloqueio.curta()) <= 120


def test_o_painel_desenha_o_assistente_com_o_passo_da_nuvem(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    tmp_path: Path,
    ambiente: dict[str, str],
    sem_chaveiro: None,
) -> None:
    ponte = _ponte(tmp_path, ambiente)
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.5)
    tela = cast(Any, ponte)
    tela.abrirPainel("configuracao")
    _esperar(aplicativo, 0.6)
    tela.modelos.abrirProvedor(GROQ)
    _esperar(aplicativo, 0.6)

    assert [str(e) for e in janela.errors()] == []
    nuvem = _item(janela, "passo-nuvem")
    assert "✗ nuvem" in str(nuvem.property("text"))
    tela.modelos.ligarProvedor(GROQ, True)
    _esperar(aplicativo, 0.4)
    assert "✓ nuvem" in str(_item(janela, "passo-nuvem").property("text"))
