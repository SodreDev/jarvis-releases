"""ADR-0028: as ferramentas reais do catálogo v1, do pedido do modelo ao resultado — sem rede."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.apps.resolvedor import RepositorioDeAliases
from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.executor.lancador import App, RegistroDeApps, dividir_exec, ler_desktop
from jarvis.politica.abertura import nome_de_app
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731


@pytest.fixture
def casa(tmp_path: Path) -> Path:
    lar = tmp_path / "casa"
    (lar / "Documentos" / "projetos").mkdir(parents=True)
    (lar / "Documentos" / "notas.txt").write_text("comprar café\nligar para a Bia\n", "utf-8")
    (lar / "Documentos" / "projetos" / "jarvis-ideias.md").write_text("# ideias\n", "utf-8")
    (lar / "Documentos" / ".env").write_text("API_TOKEN=segredo\n", "utf-8")
    (lar / ".ssh").mkdir()
    (lar / ".ssh" / "id_rsa").write_text("CHAVE PRIVADA", "utf-8")
    (lar / "Documentos" / "atalho").symlink_to(lar / ".ssh" / "id_rsa")
    return lar


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


def _executor(
    lar: Path, auditoria: LogDeAuditoria, modo: Modo = Modo.PADRAO, **mudancas: Any
) -> ExecutorDeFerramentas:
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        modo=modo,
        pasta_do_jarvis=lar.parent / "area",
        session_id="01a1c000-0000-7000-8000-000000000006",
        apps_autorizados=mudancas.pop("apps_autorizados", frozenset()),
        sites_sem_confirmar=mudancas.pop("sites_sem_confirmar", frozenset()),
    )
    executor = ExecutorDeFerramentas(pdp=pdp, lar=lar, **mudancas)
    executor.preparar()
    return executor


# --- leitura dentro das raízes ---------------------------------------------------------
def test_lista_a_pasta_sem_o_segredo_e_sem_seguir_link(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    resultado = _executor(casa, auditoria).executar(
        "files.list_dir", {"path": "~/Documentos"}, cancelado=NUNCA
    )
    assert resultado.status == "ok", resultado.motivo
    nomes = {e["nome"]: e["tipo"] for e in resultado.dados["entradas"]}
    assert nomes == {"atalho": "link (não seguido)", "notas.txt": "arquivo", "projetos": "pasta"}
    assert resultado.dados["omitidas_por_seguranca"] == 1, ".env não aparece"


def test_le_o_texto_e_recusa_link_para_a_chave(casa: Path, auditoria: LogDeAuditoria) -> None:
    executor = _executor(casa, auditoria)
    lido = executor.executar("files.read_text", {"path": "~/Documentos/notas.txt"}, cancelado=NUNCA)
    assert lido.status == "ok"
    assert "comprar café" in lido.dados["texto"]

    pelo_link = executor.executar(
        "files.read_text", {"path": "~/Documentos/atalho"}, cancelado=NUNCA
    )
    assert pelo_link.status in {"erro", "negado"}
    assert "CHAVE" not in pelo_link.para_o_modelo()


def test_chave_ssh_e_negada_ate_no_modo_total(casa: Path, auditoria: LogDeAuditoria) -> None:
    resultado = _executor(casa, auditoria, Modo.TOTAL).executar(
        "files.read_text", {"path": "~/.ssh/id_rsa"}, cancelado=NUNCA
    )
    assert resultado.status == "negado"
    assert "CHAVE" not in resultado.para_o_modelo()


def test_no_modo_padrao_do_produto_nada_do_dono_e_lido(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    """Padrão do Jarvis = modo `jarvis`: só a área dele. As pastas do dono ficam fora."""
    resultado = _executor(casa, auditoria, Modo.JARVIS).executar(
        "files.read_text", {"path": "~/Documentos/notas.txt"}, cancelado=NUNCA
    )
    assert resultado.status == "negado"
    assert "fora das raízes" in resultado.motivo


def test_caminho_relativo_e_recusado_com_exemplo(casa: Path, auditoria: LogDeAuditoria) -> None:
    resultado = _executor(casa, auditoria).executar(
        "files.list_dir", {"path": "Documentos"}, cancelado=NUNCA
    )
    assert resultado.status == "erro"
    assert "~/Documentos" in resultado.motivo


def test_procura_pelo_nome_sem_acento_e_sem_entrar_no_negado(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor = _executor(casa, auditoria, Modo.TOTAL)
    achados = executor.executar("files.search_in_roots", {"consulta": "IDEIAS"}, cancelado=NUNCA)
    assert achados.status == "ok"
    assert any(a.endswith("jarvis-ideias.md") for a in achados.dados["achados"])
    chaves = executor.executar("files.search_in_roots", {"consulta": "id_rsa"}, cancelado=NUNCA)
    assert chaves.dados["achados"] == []


def test_a_busca_para_quando_o_dono_interrompe(casa: Path, auditoria: LogDeAuditoria) -> None:
    resultado = _executor(casa, auditoria).executar(
        "files.search_in_roots", {"consulta": "notas"}, cancelado=lambda: True
    )
    assert resultado.status == "cancelado"


# --- escrita só na pasta do Jarvis: moderada, roda sem perguntar e avisa -------------------------
def test_rascunho_e_moderado_roda_sem_perguntar_e_avisa(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    perguntas: list[Confirmacao] = []

    def negar(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return False

    executor = _executor(casa, auditoria)
    resultado = executor.executar(
        "files.write_draft",
        {"nome": "lista", "texto": "café e pão"},
        cancelado=NUNCA,
        confirmar=negar,
    )
    assert resultado.status == "ok"
    assert perguntas == [], "tool moderada não pergunta (dono, 2026-10-18)"
    assert resultado.aviso == "Gravei o rascunho lista.md na pasta do Jarvis."
    assert [p.name for p in (casa.parent / "area" / "rascunhos").glob("*.md")] == ["lista.md"]


def test_rascunho_com_o_sim_grava_novo_e_nunca_sobrescreve(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor = _executor(casa, auditoria)
    sim = lambda _p: True  # noqa: E731
    primeiro = executor.executar(
        "files.write_draft",
        {"nome": "../../.bashrc", "texto": "um"},
        cancelado=NUNCA,
        confirmar=sim,
    )
    segundo = executor.executar(
        "files.write_draft",
        {"nome": "../../.bashrc", "texto": "dois"},
        cancelado=NUNCA,
        confirmar=sim,
    )
    assert primeiro.status == segundo.status == "ok"
    pasta = casa.parent / "area" / "rascunhos"
    assert sorted(p.name for p in pasta.iterdir() if p.is_file()) == ["bashrc-2.md", "bashrc.md"]
    assert (pasta / "bashrc.md").read_text("utf-8") == "um", "o primeiro não foi sobrescrito"
    assert not (casa / ".bashrc").exists()


def test_rascunho_de_evento_e_um_ics_local_sem_convite(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    resultado = _executor(casa, auditoria).executar(
        "calendar.create_draft_event",
        {"titulo": "Dentista, sala 3", "inicio": "2026-10-20T14:30", "duracao_min": 45},
        cancelado=NUNCA,
        confirmar=lambda _p: True,
    )
    assert resultado.status == "ok"
    ics = Path(resultado.dados["caminho"]).read_text("utf-8")
    assert "DTSTART:20261020T143000" in ics and "DTEND:20261020T151500" in ics
    assert "SUMMARY:Dentista\\, sala 3" in ics
    assert "ATTENDEE" not in ics


# --- apps e sites ------------------------------------------------------------------------
def _desktop(pasta: Path, nome: str, exec_: str, titulo: str) -> None:
    (pasta / f"{nome}.desktop").write_text(
        f"[Desktop Entry]\nType=Application\nName={titulo}\nExec={exec_}\n", "utf-8"
    )


def test_o_exec_do_desktop_vira_argv_sem_shell(tmp_path: Path) -> None:
    assert dividir_exec('"/opt/Meu App/app" --nova-janela %U') == [
        "/opt/Meu App/app",
        "--nova-janela",
        "%U",
    ]
    _desktop(tmp_path, "perigoso", "sh -c 'rm -rf ~'", "Perigoso")
    _desktop(tmp_path, "calc", "kcalc %u", "Calculadora")
    assert ler_desktop(tmp_path / "perigoso.desktop") is None
    calc = ler_desktop(tmp_path / "calc.desktop")
    assert calc is not None and calc.argv == ("kcalc",)


def test_app_fora_do_registro_e_negado_e_sugere(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    apps = tmp_path / "apps"
    apps.mkdir()
    _desktop(apps, "org.kde.kcalc", "kcalc", "KCalc")
    _desktop(apps, "org.kde.dolphin", "dolphin %u", "Dolphin")
    registro = RegistroDeApps.montar(["org.kde.kcalc"], pastas=[str(apps)])
    lancados: list[App] = []

    def lancar(app: App) -> int:
        lancados.append(app)
        return 4242

    executor = _executor(
        casa,
        auditoria,
        registro_de_apps=registro,
        apps_autorizados=frozenset(
            nome_de_app(n) for a in registro.autorizados.values() for n in a.nomes
        ),
        lancar_app=lancar,
    )

    fora = executor.executar("apps.launch", {"nome": "Dolphin"}, cancelado=NUNCA)
    assert fora.status == "negado"
    assert "KCalc" in fora.motivo, "a recusa sugere o que está autorizado"
    dentro = executor.executar("apps.launch", {"nome": "kcalc"}, cancelado=NUNCA)
    assert dentro.status == "ok"
    assert [a.argv for a in lancados] == [("kcalc",)]


def test_app_marcado_chamado_por_nome_parcial_abre_sem_confirmar(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    """O executor sempre resolveu "brave" para "Brave Web Browser"; a política exigia o nome
    inteiro e negava. Agora o nome que o PDP vê já é o do app marcado."""
    apps = tmp_path / "apps"
    apps.mkdir()
    _desktop(apps, "brave-browser", "brave-browser %U", "Brave Web Browser")
    registro = RegistroDeApps.montar(["brave-browser"], pastas=[str(apps)])
    lancados: list[App] = []

    def lancar(app: App) -> int:
        lancados.append(app)
        return 1

    executor = _executor(
        casa,
        auditoria,
        registro_de_apps=registro,
        apps_autorizados=frozenset(
            nome_de_app(n) for a in registro.autorizados.values() for n in a.nomes
        ),
        lancar_app=lancar,
    )

    def nunca_confirma(_c: Confirmacao) -> bool:
        raise AssertionError("app marcado não pode pedir confirmação")

    for dito in ("brave", "Brave", "brave-browser", "Brave Web Browser"):
        resultado = executor.executar(
            "apps.launch", {"nome": dito}, cancelado=NUNCA, confirmar=nunca_confirma
        )
        assert resultado.status == "ok", (dito, resultado.motivo)
    assert [a.id for a in lancados] == ["brave-browser"] * 4


def test_app_autorizado_por_pronuncia_aproximada_abre_o_canonico(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    apps = tmp_path / "apps"
    apps.mkdir()
    _desktop(apps, "discord", "discord", "Discord")
    registro = RegistroDeApps.montar(["discord"], pastas=[str(apps)])
    lancados: list[App] = []

    def lancar(app: App) -> int:
        lancados.append(app)
        return 7

    executor = _executor(
        casa,
        auditoria,
        registro_de_apps=registro,
        apps_autorizados=frozenset(
            nome_de_app(nome) for nome in registro.autorizados["discord"].nomes
        ),
        lancar_app=lancar,
    )

    resultado = executor.executar("apps.launch", {"nome": "discórdi"}, cancelado=NUNCA)

    assert resultado.status == "ok", resultado.motivo
    assert resultado.dados["app"] == "Discord"
    assert [app.id for app in lancados] == ["discord"]


def test_app_ambiguo_pergunta_e_nunca_lanca(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    apps = tmp_path / "apps"
    apps.mkdir()
    _desktop(apps, "discord", "discord", "Discord")
    _desktop(apps, "discord-canary", "discord-canary", "Discord Canary")
    registro = RegistroDeApps.montar(["discord", "discord-canary"], pastas=[str(apps)])
    lancados: list[App] = []

    def lancar(app: App) -> int:
        lancados.append(app)
        return 7

    executor = _executor(
        casa,
        auditoria,
        registro_de_apps=registro,
        apps_autorizados=frozenset(
            nome_de_app(nome) for app in registro.autorizados.values() for nome in app.nomes
        ),
        lancar_app=lancar,
    )

    resultado = executor.executar("apps.launch", {"nome": "discord"}, cancelado=NUNCA)

    assert resultado.status == "negado"
    assert "você quis dizer Discord, Discord Canary?" in resultado.motivo
    assert lancados == []


def test_correcao_confirmada_vira_alias_sem_ampliar_autorizacao(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    apps = tmp_path / "apps"
    apps.mkdir()
    _desktop(apps, "discord", "discord", "Discord")
    aliases = RepositorioDeAliases(tmp_path / "estado" / "aliases.json")
    registro = RegistroDeApps.montar(
        ["discord"], pastas=[str(apps)], repositorio_de_aliases=aliases
    )
    lancados: list[App] = []

    def lancar(app: App) -> int:
        lancados.append(app)
        return 7

    executor = _executor(
        casa,
        auditoria,
        registro_de_apps=registro,
        apps_autorizados=frozenset(
            nome_de_app(nome) for nome in registro.autorizados["discord"].nomes
        ),
        lancar_app=lancar,
    )

    executor.aprender_correcao_de_app("bate-papo roxo", "discord")
    resultado = executor.executar("apps.launch", {"nome": "bate-papo roxo"}, cancelado=NUNCA)

    assert aliases.carregar() == {"discord": ("bate-papo roxo",)}
    assert resultado.status == "ok"
    assert [app.id for app in lancados] == ["discord"]


def _executor_de_navegadores(
    casa: Path, auditoria: LogDeAuditoria, tmp_path: Path, *, principal: str
) -> tuple[ExecutorDeFerramentas, list[tuple[str, ...]]]:
    from jarvis.executor.navegadores import AbridorDeNavegador

    binarios = tmp_path / "bin"
    binarios.mkdir(exist_ok=True)
    for nome in ("brave-stable", "firefox"):
        (binarios / nome).write_text("#!/bin/true\n")
        (binarios / nome).chmod(0o755)
    abertos: list[tuple[str, ...]] = []

    def lancar(argv: Any, **_: Any) -> int:
        abertos.append(tuple(argv))
        return 77

    navegadores = {"brave": str(binarios / "brave-stable"), "firefox": str(binarios / "firefox")}
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=casa,
        auditoria=auditoria,
        modo=Modo.PADRAO,
        pasta_do_jarvis=casa.parent / "area",
        session_id="01a1c000-0000-7000-8000-000000000007",
        navegadores=frozenset(navegadores),
        navegador_principal=principal,
    )
    executor = ExecutorDeFerramentas(
        pdp=pdp,
        lar=casa,
        navegadores=AbridorDeNavegador(navegadores=navegadores, principal=principal, lancar=lancar),
    )
    executor.preparar()
    return executor, abertos


def _sem_confirmar(_c: Confirmacao) -> bool:
    raise AssertionError("navegador configurado não pede confirmação")


def test_abrir_so_o_navegador_principal_sem_url_e_sem_confirmar(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")

    r = executor.executar("browser.launch", {}, cancelado=NUNCA, confirmar=_sem_confirmar)

    assert r.status == "ok" and r.dados == {"navegador": "brave", "pid": 77}
    assert [a[1:] for a in abertos] == [()], "sem URL: só o programa"
    assert Path(abertos[0][0]).name == "brave-stable"


def test_abrir_o_navegador_pelo_nome_resolve_entre_os_configurados(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")

    for dito in ("firefox", "Firefox"):
        r = executor.executar(
            "browser.launch", {"navegador": dito}, cancelado=NUNCA, confirmar=_sem_confirmar
        )
        assert r.status == "ok" and r.dados["navegador"] == "firefox"
    assert {Path(a[0]).name for a in abertos} == {"firefox"}


def test_navegador_que_o_dono_nao_configurou_e_negado(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")

    r = executor.executar(
        "browser.launch", {"navegador": "chrome"}, cancelado=NUNCA, confirmar=_sem_confirmar
    )

    assert r.status == "negado" and abertos == []


def test_sem_principal_configurado_nao_abre_e_diz_onde_escolher(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="")

    r = executor.executar("browser.launch", {}, cancelado=NUNCA, confirmar=_sem_confirmar)

    assert r.status == "negado" and "Configuração → Navegadores" in r.motivo and abertos == []


def test_o_modelo_ve_os_navegadores_configurados(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, _ = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")
    descricao = next(
        t["descricao"] for t in executor.catalogo_para_o_modelo() if t["id"] == "browser.launch"
    )
    assert str(descricao).endswith("Configurados agora: brave (principal), firefox.")


# --- uma instância só (dono, 2026-10-21): só abre navegador se não houver um ativo ----------------
def test_abrir_o_navegador_ja_aberto_traz_a_janela_do_dono_e_nao_abre_outra(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")
    assert executor.navegadores is not None
    mostrados: list[str] = []

    def mostrar(familia: str) -> dict[str, Any]:
        mostrados.append(familia)
        return {"visivel": True}

    executor.navegadores.mostrar_aberto = mostrar
    executor.navegadores.em_execucao = lambda _f: 4242

    r = executor.executar("browser.launch", {}, cancelado=NUNCA, confirmar=_sem_confirmar)

    assert r.status == "ok" and abertos == [], "nenhuma janela nem instância nova"
    assert r.dados["ja_aberto"] is True and r.dados["visivel"] is True and r.dados["pid"] is None
    assert mostrados == ["brave"]


def test_navegador_rodando_sem_extensao_nao_ganha_outra_janela(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")
    assert executor.navegadores is not None
    executor.navegadores.mostrar_aberto = lambda _f: None  # extensão não conectada
    executor.navegadores.em_execucao = lambda f: 4242 if f == "brave" else None

    r = executor.executar("browser.launch", {}, cancelado=NUNCA, confirmar=_sem_confirmar)
    firefox = executor.executar(
        "browser.launch", {"navegador": "firefox"}, cancelado=NUNCA, confirmar=_sem_confirmar
    )

    assert r.status == "ok" and r.dados["ja_aberto"] is True and r.dados["visivel"] is False
    assert "não abri outra janela" in r.dados["situacao"]
    assert firefox.dados == {"navegador": "firefox", "pid": 77}, "o Firefox não estava aberto"
    assert [Path(a[0]).name for a in abertos] == ["firefox"]


def test_aberto_sem_janela_nenhuma_abrir_e_abrir_a_janela_dele(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor, abertos = _executor_de_navegadores(casa, auditoria, tmp_path, principal="brave")
    assert executor.navegadores is not None
    executor.navegadores.mostrar_aberto = lambda _f: {"visivel": False, "sem_janela": True}
    executor.navegadores.em_execucao = lambda _f: 4242

    r = executor.executar("browser.launch", {}, cancelado=NUNCA, confirmar=_sem_confirmar)

    assert r.status == "ok" and r.dados == {"navegador": "brave", "pid": 77}
    assert len(abertos) == 1


def test_apps_launch_de_um_navegador_ja_aberto_traz_a_janela_e_fechado_abre_como_app(
    tmp_path: Path, casa: Path, auditoria: LogDeAuditoria
) -> None:
    """«Abre o Brave» pelo apps.launch abriria outra janela do Brave já aberto — mesmo liberado só
    como app, sem estar em Configuração → Navegadores. Fechado, ele abre como qualquer app."""
    from jarvis.executor.navegadores import AbridorDeNavegador

    apps = tmp_path / "apps"
    apps.mkdir()
    _desktop(apps, "brave-browser", "brave-browser-stable %U", "Brave Web Browser")
    registro = RegistroDeApps.montar(["brave-browser"], pastas=[str(apps)])
    lancados: list[App] = []

    def lancar(app: App) -> int:
        lancados.append(app)
        return 7

    def nunca(*_a: Any, **_k: Any) -> int:
        raise AssertionError("o apps.launch abre pelo lançador do app, não pelo do navegador")

    abridor = AbridorDeNavegador(
        navegadores={},  # liberado só como app
        principal="",
        lancar=nunca,
        mostrar_aberto=lambda _f: {"visivel": True},
    )
    executor = _executor(
        casa,
        auditoria,
        registro_de_apps=registro,
        apps_autorizados=frozenset(
            nome_de_app(nome) for app in registro.autorizados.values() for nome in app.nomes
        ),
        lancar_app=lancar,
        navegadores=abridor,
    )

    r = executor.executar("apps.launch", {"nome": "brave"}, cancelado=NUNCA)

    assert r.status == "ok", r.motivo
    assert r.dados["ja_aberto"] is True and r.dados["visivel"] is True
    assert lancados == [], "nada foi lançado de novo"

    abridor.mostrar_aberto = lambda _f: None  # sem extensão conectada…
    abridor.em_execucao = lambda _f: 4242  # …mas o processo do Brave rodando
    rodando = executor.executar("apps.launch", {"nome": "brave"}, cancelado=NUNCA)
    assert rodando.status == "ok" and rodando.dados["ja_aberto"] is True and lancados == []

    abridor.em_execucao = lambda _f: None  # fechado: aí sim abre, uma vez, como app
    fechado = executor.executar("apps.launch", {"nome": "brave"}, cancelado=NUNCA)
    assert fechado.status == "ok" and fechado.dados["pid"] == 7
    assert [a.id for a in lancados] == ["brave-browser"]


def test_site_so_http_e_dominio_liberado_abre_sem_perguntar(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    abertos: list[str] = []
    perguntas: list[Confirmacao] = []
    executor = _executor(
        casa,
        auditoria,
        abrir_site=abertos.append,
        sites_sem_confirmar=frozenset({"wikipedia.org"}),
    )

    def perguntar(p: Confirmacao) -> bool:
        perguntas.append(p)
        return False

    js = executor.executar("sites.open", {"url": "javascript:alert(1)"}, cancelado=NUNCA)
    senha = executor.executar("sites.open", {"url": "https://eu:x@banco.com"}, cancelado=NUNCA)
    livre = executor.executar(
        "sites.open",
        {"url": "https://pt.wikipedia.org/wiki/Jarvis"},
        cancelado=NUNCA,
        confirmar=perguntar,
    )
    outro = executor.executar(
        "sites.open", {"url": "https://exemplo.com"}, cancelado=NUNCA, confirmar=perguntar
    )
    assert js.status == senha.status == "negado"
    assert livre.status == "ok"
    assert outro.status == "ok", "abrir site é livre (dono, 2026-10-18)"
    assert perguntas == []
    assert abertos == ["https://pt.wikipedia.org/wiki/Jarvis", "https://exemplo.com"]


def test_argumento_a_mais_e_tool_inventada_sao_recusados(
    casa: Path, auditoria: LogDeAuditoria
) -> None:
    executor = _executor(casa, auditoria)
    extra = executor.executar(
        "files.list_dir", {"path": "~/Documentos", "recursivo": True}, cancelado=NUNCA
    )
    inventada = executor.executar("shell.run", {"cmd": "ls"}, cancelado=NUNCA)
    assert extra.status == "erro" and "contrato" in extra.motivo
    assert inventada.status == "negado"


def test_o_catalogo_do_modelo_so_tem_o_que_tem_corpo(casa: Path, auditoria: LogDeAuditoria) -> None:
    ids = {t["id"] for t in _executor(casa, auditoria).catalogo_para_o_modelo()}
    assert ids == {
        "files.list_dir",
        "files.read_text",
        "files.search_in_roots",
        "files.write_draft",
        "calendar.create_draft_event",
        "apps.launch",
        "sites.open",
        "browser.launch",
        "acao.desfazer",
        # as nativas do assistente de voz (item 4); `timer.*` só com agenda e `tarefa.*` com gestor
        "files.create_dir",
        "files.copy",
        "files.move",
        "system.clock.now",
        "system.machine.status",
        "system.volume.get",
        "system.volume.set",
        "system.brightness.set",
        "media.player.control",
        "media.player.status",
        "window.list",
        "window.focused",
        "window.focus_app",
        "window.close",
        "apps.quit",
        "clipboard.text.read",
        "clipboard.text.write",
        "notify.desktop.send",
        "web.buscar",
        "web.canal_videos",
        "web.ler",
    }
    assert not any(i.startswith("memoria.") for i in ids)
