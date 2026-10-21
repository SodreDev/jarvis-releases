"""O roteador de método (dono, 2026-10-20, ADR-0035): a tabela de casos é este teste."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.executor.desfazer import Contaminacao
from jarvis.executor.ferramentas import Avaliacao, ExecutorDeFerramentas
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.metodo import ENTRADA, ContextoDoMetodo, Metodo, escolher_metodo, quer_ver
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.trilha import CAUSAS, TrilhaDeDiagnostico, eventos_do_ultimo_turno

TUDO: ContextoDoMetodo = ContextoDoMetodo(
    navegador=True, entrada=True, apps=frozenset({"spotify", "steam", "brave"})
)
SEM_EXTENSAO: ContextoDoMetodo = ContextoDoMetodo(
    navegador=False, entrada=True, apps=frozenset({"spotify"})
)
SEM_ENTRADA: ContextoDoMetodo = ContextoDoMetodo(navegador=True, entrada=False)


@pytest.mark.parametrize(
    ("fala", "contexto", "metodo", "motivo"),
    [
        # site → a extensão, direto (sem abrir o navegador como app, sem atalho, sem terminal)
        ("abre o youtube e procura o primo rico", TUDO, Metodo.NAVEGADOR, "cita_site"),
        ("entra no exemplo.com.br", TUDO, Metodo.NAVEGADOR, "cita_site"),
        ("pesquisa na web sobre o eclipse", TUDO, Metodo.NAVEGADOR, "cita_site"),
        ("abre o youtube", SEM_EXTENSAO, Metodo.WEB, "cita_site_sem_extensao"),
        # o caso do dono (2026-10-21): vídeo no site é do site, mesmo com "toca" ou "música"
        ("abra um vídeo no YouTube", TUDO, Metodo.NAVEGADOR, "cita_site"),
        ("toca um vídeo do primo rico no youtube", TUDO, Metodo.NAVEGADOR, "cita_site"),
        ("põe uma música no youtube", TUDO, Metodo.NAVEGADOR, "cita_site"),
        # site que proíbe automação → mouse e teclado virtuais (ADR-0027)
        ("manda um oi pra Ana no whatsapp", TUDO, Metodo.ENTRADA_VIRTUAL, "site_sem_automacao"),
        ("manda um oi pra Ana no whatsapp", SEM_ENTRADA, Metodo.NAVEGADOR, "cita_site"),
        # app local → o resolvedor e o foco
        ("abre o spotify", TUDO, Metodo.APP, "cita_app"),
        ("abre o navegador", TUDO, Metodo.APP, "abre_o_navegador"),
        ("abre o Firefox", SEM_ENTRADA, Metodo.APP, "abre_o_navegador"),
        # terminal e sistema de arquivos → subagente
        ("roda esse script no terminal", TUDO, Metodo.SUBAGENTE, "pede_terminal"),
        ("vê o que tem nos arquivos do sistema", TUDO, Metodo.SUBAGENTE, "pede_terminal"),
        # o que tem ferramenta própria
        ("aumenta o volume", TUDO, Metodo.SISTEMA, "pede_sistema"),
        ("toca uma música", TUDO, Metodo.SISTEMA, "pede_sistema"),
        ("aumenta o volume do youtube", TUDO, Metodo.CONVERSA, "pedido_misto"),
        ("me lembra de ligar pro João às três", TUDO, Metodo.SISTEMA, "pede_sistema"),
        ("anota que a reunião é terça", TUDO, Metodo.MEMORIA, "pede_memoria"),
        # o dono pediu o teclado ou o mouse pelo nome: tem
        ("aperta ctrl+L", TUDO, Metodo.ENTRADA_VIRTUAL, "pede_teclado_ou_mouse"),
        # misto ou sem método: o modelo escolhe, nada fica de fora
        ("abre o spotify e pesquisa o primo rico no google", TUDO, Metodo.CONVERSA, "pedido_misto"),
        ("abre o youtube no brave", TUDO, Metodo.CONVERSA, "pedido_misto"),
        ("qual a capital da França?", TUDO, Metodo.CONVERSA, "sem_metodo_especifico"),
    ],
)
def test_a_tabela_de_casos(
    fala: str, contexto: ContextoDoMetodo, metodo: Metodo, motivo: str
) -> None:
    escolha = escolher_metodo(fala, contexto)
    assert (escolha.metodo, escolha.motivo) == (metodo, motivo)
    assert motivo in CAUSAS  # o código vai à trilha, que só grava o que está na allowlist


@pytest.mark.parametrize(
    ("fala", "ver"),
    [
        ("abra um vídeo no YouTube", True),
        ("abre o canal do Primo Rico no youtube", True),
        ("coloca um vídeo de gatos pra eu ver", True),
        ("toca um vídeo do primo rico no youtube", True),
        ("quero assistir o último vídeo do canal", True),
        ("põe o g1 na tela", True),
        ("pesquisa no youtube quantos inscritos tem o primo rico", False),
        ("lê pra mim a notícia do g1", False),
        ("procura o preço do iphone na amazon", False),
        ("o que tem de novo no youtube?", False),
        ("sabre de luz no mercado livre", False),  # "abre" dentro de outra palavra não conta
    ],
)
def test_quer_ver_e_do_pedido_do_dono(fala: str, ver: bool) -> None:
    """Abrir e mostrar terminam à vista do dono; pesquisar e ler, não (auditoria, 2026-10-21)."""
    assert quer_ver(fala) is ver


def test_o_que_cada_metodo_deixa_de_fora() -> None:
    site = escolher_metodo("abre o youtube", TUDO)
    assert {"apps.launch", "browser.launch"} | ENTRADA <= site.evitar
    assert "browser.navigate" not in site.evitar and "sites.open" not in site.evitar
    assert escolher_metodo("roda o script no terminal", TUDO).evitar >= ENTRADA
    assert escolher_metodo("aperta ctrl+L", TUDO).evitar == frozenset()
    assert escolher_metodo("abre o spotify e o google", TUDO).evitar == frozenset()
    # Uma instância só (dono, 2026-10-21): «abre o navegador» vai pelo browser.launch, que traz o
    # navegador já aberto; o apps.launch abriria outra janela dele.
    navegador = escolher_metodo("abre o Brave", TUDO)
    assert "apps.launch" in navegador.evitar and "browser.launch" not in navegador.evitar
    assert "traz para a frente o que já está aberto" in navegador.nota()
    assert "Método deste pedido: navegador (cita_site)" in site.nota()
    assert escolher_metodo("qual a capital da França?", TUDO).nota() == ""


# --- no executor e no cérebro --------------------------------------------------------------------
@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    registro = RegistroDeApps(
        autorizados={
            "spotify": App(
                id="spotify",
                nome="Spotify",
                nomes=("spotify",),
                argv=("spotify",),
                arquivo=Path("/usr/share/applications/spotify.desktop"),
            )
        },
        instalados=frozenset({"spotify"}),
    )
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            apps_autorizados=frozenset({"spotify"}),
        )
        executor = ExecutorDeFerramentas(
            pdp=pdp, lar=lar, registro_de_apps=registro, trilha=TrilhaDeDiagnostico(tmp_path / "t")
        )
        executor.preparar()
        yield executor


def test_o_executor_recusa_no_turno_o_que_o_metodo_deixa_de_fora_mas_nao_na_tarefa(
    executor: ExecutorDeFerramentas, tmp_path: Path
) -> None:
    assert executor.trilha is not None
    executor.trilha.novo_turno("t-1", motor="teste")  # como o app faz a cada turno
    executor.novo_turno("roda esse script no terminal")

    recusado = executor.executar("apps.launch", {"nome": "spotify"}, cancelado=lambda: False)
    da_tarefa = executor.avaliar(
        "apps.launch",
        {"nome": "spotify"},
        session_id="",
        call_id="t-1-1",
        contaminacao=Contaminacao(),  # a chamada de uma tarefa em segundo plano
    )

    assert recusado.status == "negado"
    assert "método subagente (pede_terminal)" in recusado.motivo
    assert "tarefa.iniciar" in recusado.motivo
    assert isinstance(da_tarefa, Avaliacao), "a tarefa segue o PDP, não o método do turno"
    (metodo,) = [e for e in eventos_do_ultimo_turno(tmp_path / "t") if e["evento"] == "metodo"]
    assert (metodo["metodo"], metodo["motivo"]) == ("subagente", "pede_terminal")
    assert "roda esse script" not in str(metodo)  # só metadados: a fala não vai para a trilha


def test_o_cerebro_diz_o_metodo_ao_modelo_no_prompt_do_turno(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = MotorRoteirizado(resposta="Ok.")
    Cerebro(motor=motor, ferramentas=executor).responder(
        "roda esse script no terminal", epoch=0, publicar=lambda _: None
    )
    assert "Método deste pedido: subagente (pede_terminal)" in motor.pedidos[0].sistema
