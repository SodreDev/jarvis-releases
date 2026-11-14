"""Os modos de permissão do dono (ADR-0066): automático e bypass."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp, Pedido, Veredito
from jarvis.politica.permissao import (
    DESTRUTIVAS,
    PERMISSAO_PADRAO,
    ModoDePermissao,
    comando_de_permissao,
    dispensa_o_sim,
    modo_de_permissao,
)
from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler, validar

LAR = Path("/casa/sodre")


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


def _pdp(auditoria: LogDeAuditoria, permissao: ModoDePermissao) -> Pdp:
    return Pdp(
        catalogo=carregar_catalogo(),
        lar=LAR,
        auditoria=auditoria,
        modo=Modo.TOTAL,
        permissao=permissao,
    )


def test_o_padrao_do_dono_e_o_automatico() -> None:
    assert PERMISSAO_PADRAO is ModoDePermissao.AUTOMATICO
    assert Configuracao().permissao == "automatico"
    assert modo_de_permissao("") is ModoDePermissao.AUTOMATICO
    assert modo_de_permissao("bypass") is ModoDePermissao.BYPASS
    # A matriz não é escolha do dono: do arquivo, vira o padrão.
    assert modo_de_permissao("matriz") is ModoDePermissao.AUTOMATICO


@pytest.mark.parametrize("tool_id", sorted(DESTRUTIVAS))
def test_no_automatico_so_o_destrutivo_pede(tool_id: str) -> None:
    assert not dispensa_o_sim(ModoDePermissao.AUTOMATICO, tool_id)
    assert dispensa_o_sim(ModoDePermissao.BYPASS, tool_id)
    assert not dispensa_o_sim(ModoDePermissao.MATRIZ, tool_id)


@pytest.mark.parametrize(
    "tool_id",
    ["browser.avaliar", "browser.acao_sensivel", "input.acao_sensivel", "delegar.claude_code"],
)
def test_o_resto_nao_pede_nem_no_automatico(tool_id: str) -> None:
    assert dispensa_o_sim(ModoDePermissao.AUTOMATICO, tool_id)


def test_pdp_no_automatico_solta_o_envio_e_segura_o_apagar(auditoria: LogDeAuditoria) -> None:
    """O bug do dono: «posso rodar JavaScript?» e «quer que eu mande?» não perguntam mais; apagar
    memória (destrutivo) continua pedindo o sim."""
    pdp = _pdp(auditoria, ModoDePermissao.AUTOMATICO)
    envio = pdp.decidir(Pedido("browser.acao_sensivel", {"acao": "browser.type", "detalhe": "x"}))
    assert envio.veredito is Veredito.ALLOW
    assert "modo automático" in envio.motivo
    script = pdp.decidir(
        Pedido("browser.avaliar", {"codigo": "1"}, exige_o_sim="o guarda pediu o sim")
    )
    assert script.veredito is Veredito.ALLOW
    encerrar = pdp.decidir(
        Pedido("apps.quit", {"app": "kate"}, exige_o_sim="trabalho que pode não estar salvo")
    )
    assert encerrar.veredito is Veredito.CONFIRM


def test_pdp_no_bypass_nada_pede(auditoria: LogDeAuditoria) -> None:
    pdp = _pdp(auditoria, ModoDePermissao.BYPASS)
    encerrar = pdp.decidir(
        Pedido("apps.quit", {"app": "kate"}, exige_o_sim="trabalho que pode não estar salvo")
    )
    assert encerrar.veredito is Veredito.ALLOW
    assert "modo bypass" in encerrar.motivo


@pytest.mark.parametrize("permissao", [ModoDePermissao.AUTOMATICO, ModoDePermissao.BYPASS])
def test_a_lista_de_negacao_vale_nos_dois_modos(
    auditoria: LogDeAuditoria, permissao: ModoDePermissao
) -> None:
    """Segredo nunca é lido (logo nunca impresso nem exfiltrado): não é pedido de permissão."""
    pdp = _pdp(auditoria, permissao)
    decisao = pdp.decidir(Pedido("files.read_text", {}, caminho="/casa/sodre/.ssh/id_ed25519"))
    assert decisao.veredito is Veredito.DENY


def test_a_matriz_solta_continua_pedindo(auditoria: LogDeAuditoria) -> None:
    pdp = _pdp(auditoria, ModoDePermissao.MATRIZ)
    envio = pdp.decidir(Pedido("browser.acao_sensivel", {"acao": "browser.type", "detalhe": "x"}))
    assert envio.veredito is Veredito.CONFIRM


@pytest.mark.parametrize(
    ("fala", "esperado"),
    [
        ("ativa o modo bypass", ModoDePermissao.BYPASS),
        ("Jarvis, modo bypass", ModoDePermissao.BYPASS),
        ("muda para o modo baipass", ModoDePermissao.BYPASS),
        ("liga o modo de permissão bypass", ModoDePermissao.BYPASS),
        ("volta pro modo automático", ModoDePermissao.AUTOMATICO),
        ("modo automático", ModoDePermissao.AUTOMATICO),
        ("o que é o modo bypass?", None),
        ("abre o youtube", None),
        ("manda pra minha mãe que o modo bypass é legal amanhã", None),
    ],
)
def test_a_voz_do_dono_troca_o_modo(fala: str, esperado: ModoDePermissao | None) -> None:
    assert comando_de_permissao(fala) is esperado


def test_o_modo_fica_salvo_no_arquivo(tmp_path: Path) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    escrever(Configuracao().com(permissao="bypass"), caminho)
    assert ler(caminho).permissao == "bypass"
    assert 'permissao = "bypass"' in caminho.read_text(encoding="utf-8")


def test_modo_desconhecido_e_recusado() -> None:
    with pytest.raises(ConfiguracaoInvalida, match="permissao"):
        validar(Configuracao().com(permissao="tudo"))


def test_ordem_vinda_de_conteudo_de_terceiros_pede_o_sim_no_automatico(
    auditoria: LogDeAuditoria,
) -> None:
    """O invariante de não exfiltrar (ADR-0065 + ADR-0066): a ação com efeito depois de ler texto
    que tenta dar ordens não é pedido direto do dono — no automático, ainda pede; no bypass, não."""
    pedido = Pedido(
        "browser.acao_sensivel",
        {"acao": "browser.type", "detalhe": "x"},
        exige_o_sim="o conteúdo lido tenta dar ordens",
        injecao=True,
    )
    assert _pdp(auditoria, ModoDePermissao.AUTOMATICO).decidir(pedido).veredito is Veredito.CONFIRM
    assert _pdp(auditoria, ModoDePermissao.BYPASS).decidir(pedido).veredito is Veredito.ALLOW
