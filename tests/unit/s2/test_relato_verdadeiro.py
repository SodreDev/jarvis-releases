"""O bug do dono (2026-11-14): «abre o contato da minha mãe e diz eu te amo» (ADR-0066).

O Jarvis pediu permissão para rodar JavaScript, não executou e mesmo assim disse que abriu o
contato — e parou perguntando «quer que eu mande?». Aqui o mesmo pedido, com o WhatsApp falso
(`PaginaFalsa`), o motor roteirizado e o guarda sem classificador (a zona cinza que pedia o sim):
nenhum navegador, conta, microfone ou chave de verdade.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas, ResultadoDeFerramenta
from jarvis.navegador.cliente import ClienteDoNavegador
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.guarda import GuardaDeContexto
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.politica.permissao import ModoDePermissao
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.verdade import (
    FALTA_ENVIAR,
    Afirmacao,
    afirmacoes,
    conferir,
    envio_conferido,
)
from tests.unit.navegador.test_ferramentas_browser import PaginaFalsa

WHATSAPP = "https://web.whatsapp.com/"
PEDIDO = "abre o contato da minha mãe e diz eu te amo"
CLICAR_NA_MAE = "document.querySelector('[title=\"Mãe\"]').click()"


def _whatsapp() -> PaginaFalsa:
    pagina = PaginaFalsa()
    pagina.abas[0].update(url=WHATSAPP, titulo="WhatsApp")
    pagina.elemento("Mensagem", tag="div", campo=True, editavel=True, noFormulario=True)
    pagina.texto = "Mãe · online · eu te amo ✓✓"
    return pagina


@pytest.fixture
def pagina() -> PaginaFalsa:
    return _whatsapp()


def _executor(
    tmp_path: Path, pagina: PaginaFalsa, permissao: ModoDePermissao
) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    with LogDeAuditoria(tmp_path / f"auditoria-{permissao}.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            permissao=permissao,
        )
        ex = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            abrir_site=lambda _url: None,
            navegador=CorposDoNavegador(ClienteDoNavegador(pagina)),
            # Sem classificador, a zona cinza do guarda pede o sim: foi o «posso rodar JavaScript?».
            guarda=GuardaDeContexto(),
        )
        ex.preparar()
        yield ex
        assert ex.navegador is not None
        ex.navegador.controle.fechar()


def _roteiro(*rodadas: Sequence[str | PedidoDeTool]) -> MotorRoteirizado:
    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        return rodadas[min(feitas, len(rodadas) - 1)]

    return MotorRoteirizado(resposta=resposta)


def _dizer(cerebro: Cerebro, texto: str) -> tuple[Any, str]:
    publicados: list[dict[str, Any]] = []
    resposta = cerebro.responder(texto, epoch=0, publicar=publicados.append)
    falado = " ".join(str(p["text"]) for p in publicados)
    cerebro.ouvido(resposta.response_id, falado, interrompida=False)
    return resposta, falado


ENVIO_COMPLETO: tuple[list[str | PedidoDeTool], ...] = (
    ["Abri o contato da sua mãe. ", PedidoDeTool("browser.avaliar", {"codigo": CLICAR_NA_MAE})],
    # Ler a página antes de digitar (ADR-0069 §2).
    [PedidoDeTool("browser.inspecionar", {})],
    [PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "eu te amo"})],
    [PedidoDeTool("browser.acionar", {"alvo": "Mensagem", "acao": "tecla", "tecla": "Enter"})],
    [PedidoDeTool("browser.read", {})],
    ["Mandei «eu te amo» para a sua mãe."],
)


def test_reproduz_o_bug_na_matriz_antiga(tmp_path: Path, pagina: PaginaFalsa) -> None:
    """Com a matriz de antes, o script pede o sim e nada roda — e a narração «Abri o contato»
    escapava para a voz. Agora a narração é cortada mesmo aqui (nada confirmou)."""
    for executor in _executor(tmp_path, pagina, ModoDePermissao.MATRIZ):
        cerebro = Cerebro(motor=_roteiro(*ENVIO_COMPLETO), ferramentas=executor)
        resposta, falado = _dizer(cerebro, PEDIDO)
        assert [r.status for r in resposta.ferramentas][:1] == ["negado"]
        assert "page.eval" not in pagina.metodos()
        assert "Abri o contato" not in falado
        assert "Abri o contato da sua mãe." in resposta.sem_confirmacao


def test_no_automatico_executa_ate_o_fim_e_so_afirma_o_confirmado(
    tmp_path: Path, pagina: PaginaFalsa
) -> None:
    for executor in _executor(tmp_path, pagina, ModoDePermissao.AUTOMATICO):
        motor = _roteiro(*ENVIO_COMPLETO)
        cerebro = Cerebro(motor=motor, ferramentas=executor)
        resposta, falado = _dizer(cerebro, PEDIDO)
        assert [r.tool_id for r in resposta.ferramentas] == [
            "browser.avaliar",
            "browser.inspecionar",
            "browser.type",
            "browser.acionar",
            "browser.read",
        ]
        assert all(r.status == "ok" for r in resposta.ferramentas), resposta.ferramentas
        metodos = pagina.metodos()
        assert "page.eval" in metodos and "page.type" in metodos and "page.act" in metodos
        assert cerebro.pendencias.valida() is None, "nenhuma pergunta de permissão"
        # A narração antes do primeiro passo não tinha confirmação; o fim, sim (envio + leitura).
        assert "Abri o contato" not in falado
        assert "Mandei «eu te amo» para a sua mãe." in falado


def test_a_pergunta_do_jarvis_nao_e_cortada_nem_cobrada(
    tmp_path: Path, pagina: PaginaFalsa
) -> None:
    """ADR-0070: perguntar é decisão do Jarvis, não afirmação a conferir — a pergunta vai ao dono;
    o «abri» que nada confirmou continua cortado."""
    rodadas = (
        [PedidoDeTool("browser.avaliar", {"codigo": CLICAR_NA_MAE})],
        ["Abri o contato da sua mãe. Quer que eu mande a mensagem?"],
    )
    for executor in _executor(tmp_path, pagina, ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=_roteiro(*rodadas), ferramentas=executor)
        resultado, falado = _dizer(cerebro, PEDIDO)
        assert resultado.cobrancas == 0
        assert "Quer que eu mande a mensagem?" in falado


def test_sem_confirmar_o_envio_o_jarvis_diz_o_que_falta(
    tmp_path: Path, pagina: PaginaFalsa
) -> None:
    """O motor afirma «mandei» sem nenhum envio: cortado, cobrado duas vezes, e o código diz
    que a mensagem não foi enviada — nunca o relato falso."""
    rodadas = (
        [PedidoDeTool("browser.avaliar", {"codigo": CLICAR_NA_MAE})],
        ["Mandei «eu te amo» para a sua mãe."],
    )
    for executor in _executor(tmp_path, pagina, ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=_roteiro(*rodadas), ferramentas=executor)
        resposta, falado = _dizer(cerebro, PEDIDO)
        assert "Mandei" not in falado
        assert FALTA_ENVIAR in falado
        assert resposta.cobrancas == 2


# --- o crivo, frase a frase -------------------------------------------------------------------
def _ok(tool_id: str, **dados: Any) -> ResultadoDeFerramenta:
    return ResultadoDeFerramenta(tool_id, "ok", dados=dados)


@pytest.mark.parametrize(
    ("frase", "esperado"),
    [
        ("Abri o contato da sua mãe.", {Afirmacao.ABRIU}),
        ("Mandei a mensagem.", {Afirmacao.ENVIOU}),
        ("A mensagem foi enviada.", {Afirmacao.ENVIOU}),
        ("Quer que eu mande a mensagem?", {Afirmacao.PEDE_PERMISSAO}),
        ("Posso rodar o script na página?", {Afirmacao.PEDE_PERMISSAO}),
        ("Vou abrir o WhatsApp.", set()),
        ("O Spotify não está aberto.", set()),
        ("Ainda não enviei a mensagem.", set()),
        ("Qual das duas Anas você quer?", set()),
        ("O tempo amanhã é de sol.", set()),
    ],
)
def test_afirmacoes(frase: str, esperado: set[Afirmacao]) -> None:
    assert afirmacoes(frase) == esperado


def test_envio_so_conta_conferido() -> None:
    enviado = _ok("browser.acionar", enviado=True)
    assert not envio_conferido([enviado])
    assert envio_conferido([enviado, _ok("browser.read")])
    assert envio_conferido([_ok("social.enviar", enviado=True, conferido=True)])
    assert not envio_conferido([ResultadoDeFerramenta("social.enviar", "erro")])


def test_conferir_corta_so_o_que_nao_se_confirma() -> None:
    relato = conferir("Abri o WhatsApp. Mandei a mensagem. Até mais.", [_ok("sites.open")])
    assert relato.texto == "Abri o WhatsApp. Até mais."
    assert relato.cortadas == ("Mandei a mensagem.",)


def test_a_mensagem_que_o_jarvis_digita_nao_e_vetada_pelo_codigo(
    tmp_path: Path, pagina: PaginaFalsa
) -> None:
    """ADR-0070 (c5): redigir no tom do dono é orientação (persona e tarefa), não veto por regex —
    o código não recusa o `browser.type` que repete a fala do dono; quem decide é o Jarvis."""
    vistos: list[str] = []

    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        vistos.append(contexto.sistema)
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        if feitas == 0:
            return [PedidoDeTool("browser.avaliar", {"codigo": CLICAR_NA_MAE})]
        if feitas == 1:
            return [PedidoDeTool("browser.inspecionar", {})]
        if feitas == 2:
            return [PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "eu te amo"})]
        return ["Pronto."]

    for executor in _executor(tmp_path, pagina, ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=MotorRoteirizado(resposta=resposta), ferramentas=executor)
        resultado, _falado = _dizer(cerebro, PEDIDO)
    digitados = [r for r in resultado.ferramentas if r.tool_id == "browser.type"]
    assert len(digitados) == 1 and not resultado.cobrou_redacao
    assert not any("REDIJA A MENSAGEM" in s for s in vistos), "sem veto nem cobrança do código"
    digitado = [params for metodo, params in pagina.chamadas if metodo == "page.type"]
    assert len(digitado) == 1 and "eu te amo" in str(digitado[0])
