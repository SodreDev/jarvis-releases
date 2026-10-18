"""Casos de regressão da fala pt-BR aproximada, todos sem ASR, rede ou microfone."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.apps.medicao import CasoDePronuncia, medir
from jarvis.apps.resolvedor import RepositorioDeAliases, ResolvedorDeApps, dicas_de_apps
from jarvis.executor.lancador import (
    App,
    AppRecusado,
    RegistroDeApps,
    ler_desktop,
    listar_binarios_do_path,
)


def _app(
    identificador: str, nome: str, *, generico: str = "", keywords: tuple[str, ...] = ()
) -> App:
    return App(
        id=identificador,
        nome=nome,
        nomes=(nome, identificador),
        argv=(identificador,),
        arquivo=Path(),
        generico=generico,
        keywords=keywords,
        exec_nome=identificador,
    )


APPS = (
    _app("discord", "Discord"),
    _app("spotify", "Spotify"),
    _app("vscode", "Visual Studio Code"),
    _app("chrome", "Google Chrome"),
    _app("brave", "Brave Web Browser"),
    _app("obsidian", "Obsidian"),
    _app("teamspeak", "TeamSpeak"),
)


@pytest.mark.parametrize(
    ("fala", "esperado"),
    (
        ("discórdi", "discord"),
        ("espótifai", "spotify"),
        ("vi esse côdi", "vscode"),
        ("cróme", "chrome"),
        ("brêive", "brave"),
        ("obisídian", "obsidian"),
        ("tim speak", "teamspeak"),
        ("abre o spotify", "spotify"),
    ),
)
def test_resolve_pronuncias_aproximadas_sem_apelidos_manuais(fala: str, esperado: str) -> None:
    resultado = ResolvedorDeApps(APPS).resolver(fala)

    assert resultado.estado == "encontrado", resultado
    assert resultado.app is not None and resultado.app.id == esperado


def test_empate_nao_escolhe_por_palpite() -> None:
    resultado = ResolvedorDeApps(
        (_app("discord", "Discord"), _app("discord-canary", "Discord Canary"))
    ).resolver("discord")

    assert resultado.estado == "ambiguo"
    assert resultado.app is None
    assert "Discord" in resultado.pergunta and "Canary" in resultado.pergunta


def test_abaixo_do_limiar_nao_encontra() -> None:
    resultado = ResolvedorDeApps(APPS).resolver("planilha galactica")

    assert resultado.estado == "nao_encontrado"
    assert resultado.app is None


def test_correcao_do_dono_persiste_e_vira_alias(tmp_path: Path) -> None:
    repositorio = RepositorioDeAliases(tmp_path / "estado" / "aliases.json")
    registro = RegistroDeApps(
        autorizados={"discord": APPS[0]},
        instalados=frozenset({"discord"}),
        catalogo={"discord": APPS[0]},
        repositorio_de_aliases=repositorio,
    )

    with pytest.raises(AppRecusado):
        registro.resolver("bate papo roxo")
    renovado = registro.com_correcao("bate papo roxo", "discord")

    assert repositorio.carregar() == {"discord": ("bate papo roxo",)}
    assert renovado.resolver("bate papo roxo").id == "discord"


def test_correcao_nunca_pode_autorizar_app_fora_da_lista(tmp_path: Path) -> None:
    registro = RegistroDeApps(
        autorizados={"discord": APPS[0]},
        instalados=frozenset({"discord", "spotify"}),
        repositorio_de_aliases=RepositorioDeAliases(tmp_path / "aliases.json"),
    )

    with pytest.raises(AppRecusado, match="não autorizado"):
        registro.com_correcao("musica", "spotify")


def test_registro_normal_usa_estado_do_usuario_para_aprender(tmp_path: Path) -> None:
    pasta = tmp_path / "apps"
    pasta.mkdir()
    arquivo = pasta / "discord.desktop"
    arquivo.write_text(
        "[Desktop Entry]\nType=Application\nName=Discord\nExec=discord\n", encoding="utf-8"
    )
    registro = RegistroDeApps.montar(
        ["discord"], pastas=[str(pasta)], ambiente={"XDG_STATE_HOME": str(tmp_path / "estado")}
    )

    renovado = registro.com_correcao("bate-papo roxo", "discord")

    assert renovado.resolver("bate-papo roxo").id == "discord"
    assert (tmp_path / "estado" / "jarvis" / "apps" / "aliases.json").is_file()


def test_desktop_entry_entrega_generic_keywords_e_exec_ao_catalogo(tmp_path: Path) -> None:
    arquivo = tmp_path / "codigo.desktop"
    arquivo.write_text(
        "[Desktop Entry]\nType=Application\nName=Visual Studio Code\n"
        "GenericName=Editor de Código\nKeywords=programação;IDE;\nExec=code --reuse-window %U\n",
        encoding="utf-8",
    )
    app = ler_desktop(arquivo)

    assert app is not None
    assert app.generico == "Editor de Código"
    assert app.keywords == ("programação", "IDE") and app.exec_nome == "code"
    assert ResolvedorDeApps((app,)).resolver("programacao").app is app


def test_binarios_do_path_sao_descobertos_sem_serem_autorizados(tmp_path: Path) -> None:
    binarios = tmp_path / "bin"
    binarios.mkdir()
    executavel = binarios / "meu-editor"
    executavel.write_text("#!/bin/true\n", encoding="utf-8")
    executavel.chmod(0o755)

    apps = listar_binarios_do_path(ambiente={"PATH": str(binarios)})

    assert [app.nome for app in apps] == ["meu-editor"]
    assert (
        RegistroDeApps.montar(
            [], incluir_binarios_do_path=True, ambiente={"PATH": str(binarios)}
        ).autorizados
        == {}
    )


def test_dicas_respeitam_orcamento_e_preservam_nomes_canonicos() -> None:
    dicas = dicas_de_apps(("Discord", "TeamSpeak", "Discord", "x" * 500), primeira="jarvis")

    assert dicas.startswith("jarvis, Discord, TeamSpeak")
    assert len(dicas) <= 480


def test_medicao_publica_top_1_top_3_e_falso_aceite() -> None:
    casos = (
        CasoDePronuncia("discórdi", "discord"),
        CasoDePronuncia("tim speak", "teamspeak"),
        CasoDePronuncia("planilha galactica", "discord"),
    )

    metricas = medir(casos, ResolvedorDeApps(APPS))

    assert metricas.total == 3
    assert metricas.com_referencia == 3
    assert metricas.top_1 == metricas.top_3 == 2
    assert metricas.falso_aceite == 0
