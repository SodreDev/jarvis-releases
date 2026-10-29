"""Cliente MCP (ADR-0052): config desligada por padrão, promoção com o tier do dono, tool
proibida recusada, o cliente stdio ponta a ponta com um servidor falso, e a ligação com o
executor/PDP/guarda — o conteúdo do servidor é dado, nunca ordem."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import RespostaEscolha
from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.mcp.cliente import ClienteMcp, TransporteStdio
from jarvis.mcp.config import ConfiguracaoMcpInvalida, ServidorMcp, carregar_mcp
from jarvis.mcp.gestor import GestorMcp
from jarvis.mcp.promocao import McpProibida, promover
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.guarda import GuardaDeContexto
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731
SERVIDOR_FALSO = Path(__file__).with_name("servidor_falso.py")


def _servidor(**kw: Any) -> ServidorMcp:
    base = {
        "nome": "devtools",
        "comando": (sys.executable, "-I", str(SERVIDOR_FALSO)),
        "ligado": True,
        "tier_padrao": "moderado",
        "tiers": {"list_console_messages": "leitura", "navigate_page": "moderado"},
    }
    base.update(kw)
    return ServidorMcp(**base)  # type: ignore[arg-type]


# --- a configuração --------------------------------------------------------------------------


def test_sem_arquivo_a_lista_e_vazia(tmp_path: Path) -> None:
    assert carregar_mcp(tmp_path / "nao-existe.toml") == []


def test_le_servidores_e_o_padrao_e_desligado(tmp_path: Path) -> None:
    alvo = tmp_path / "mcp.toml"
    alvo.write_text(
        '[servidor.devtools]\ncomando = ["npx", "chrome-devtools-mcp"]\n'
        'ligado = true\ntier_padrao = "moderado"\n[servidor.devtools.tools]\n'
        'list_console_messages = "leitura"\n'
        '[servidor.outro]\ncomando = ["x"]\n',  # sem ligado: desligado por padrão
        encoding="utf-8",
    )
    servidores = {s.nome: s for s in carregar_mcp(alvo)}
    assert servidores["devtools"].ligado is True
    assert servidores["devtools"].tier_de("list_console_messages") == "leitura"
    assert servidores["devtools"].tier_de("evaluate_script") == "moderado"  # o padrão
    assert servidores["outro"].ligado is False


def test_arquivo_com_cara_de_segredo_e_recusado(tmp_path: Path) -> None:
    alvo = tmp_path / "mcp.toml"
    alvo.write_text('[servidor.x]\ncomando = ["x"]\napi_key = "sk-abc12345"\n', encoding="utf-8")
    with pytest.raises(ConfiguracaoMcpInvalida, match="segredo"):
        carregar_mcp(alvo)


# --- a promoção (política nossa, ADR-0010) ---------------------------------------------------


def test_promover_usa_o_tier_do_dono_e_nunca_o_do_servidor() -> None:
    servidor = _servidor()
    manifesto = promover(
        servidor, {"name": "navigate_page", "description": "navega", "tier": "livre"}
    )
    assert manifesto["id"] == "mcp.devtools.navigate_page"
    assert manifesto["tier"] == "moderado"  # do dono, não o "tier": "livre" que o servidor mandou
    assert manifesto["trust_input"] == "untrusted"
    leitura = promover(servidor, {"name": "list_console_messages", "description": "lê"})
    assert leitura["tier"] == "livre" and leitura["risk_class"] == "leitura"


def test_tool_proibida_de_promover_e_recusada() -> None:
    with pytest.raises(McpProibida):
        promover(_servidor(), {"name": "shell_exec"})


# --- o cliente stdio ponta a ponta com o servidor falso --------------------------------------


def test_o_cliente_lista_e_chama_as_tools_pelo_stdio() -> None:
    cliente = ClienteMcp(
        transporte=TransporteStdio(comando=(sys.executable, "-I", str(SERVIDOR_FALSO)))
    )
    try:
        nomes = {t["name"] for t in cliente.listar_tools()}
        assert {"list_console_messages", "evaluate_script", "navigate_page"} <= nomes
        resposta = cliente.chamar_tool("evaluate_script", {"expression": "1+1"})
        assert "eco" in str(resposta)
    finally:
        cliente.fechar()


# --- o gestor + o executor + o PDP + o guarda ------------------------------------------------


def _jev(escolha: str = "permitir", p: float = 0.9) -> ClassificadorFalso:
    def roteiro(_e: Any, _p: Any) -> dict[str, Any]:
        return {
            "acao": RespostaEscolha(escolha, p, {escolha: p}),
            "categoria": RespostaEscolha("nenhuma", 0.9, {"nenhuma": 0.9}),
        }

    return ClassificadorFalso(roteiro=roteiro)


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "a.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        gestor = GestorMcp(servidores=[_servidor()])
        ex = ExecutorDeFerramentas(
            pdp=pdp, lar=lar, mcp=gestor, guarda=GuardaDeContexto(classificador=_jev())
        )
        ex.preparar()  # promove as tools do servidor falso
        ex.novo_turno("depura a loja example")
        ex.objetivo.alcancar(["https://loja.example"]) if ex.objetivo else None
        yield ex
        gestor.fechar()


def test_sem_gestor_nenhuma_mcp_existe(tmp_path: Path) -> None:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "a.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        ex = ExecutorDeFerramentas(pdp=pdp, lar=lar)  # sem mcp
        ex.preparar()
        assert not any(t.startswith("mcp.") for t in ex.manifestos)
        assert not ex._ligada("mcp.devtools.evaluate_script")


def test_as_tools_promovidas_entram_no_catalogo_e_rodam_como_dado(
    executor: ExecutorDeFerramentas,
) -> None:
    ids = {t["id"] for t in executor.catalogo_para_o_modelo()}
    assert "mcp.devtools.evaluate_script" in ids
    assert "mcp.devtools.list_console_messages" in ids
    assert "mcp.devtools.shell_exec" not in ids  # proibida: nunca entrou
    r = executor.executar("mcp.devtools.evaluate_script", {"expression": "2+2"}, cancelado=NUNCA)
    assert r.status == "ok"
    assert r.dados["servidor"] == "devtools" and "eco" in str(r.dados["resultado"])


def test_a_leitura_passa_e_o_destino_fora_do_objetivo_pede_o_sim(
    executor: ExecutorDeFerramentas,
) -> None:
    # leitura: o guarda deixa passar direto (nem vai ao Jev).
    console = executor.executar("mcp.devtools.list_console_messages", {}, cancelado=NUNCA)
    assert console.status == "ok"
    # navigate para um site FORA do objetivo: o guarda pede o sim (vira pendência/confirm).
    avaliacao = executor.avaliar(
        "mcp.devtools.navigate_page", {"url": "https://outro-site.example/x"}
    )
    from jarvis.executor.ferramentas import Avaliacao

    assert isinstance(avaliacao, Avaliacao)
    assert str(avaliacao.decisao.veredito) == "confirm"


def test_destino_dentro_do_objetivo_nao_pede(executor: ExecutorDeFerramentas) -> None:
    avaliacao = executor.avaliar(
        "mcp.devtools.navigate_page", {"url": "https://loja.example/produto"}
    )
    from jarvis.executor.ferramentas import Avaliacao

    assert isinstance(avaliacao, Avaliacao)
    assert str(avaliacao.decisao.veredito) == "allow"
