"""A caixa de scripts isolada (ADR-0050) e a ligação com o guarda (ADR-0049) no executor.

Os testes que sobem a caixa de verdade pedem bubblewrap ou podman; sem nenhum, são pulados (a
ferramenta degrada honesto e o teste de contrato cobre o `sem_suporte`)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import RespostaEscolha
from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.scripts import CaixaDeScript, Limites, backend_disponivel
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.guarda import GuardaDeContexto
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731
TEM_CAIXA = backend_disponivel() is not None
precisa_de_caixa = pytest.mark.skipif(not TEM_CAIXA, reason="sem bubblewrap nem podman")


def _jev(escolha: str = "permitir", p: float = 0.9) -> ClassificadorFalso:
    def roteiro(_estado: Any, _perguntas: Any) -> dict[str, Any]:
        return {
            "acao": RespostaEscolha(escolha, p, {escolha: p}),
            "categoria": RespostaEscolha("nenhuma", 0.9, {"nenhuma": 0.9}),
        }

    return ClassificadorFalso(roteiro=roteiro)


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(
            pdp=pdp, lar=lar, caixa=CaixaDeScript(), guarda=GuardaDeContexto(classificador=_jev())
        )
        executor.preparar()
        executor.novo_turno("some esses números")
        yield executor


def _rodar(executor: ExecutorDeFerramentas, **args: Any) -> Any:
    return executor.executar("script.rodar", args, cancelado=NUNCA)


# A caixa, direto.


@precisa_de_caixa
def test_a_caixa_roda_python_e_devolve_a_saida() -> None:
    r = CaixaDeScript().rodar(
        "python", "print(sum(int(x) for x in input().split()))", entrada="3 4 5"
    )
    assert r.saida.strip() == "12" and r.codigo_de_saida == 0 and not r.estouro_de_tempo


@precisa_de_caixa
def test_a_caixa_roda_js() -> None:
    r = CaixaDeScript().rodar("js", "console.log(2 ** 10)")
    assert r.saida.strip() == "1024" and r.codigo_de_saida == 0


@precisa_de_caixa
def test_a_caixa_nao_tem_rede() -> None:
    r = CaixaDeScript().rodar(
        "python", "import socket; socket.create_connection(('1.1.1.1', 80), 2)"
    )
    assert r.codigo_de_saida != 0 and "unreachable" in r.erro.lower()


@precisa_de_caixa
def test_a_caixa_nao_ve_a_casa_do_dono() -> None:
    codigo = (
        "import os\n"
        "try:\n"
        "    print('home:', os.listdir('/home'))\n"
        "except FileNotFoundError:\n"
        "    print('sem /home')"
    )
    r = CaixaDeScript().rodar("python", codigo)
    assert "sem /home" in r.saida or r.saida.strip() == "home: []"


@precisa_de_caixa
def test_o_prazo_mata_o_laco_infinito() -> None:
    r = CaixaDeScript().rodar("python", "while True: pass", limites=Limites(prazo_s=0.6))
    assert r.estouro_de_tempo and r.ms < 3000


@precisa_de_caixa
def test_a_saida_grande_e_cortada() -> None:
    r = CaixaDeScript().rodar("python", "print('x' * 200000)")
    assert r.saida_cortada and len(r.saida.encode("utf-8")) <= 64 * 1024


def test_sem_backend_degrada_honesto() -> None:
    caixa = CaixaDeScript(backend=None)
    assert not caixa.disponivel()
    r = caixa.rodar("python", "print(1)")
    assert r.sem_suporte and r.codigo_de_saida != 0


def test_o_limite_so_aperta_nunca_afrouxa() -> None:
    base = Limites(prazo_s=10.0, memoria_bytes=256 * 2**20)
    apertado = base.apertados(prazo_s=2.0, memoria_bytes=999 * 2**20)
    assert apertado.prazo_s == 2.0 and apertado.memoria_bytes == 256 * 2**20


# A ligação no executor: ligada, corpo, e o guarda antes do PDP.


def test_script_rodar_some_sem_caixa(tmp_path: Path) -> None:
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
        executor = ExecutorDeFerramentas(pdp=pdp, lar=lar)  # sem caixa
        executor.preparar()
        assert not executor._ligada("script.rodar")
        r = executor.executar(
            "script.rodar", {"linguagem": "python", "codigo": "print(1)"}, cancelado=NUNCA
        )
    assert r.status == "negado" and r.causa == "ferramenta_desligada"


@precisa_de_caixa
def test_o_executor_roda_o_script_pela_caixa(executor: ExecutorDeFerramentas) -> None:
    r = _rodar(executor, linguagem="python", codigo="print(6 * 7)")
    assert r.status == "ok" and r.dados["saida"].strip() == "42"


def test_o_guarda_barra_o_script_que_abre_credenciais(executor: ExecutorDeFerramentas) -> None:
    # Barra antes do PDP e antes de subir a caixa: não precisa de bwrap.
    r = _rodar(executor, linguagem="python", codigo="print(open('/home/dono/.ssh/id_rsa').read())")
    assert r.status == "negado" and r.causa == "guarda_barrou"
    assert "Barrei:" in r.motivo


def test_o_guarda_barra_baixar_e_executar(executor: ExecutorDeFerramentas) -> None:
    r = _rodar(executor, linguagem="python", codigo="import subprocess; subprocess.run(['ls'])")
    assert r.status == "negado" and r.causa == "guarda_barrou"


def test_a_caixa_com_rede_pede_o_sim(executor: ExecutorDeFerramentas) -> None:
    # rede=True é zona de confirmação: o turno acaba numa pendência (o PDP vira confirm).
    executor.guarda = GuardaDeContexto(classificador=_jev())
    avaliacao = executor.avaliar(
        "script.rodar", {"linguagem": "python", "codigo": "print(1)", "rede": True}
    )
    from jarvis.executor.ferramentas import Avaliacao

    assert isinstance(avaliacao, Avaliacao)
    assert str(avaliacao.decisao.veredito) == "confirm"


def test_o_evento_guarda_entra_na_trilha_sem_o_codigo(
    executor: ExecutorDeFerramentas, tmp_path: Path
) -> None:
    from jarvis.trilha import TrilhaDeDiagnostico

    executor.trilha = TrilhaDeDiagnostico(tmp_path / "trilha", relogio=lambda: 10.0)
    _rodar(executor, linguagem="python", codigo="import subprocess; subprocess.run(['id'])")
    gravado = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "trilha").rglob("*.jsonl"))
    assert '"evento": "guarda"' in gravado and '"decisao": "barrar"' in gravado
    assert "subprocess" not in gravado
