"""O caminho rápido (dono, 2026-10-21, ADR-0045): a tabela das regras é este teste.

A regra só acha a ferramenta e os argumentos; quem decide se roda continua sendo o PDP, o Jev e a
pergunta ao dono (o teste do cérebro, `tests/unit/s2/test_caminho_rapido.py`, prova isso).
"""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.politica.atalho import Atalho, ContextoDoAtalho, Regra, achar, frase, limpar

APPS = {"discord": "Discord", "steam": "Steam", "brave": "Brave Web Browser", "spotify": "Spotify"}


def _contexto(
    *,
    navegador: bool = True,
    fora: frozenset[str] = frozenset(),
    motivo: str = "",
) -> ContextoDoAtalho:
    return ContextoDoAtalho(
        disponivel=lambda tool_id: tool_id not in fora,
        app=lambda nome: APPS.get(nome),
        navegador_configurado=lambda nome: "brave" if nome in ("brave", "navegador") else None,
        navegador=navegador,
        motivo_do_metodo=motivo,
    )


@pytest.mark.parametrize(
    ("fala", "regra", "tool_id", "args"),
    [
        # abrir um app liberado (o resolvedor, sem dúvida)
        ("Jarvis, abre o Discord", Regra.ABRIR_APP, "apps.launch", {"nome": "Discord"}),
        ("abra o steam por favor", Regra.ABRIR_APP, "apps.launch", {"nome": "Steam"}),
        ("pode abrir o spotify pra mim", Regra.ABRIR_APP, "apps.launch", {"nome": "Spotify"}),
        # o navegador configurado vai pelo browser.launch (uma instância só, ADR-0036)
        ("abre o Brave", Regra.ABRIR_NAVEGADOR, "browser.launch", {"navegador": "brave"}),
        ("abre o navegador", Regra.ABRIR_NAVEGADOR, "browser.launch", {"navegador": "brave"}),
        # fechar a janela × encerrar o app (ADR-0042)
        ("fecha o Discord", Regra.FECHAR_JANELA, "window.close", {"app": "discord"}),
        ("fecha a janela", Regra.FECHAR_JANELA, "window.close", {}),
        ("fecha esse aí", Regra.FECHAR_JANELA, "window.close", {}),
        ("fecha o Discord todo", Regra.ENCERRAR_APP, "apps.quit", {"app": "discord"}),
        ("mata o steam", Regra.ENCERRAR_APP, "apps.quit", {"app": "steam"}),
        ("encerra o steam de vez", Regra.ENCERRAR_APP, "apps.quit", {"app": "steam"}),
        # focar
        ("vai pro discord", Regra.FOCAR_APP, "window.focus_app", {"app": "discord"}),
        ("traz o brave pra frente", Regra.FOCAR_APP, "window.focus_app", {"app": "brave"}),
        # o que está em foco, as janelas, as abas
        ("qual janela está em foco?", Regra.EM_FOCO, "window.focused", {}),
        ("o que está na tela?", Regra.EM_FOCO, "window.focused", {}),
        ("o que está no monitor principal", Regra.EM_FOCO, "window.focused", {}),
        ("quais janelas estão abertas?", Regra.JANELAS, "window.list", {}),
        ("o que tá aberto agora", Regra.JANELAS, "window.list", {}),
        ("quais abas estão abertas?", Regra.ABAS, "browser.tabs", {}),
        # site: o navegador do dono desde o primeiro passo, com a busca do próprio site
        ("abre o YouTube", Regra.ABRIR_SITE, "browser.navigate",
         {"url": "https://www.youtube.com/"}),
        ("entra no g1", Regra.ABRIR_SITE, "browser.navigate", {"url": "https://g1.globo.com/"}),
        ("abre exemplo.com.br", Regra.ABRIR_SITE, "browser.navigate",
         {"url": "https://exemplo.com.br/"}),
        ("pesquisa vídeos de gatos no YouTube", Regra.BUSCAR_NO_SITE, "browser.navigate",
         {"url": "https://www.youtube.com/results?search_query=v%C3%ADdeos+de+gatos"}),
        ("procura no mercado livre fone bluetooth", Regra.BUSCAR_NO_SITE, "browser.navigate",
         {"url": "https://lista.mercadolivre.com.br/fone%20bluetooth"}),
        ("abre o youtube e pesquisa o primo rico", Regra.BUSCAR_NO_SITE, "browser.navigate",
         {"url": "https://www.youtube.com/results?search_query=o+primo+rico"}),
        # o primeiro passo, e o modelo segue (abrir o canal, ler as notícias)
        ("abre o canal do Primo Rico no YouTube", Regra.PRIMEIRO_PASSO_NO_SITE,
         "browser.navigate", {"url": "https://www.youtube.com/results?search_query=Primo+Rico"}),
        ("abra um vídeo no YouTube", Regra.PRIMEIRO_PASSO_NO_SITE, "browser.navigate",
         {"url": "https://www.youtube.com/"}),
        ("quais as notícias do g1", Regra.PRIMEIRO_PASSO_NO_SITE, "browser.navigate",
         {"url": "https://g1.globo.com/", "segundo_plano": True}),
    ],
)  # fmt: skip
def test_a_tabela_das_regras(fala: str, regra: Regra, tool_id: str, args: dict[str, Any]) -> None:
    achado = achar(fala, _contexto())
    assert achado is not None, fala
    assert (achado.regra, achado.tool_id, dict(achado.args)) == (regra, tool_id, args)


def test_o_primeiro_passo_nao_fecha_o_pedido_e_o_resto_fecha() -> None:
    canal = achar("abre o canal do Primo Rico no YouTube", _contexto())
    assert canal is not None and not canal.completo
    abrir = achar("abre o YouTube", _contexto())
    assert abrir is not None and abrir.completo


@pytest.mark.parametrize(
    "fala",
    [
        "abre o Discord e manda um oi pra Ana",  # composto: o modelo decide
        "abre o diário",  # não resolve para app liberado
        "abre o arquivo de notas da reunião de ontem à tarde",  # longo demais
        "fecha a aba",  # aba é do navegador
        "fecha o jarvis",  # encerrar o Jarvis é outra coisa (ADR-0041)
        "fecha tudo",
        "procura o arquivo relatório",  # sem o roteador dizer busca genérica, não é web
        "qual a capital da França?",
        "abre o youtube no brave",  # site num navegador nomeado: o modelo decide
        "roda o discord no terminal",  # o alvo tem contexto: não é só o nome do app
        "fecha o steam com o jogo",
        "",
    ],
)
def test_o_que_nao_e_atalho(fala: str) -> None:
    assert achar(fala, _contexto()) is None


def test_a_busca_generica_so_quando_o_roteador_diz() -> None:
    sem = achar("pesquisa a previsão do tempo", _contexto())
    com = achar("pesquisa na internet a previsão do tempo", _contexto(motivo="busca_generica"))
    assert sem is None
    assert com == Atalho(
        Regra.BUSCAR_NA_WEB,
        "web.buscar",
        {"consulta": "a previsão do tempo"},
        completo=False,
        termo="a previsão do tempo",
    )


def test_ferramenta_fora_do_turno_nao_vira_atalho() -> None:
    """O método do pedido (ADR-0035) tirou a ferramenta: a regra não a usa."""
    assert achar("abre o Discord", _contexto(fora=frozenset({"apps.launch"}))) is None
    assert achar("abre o YouTube", _contexto(fora=frozenset({"browser.navigate"}))) is None


def test_sem_extensao_o_site_abre_pelo_sites_open_e_o_primeiro_passo_fica_com_o_modelo() -> None:
    sem = _contexto(navegador=False)
    abrir = achar("abre o YouTube", sem)
    assert abrir is not None and abrir.tool_id == "sites.open"
    assert achar("abre o canal do Primo Rico no YouTube", sem) is None
    assert achar("quais abas estão abertas?", sem) is None


def test_a_fala_limpa_tira_a_chamada_e_a_cortesia() -> None:
    assert limpar("Ei Jarvis, por favor, abre o Discord pra mim agora!") == "abre o discord"


@pytest.mark.parametrize(
    ("fala", "dados", "dita"),
    [
        ("abre o Discord", {"app": "Discord", "pid": 9}, "Abrindo o Discord."),
        (
            "abre o Brave",
            {"navegador": "brave", "ja_aberto": True, "visivel": True},
            "O Brave já estava aberto: trouxe para a frente.",
        ),
        (
            "abre o Brave",
            {"navegador": "brave", "ja_aberto": True, "visivel": False},
            "O Brave já estava aberto, mas o sistema não deixou trazê-lo para a frente.",
        ),
        ("fecha o Discord", {"app": "Discord", "fechada": True}, "Fechei a janela do Discord."),
        ("fecha a janela", {"app": "Kate", "fechada": True}, "Fechei a janela."),
        (
            "fecha o kate",
            {"app": "Kate", "fechada": False},
            "Pedi para fechar o Kate, mas a janela continua aberta: ele pode estar perguntando se "
            "salva.",
        ),
        ("mata o discord", {"app": "Discord", "conferido": True}, ""),
        ("vai pro discord", {"app": "discord"}, "Pronto, o Discord está na frente."),
        ("abre o YouTube", {"visivel": True}, "Abri o YouTube."),
        ("abre exemplo.com.br", {"visivel": True}, "Abri o exemplo.com.br."),
        (
            "pesquisa gatos no YouTube",
            {"visivel": True},
            "Abri a busca do YouTube por gatos.",
        ),
        (
            "quais abas estão abertas",
            {"abas": [{"titulo": "G1", "estado": "à vista"}, {"titulo": "X", "estado": "x"}]},
            "2 abas abertas. À vista: G1.",
        ),
        (
            "quais janelas estão abertas",
            {"janelas": [{"app": "brave-browser"}, {"app": "discord"}, {"app": "brave-browser"}]},
            "Abertas: Brave e Discord.",
        ),
    ],
)
def test_a_frase_e_do_codigo_e_curta(fala: str, dados: dict[str, Any], dita: str) -> None:
    achado = achar(fala, _contexto())
    assert achado is not None
    assert frase(achado, dados) == dita


def test_a_frase_do_foco_diz_a_ativa_e_a_da_frente_do_principal() -> None:
    """Dois monitores: o Jarvis ativo no outro, o Brave na frente do principal (o caso do dono)."""
    achado = achar("o que está em foco?", _contexto())
    assert achado is not None
    dados = {
        "foco": {
            "id": "j",
            "app": "jarvis",
            "titulo": "Jarvis",
            "monitor": "B",
            "principal": False,
        },
        "monitores": [
            {
                "monitor": "A",
                "principal": True,
                "na_frente": {"id": "b", "app": "brave-browser", "titulo": "YouTube - Brave"},
            },
            {"monitor": "B", "principal": False, "na_frente": {"id": "j", "app": "jarvis"}},
        ],
    }
    assert frase(achado, dados) == (
        "Em foco: Jarvis — Jarvis no outro monitor. Na frente do monitor principal está o Brave — "
        "YouTube - Brave."
    )
    assert frase(achado, {"foco": None}) == "Nenhuma janela está ativa agora."
