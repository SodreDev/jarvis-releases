"""O Jarvis repetia a resposta (dono, 2026-11-15: «numa mensagem ele formula 5 ou 6 respostas e
fica repetindo»). A causa achada na trilha dele: turno sem ferramenta, duas ou três chamadas ao
motor e o dobro do texto falado. A oferta do fim da resposta («quer que eu fale mais?») casa com a
pergunta de permissão do relato verdadeiro (ADR-0066), é cortada, e o turno cobrava o motor — que
escrevia OUTRA resposta inteira ao mesmo pedido, até duas vezes, mais a frase do código.

Aqui, com o motor roteirizado e o WhatsApp falso (nenhum navegador, conta ou microfone de
verdade): respondeu, o turno está respondido — nada de nova resposta ao mesmo estímulo.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from jarvis.politica.permissao import ModoDePermissao
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.verdade import NOTA_DE_SEGUIR
from tests.unit.s2.test_relato_verdadeiro import _dizer, _executor, _whatsapp

PERGUNTA = "qual é a capital da Austrália?"
PRIMEIRA = (
    "A capital da Austrália é Camberra, e não Sydney como muita gente pensa. "
    "Quer que eu fale mais sobre a cidade?"
)
SEGUNDA = "Camberra é a capital australiana, escolhida como meio-termo entre Sydney e Melbourne."


def _motor(chamadas: list[Contexto]) -> MotorRoteirizado:
    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        chamadas.append(contexto)
        return [PRIMEIRA] if len(chamadas) == 1 else [SEGUNDA]

    return MotorRoteirizado(resposta=resposta)


def test_a_oferta_no_fim_da_resposta_nao_faz_o_jarvis_responder_de_novo(tmp_path: Path) -> None:
    chamadas: list[Contexto] = []
    for executor in _executor(tmp_path, _whatsapp(), ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=_motor(chamadas), ferramentas=executor)
        resposta, falado = _dizer(cerebro, PERGUNTA)
    assert len(chamadas) == 1, "uma resposta por estímulo: o motor não é cobrado de novo"
    assert not any(NOTA_DE_SEGUIR in c.sistema for c in chamadas)
    assert falado.count("Camberra") == 1 and "meio-termo" not in falado
    assert resposta.respondida and resposta.cobrancas == 0
    # A oferta continua fora da voz (ADR-0066), e nenhuma frase do código entra no lugar dela.
    assert "Quer que eu fale mais" not in falado
    assert "Não consegui" not in falado and "ainda não foi enviada" not in falado


def test_sem_resposta_nenhuma_o_objetivo_ainda_e_cobrado(tmp_path: Path) -> None:
    """O bug da ADR-0066 continua consertado: tudo cortado (nada respondido) = o motor segue."""
    chamadas: list[Contexto] = []

    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        chamadas.append(contexto)
        if len(chamadas) == 1:
            return ["Abri o contato da sua mãe. Quer que eu mande?"]
        return ["Ainda estou sem acesso ao contato."]

    for executor in _executor(tmp_path, _whatsapp(), ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=MotorRoteirizado(resposta=resposta), ferramentas=executor)
        resultado, falado = _dizer(cerebro, "abre o contato da minha mãe e diz eu te amo")
    assert len(chamadas) == 2 and NOTA_DE_SEGUIR in chamadas[1].sistema
    assert resultado.cobrancas == 1 and "Abri o contato" not in falado
