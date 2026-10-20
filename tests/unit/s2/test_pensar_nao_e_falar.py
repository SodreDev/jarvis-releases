"""Pensar não é falar (dono, 2026-10-20, ADR-0031): o raciocínio é do turno, a fala é o resultado.

O dono não acompanha passo a passo. O que se prova aqui, sem rede e sem LLM: o bloco `<<pensar>>`
nunca vira fala nem tela, mesmo partido entre deltas ou sem a marca de fim; o raciocínio volta ao
motor na rodada seguinte, com teto; fala no máximo um aviso curto antes da primeira ferramenta, e
a narração dos passos seguintes e o palpite depois de uma proposta ficam no raciocínio; e segurar
o texto dessas rodadas não atrasa o primeiro lote da resposta.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import LIMITE_DO_RACIOCINIO, Cerebro
from jarvis.s2.motor import (
    Contexto,
    Delta,
    Fim,
    MotivoDoFim,
    PedidoDeTool,
    Raciocinio,
    Texto,
)
from jarvis.s2.motor import (
    Modo as ModoDoMotor,
)
from jarvis.s2.motor_claude_cli import LeitorDoProtocolo
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.voz.interface import Cancelado, Onde

LER_A_NOTA = PedidoDeTool("files.read_text", {"path": "~/Documentos/notas.txt"})
LISTAR = PedidoDeTool("files.list_dir", {"path": "~/Documentos"})


def _ler(*pedacos: str) -> list[Delta]:
    leitor = LeitorDoProtocolo()
    saida: list[Delta] = []
    for pedaco in pedacos:
        saida += leitor.alimentar(pedaco)
    return saida + list(leitor.fechar())


def _fala(deltas: Sequence[Delta]) -> str:
    return "".join(d.texto for d in deltas if isinstance(d, Texto))


def _raciocinio(deltas: Sequence[Delta]) -> str:
    return "".join(d.texto for d in deltas if isinstance(d, Raciocinio))


# --- o protocolo ---------------------------------------------------------------------------
def test_o_bloco_pensar_nao_vira_fala_mesmo_partido_entre_deltas() -> None:
    deltas = _ler(
        "Vou ver. <<pen",
        "sar>>preciso achar o ",
        "canal<</pen",
        'sar>>\n<<ferramenta>> {"tool_id": "web.buscar", "args": {"consulta": "canal"}}',
    )
    assert _fala(deltas) == "Vou ver. "
    assert _raciocinio(deltas) == "preciso achar o canal"
    assert [d for d in deltas if isinstance(d, PedidoDeTool)] == [
        PedidoDeTool("web.buscar", {"consulta": "canal"})
    ]


@pytest.mark.parametrize(
    "texto",
    [
        "<< PENSAR >>plano<< /pensar >>Pronto.",  # caixa e espaços, como o modelo escreve
        "<<pensar>>plano<</pensar>>Pronto.",
    ],
)
def test_as_marcas_do_raciocinio_toleram_caixa_e_espaco(texto: str) -> None:
    deltas = _ler(texto)
    assert (_fala(deltas), _raciocinio(deltas)) == ("Pronto.", "plano")


def test_raciocinio_sem_a_marca_de_fim_nao_vira_fala() -> None:
    deltas = _ler("Abri. <<pensar>> agora confiro o título", " e o canal")
    assert _fala(deltas) == "Abri. "
    assert _raciocinio(deltas) == " agora confiro o título e o canal"


def test_a_proposta_dentro_de_um_raciocinio_aberto_fecha_o_raciocinio() -> None:
    deltas = _ler('<<pensar>>vou buscar <<ferramenta>> {"tool_id": "web.buscar", "args": {}}')
    assert _raciocinio(deltas) == "vou buscar "
    assert [d for d in deltas if isinstance(d, PedidoDeTool)] == [PedidoDeTool("web.buscar", {})]
    assert _fala(deltas) == ""


def test_um_menor_que_solto_no_texto_nao_segura_a_fala() -> None:
    leitor = LeitorDoProtocolo()
    assert _fala(list(leitor.alimentar("dois < três e "))) == "dois < três e "


# --- o cérebro -----------------------------------------------------------------------------
@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    (lar / "Documentos" / "notas.txt").write_text("comprar café\n", "utf-8")
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(pdp=pdp, lar=lar)
        executor.preparar()
        yield executor


def _roteiro(*rodadas: Sequence[Parte]) -> MotorRoteirizado:
    """A rodada N do motor é escolhida pelo número de resultados de ferramenta no contexto."""

    def resposta(contexto: Contexto) -> Sequence[Parte]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        return rodadas[min(feitas, len(rodadas) - 1)]

    return MotorRoteirizado(resposta=resposta)


def _falado(publicados: Sequence[dict[str, Any]]) -> str:
    return " ".join(str(p["text"]) for p in publicados if p["text"])


def test_o_raciocinio_nao_vai_a_fala_nem_a_tela_e_volta_ao_motor_no_passo_seguinte(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = _roteiro(
        [Raciocinio("plano: ler a nota e dizer o que tem"), "Vou ver. ", LER_A_NOTA],
        [Raciocinio("a nota fala de café"), "Na sua nota tem comprar café."],
    )
    publicados: list[dict[str, Any]] = []
    telas: list[str] = []

    resposta = Cerebro(motor=motor, ferramentas=executor).responder(
        "o que tem na minha nota?", epoch=0, publicar=publicados.append, mostrar=telas.append
    )

    assert _falado(publicados) == "Vou ver. Na sua nota tem comprar café."
    assert telas[-1] == "Vou ver. Na sua nota tem comprar café."
    assert not any("plano" in tela or "fala de café" in tela for tela in telas)
    segundo = motor.pedidos[1]
    assert segundo.raciocinio == "plano: ler a nota e dizer o que tem"
    assert segundo.ja_dito == "Vou ver."
    texto = segundo.como_texto()
    assert "interno: o dono não ouviu nem viu" in texto and "plano: ler a nota" in texto
    assert "«Vou ver.» Não repita." in texto
    assert "siga com a próxima ferramenta sem falar" in texto
    assert resposta.raciocinio == "plano: ler a nota e dizer o que tem a nota fala de café"
    assert "plano" not in resposta.gerado


def test_so_um_aviso_curto_e_a_narracao_dos_passos_seguintes_fica_no_raciocinio(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = _roteiro(
        ["Vou ver. ", LISTAR],
        ["Achei a nota, agora vou ler. ", LER_A_NOTA],
        ["Na sua nota tem comprar café."],
    )
    publicados: list[dict[str, Any]] = []
    telas: list[str] = []
    status: list[str] = []

    resposta = Cerebro(motor=motor, ferramentas=executor, ao_status=status.append).responder(
        "o que tem na minha nota?", epoch=0, publicar=publicados.append, mostrar=telas.append
    )

    assert [r.status for r in resposta.ferramentas] == ["ok", "ok"]
    assert _falado(publicados) == "Vou ver. Na sua nota tem comprar café."
    assert not any("Achei a nota" in tela for tela in telas)
    assert status == [], "sem status entre passos"
    assert resposta.narracao_retida == 1
    assert "Achei a nota, agora vou ler." in resposta.raciocinio
    assert "Achei a nota, agora vou ler." in motor.pedidos[2].raciocinio


def test_o_que_o_modelo_diz_depois_de_propor_e_palpite_e_nao_e_falado(
    executor: ExecutorDeFerramentas,
) -> None:
    """Antes do resultado voltar ele não sabe se deu certo ("pronto, li!" seria mentira)."""
    motor = _roteiro(
        ["Vou ver. ", LER_A_NOTA, " Pronto, li a nota!"],
        ["Na sua nota tem comprar café."],
    )
    publicados: list[dict[str, Any]] = []

    resposta = Cerebro(motor=motor, ferramentas=executor).responder(
        "lê a minha nota", epoch=0, publicar=publicados.append
    )

    assert _falado(publicados) == "Vou ver. Na sua nota tem comprar café."
    assert "Pronto, li a nota!" in resposta.raciocinio and resposta.narracao_retida == 1


def test_o_raciocinio_tem_teto_e_o_que_passa_e_so_contado(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = _roteiro(
        [Raciocinio("x" * (LIMITE_DO_RACIOCINIO + 500)), LER_A_NOTA],
        [Raciocinio("mais"), "Pronto."],
    )

    resposta = Cerebro(motor=motor, ferramentas=executor).responder(
        "lê a minha nota", epoch=0, publicar=lambda _: None
    )

    assert len(resposta.raciocinio) == LIMITE_DO_RACIOCINIO
    assert resposta.raciocinio_descartado == 500 + len(" mais")
    assert len(motor.pedidos[1].raciocinio) == LIMITE_DO_RACIOCINIO


def test_o_aviso_de_um_efeito_que_fica_continua_sendo_falado(
    executor: ExecutorDeFerramentas,
) -> None:
    """A pasta nova é resultado (e se desfaz): esse aviso o dono ouve, como antes."""
    motor = _roteiro(
        [PedidoDeTool("files.create_dir", {"path": "~/Documentos/viagem"})], ["Pronto."]
    )
    publicados: list[dict[str, Any]] = []

    Cerebro(motor=motor, ferramentas=executor).responder(
        "cria a pasta viagem em Documentos", epoch=0, publicar=publicados.append
    )

    assert _falado(publicados) == "Criei a pasta viagem. Pronto."


RESPOSTA_LONGA = (
    "Na sua pasta Documentos tem a nota de compras, com café, pão e leite, e mais duas "
    "planilhas do orçamento da casa deste mês e do mês passado, todas atualizadas ontem à noite."
)


@dataclass
class MotorQueObserva:
    """Primeira rodada: aviso e proposta. Segunda: a resposta longa, palavra por palavra — e anota
    quantos lotes já tinham saído quando ele terminou de gerar."""

    publicados: list[dict[str, Any]]
    lotes_antes_do_fim: list[int] = field(default_factory=list)
    nome: str = "observa (teste)"
    onde: Onde = Onde.LOCAL

    def gerar(
        self, contexto: Contexto, modo: ModoDoMotor, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        del modo, cancelado
        if not any(m.papel == "ferramenta" for m in contexto.mensagens):
            yield Texto("Vou ver. ")
            yield LISTAR
        else:
            for palavra in RESPOSTA_LONGA.split():
                yield Texto(palavra + " ")
            self.lotes_antes_do_fim.append(sum(1 for p in self.publicados if p["text"]))
        yield Fim(MotivoDoFim.CONCLUIDO)


def test_segurar_a_narracao_nao_atrasa_o_primeiro_lote_da_resposta(
    executor: ExecutorDeFerramentas,
) -> None:
    publicados: list[dict[str, Any]] = []
    telas: list[str] = []
    motor = MotorQueObserva(publicados)

    Cerebro(motor=motor, ferramentas=executor).responder(
        "o que tem em Documentos?", epoch=0, publicar=publicados.append, mostrar=telas.append
    )

    # O aviso e ao menos um lote de 14+ palavras saíram enquanto o motor ainda gerava.
    assert motor.lotes_antes_do_fim[0] >= 2
    assert _falado(publicados) == "Vou ver. " + RESPOSTA_LONGA
    # Solto o primeiro lote, a tela volta a crescer a cada delta.
    depois_do_aviso = [t for t in telas if t != "Vou ver."]
    assert len(depois_do_aviso) > 5 and depois_do_aviso[-1] == "Vou ver. " + RESPOSTA_LONGA
