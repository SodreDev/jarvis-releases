"""Pedido do dono (2026-10-17): navegadores e apps escolhidos na janela valem para as ferramentas.

Sem navegador de verdade: `.desktop` e binários falsos numa pasta de teste, e o lançador injetado.
"""

from __future__ import annotations

import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.lancador import AppRecusado, RegistroDeApps, listar_apps
from jarvis.executor.navegadores import (
    AbridorDeNavegador,
    NavegadorAberto,
    argv_da_entrada,
    detectar,
    familia_de,
    juntar,
    navegador_em_execucao,
    separar,
)
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731


def _desktop(pasta: Path, id_: str, nome: str, exec_: str, *, extras: str = "") -> Path:
    arquivo = pasta / f"{id_}.desktop"
    arquivo.write_text(
        f"[Desktop Entry]\nType=Application\nName={nome}\nExec={exec_}\n{extras}\n", "utf-8"
    )
    return arquivo


def _binario(pasta: Path, nome: str) -> Path:
    arquivo = pasta / nome
    arquivo.write_text("#!/bin/true\n", "utf-8")
    arquivo.chmod(arquivo.stat().st_mode | stat.S_IXUSR)
    return arquivo


@pytest.fixture
def instalados(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    apps = tmp_path / "applications"
    bins = tmp_path / "bin"
    apps.mkdir()
    bins.mkdir()
    https = "MimeType=x-scheme-handler/http;x-scheme-handler/https;\n"
    _desktop(apps, "brave-browser", "Brave Web Browser", f"{bins}/brave-stable %U", extras=https)
    _desktop(
        apps,
        "brave-browser-beta",
        "Brave Web Browser (Beta)",
        f"{bins}/brave-beta %U",
        extras=https,
    )
    _desktop(
        apps,
        "org.mozilla.firefox",
        "Firefox",
        "/usr/bin/flatpak run --branch=stable org.mozilla.firefox @@u %U @@",
        extras=https,
    )
    _desktop(apps, "org.kde.kate", "Kate", "kate %U", extras="Categories=Utility;TextEditor;")
    _desktop(
        apps, "kcm_clock", "Data e hora", "systemsettings kcm_clock", extras="Categories=Settings;"
    )
    _desktop(apps, "servico", "Serviço", "servico", extras="NoDisplay=true")
    _binario(bins, "brave-stable")
    _binario(bins, "firefox")
    yield apps, bins


def test_familia_junta_as_edicoes_do_mesmo_navegador() -> None:
    assert familia_de("Brave Web Browser (Beta)") == familia_de("Brave Web Browser") == "brave"
    assert familia_de("Google Chrome") == "chrome"
    assert familia_de("Firefox") == "firefox"


def test_detecta_os_navegadores_e_todas_as_opcoes_de_cada(
    instalados: tuple[Path, Path],
) -> None:
    apps, bins = instalados
    achados = {n.familia: n for n in detectar(pastas=[str(apps)], caminho_dos_binarios=str(bins))}

    assert set(achados) == {"brave", "firefox"}, "Kate, Data e hora e Serviço não são navegador"
    brave = achados["brave"]
    assert len(brave.opcoes) == 2, "o estável e o beta são duas opções do mesmo navegador"
    assert {o.argv[0] for o in brave.opcoes} == {f"{bins}/brave-stable", f"{bins}/brave-beta"}
    firefox = achados["firefox"]
    assert {o.argv[0] for o in firefox.opcoes} == {"/usr/bin/flatpak", f"{bins}/firefox"}
    flatpak = next(o for o in firefox.opcoes if o.argv[0] == "/usr/bin/flatpak")
    assert "@@u" not in flatpak.argv and "@@" not in flatpak.argv


def test_lista_de_apps_deixa_de_fora_painel_de_config_e_servico(
    instalados: tuple[Path, Path],
) -> None:
    apps, _ = instalados
    ids = {a.id for a in listar_apps(pastas=[str(apps)])}
    assert "org.kde.kate" in ids and "brave-browser" in ids
    assert "kcm_clock" not in ids and "servico" not in ids


def test_app_escolhido_a_mao_vira_autorizado_pelo_nome_do_arquivo(
    instalados: tuple[Path, Path], tmp_path: Path
) -> None:
    apps, bins = instalados
    meu = _binario(tmp_path, "meu-editor")
    avulso = _desktop(tmp_path, "avulso", "Avulso Especial", f"{bins}/firefox")
    registro = RegistroDeApps.montar(
        [], pastas=[str(apps)], extras=[str(meu), str(avulso), "/nao/existe", "relativo"]
    )

    assert registro.resolver("meu-editor").argv == (str(meu),)
    assert registro.resolver("Avulso Especial").id == "avulso"
    with pytest.raises(AppRecusado):
        registro.resolver("kate")  # instalado, mas o dono não marcou


def test_binario_nao_executavel_ou_interpretador_nao_entra(tmp_path: Path) -> None:
    sem_permissao = tmp_path / "sem-x"
    sem_permissao.write_text("x", "utf-8")
    sem_permissao.chmod(0o644)
    registro = RegistroDeApps.montar([], pastas=[], extras=[str(sem_permissao), "/usr/bin/bash"])
    assert registro.autorizados == {}


def test_abre_no_principal_ou_no_que_o_pedido_nomeia(instalados: tuple[Path, Path]) -> None:
    _, bins = instalados
    chamadas: list[tuple[str, ...]] = []

    def lancar(argv: tuple[str, ...], **_: object) -> int:
        chamadas.append(tuple(argv))
        return 1

    abridor = AbridorDeNavegador(
        navegadores={"brave": f"{bins}/brave-stable", "firefox": f"{bins}/firefox"},
        principal="brave",
        lancar=lancar,
    )
    assert abridor.abrir("https://exemplo.com") == ("brave", False)
    assert abridor.abrir("https://exemplo.com", "Firefox") == ("firefox", False)
    assert chamadas == [
        (f"{bins}/brave-stable", "https://exemplo.com"),
        (f"{bins}/firefox", "https://exemplo.com"),
    ]
    with pytest.raises(AppRecusado, match="não está configurado"):
        abridor.abrir("https://exemplo.com", "opera")


def test_reutiliza_a_aba_atual_quando_o_controlador_do_navegador_oferece_isso() -> None:
    reutilizadas: list[tuple[str, str, bool]] = []
    lancados: list[tuple[str, ...]] = []

    def reutilizar(url: str, familia: str, nova_aba: bool) -> dict[str, Any]:
        reutilizadas.append((url, familia, nova_aba))
        return {"nova_aba": False}

    abridor = AbridorDeNavegador(
        navegadores={"brave": "/nao-precisa-existir"},
        principal="brave",
        lancar=_anotando(lancados),
        reutilizar_aba=reutilizar,
    )

    assert abridor.abrir("https://www.youtube.com/watch?v=novo") == ("brave", True)
    assert reutilizadas == [("https://www.youtube.com/watch?v=novo", "brave", False)]
    assert lancados == []


def test_aba_nova_com_o_navegador_aberto_vai_pela_extensao_e_nao_executa_o_binario() -> None:
    """O caso do dono (2026-10-21): `sites.open` com `nova_aba` pulava a extensão e executava o
    Brave com a URL; o Brave aberto a punha na última janela ativa dele — a janela própria do
    Jarvis —, e o vídeo foi parar lá. Agora a aba nova também vai pela extensão, na janela dele."""
    pedidos: list[tuple[str, str, bool]] = []
    lancados: list[tuple[str, ...]] = []

    def pela_extensao(url: str, familia: str, nova_aba: bool) -> dict[str, Any]:
        pedidos.append((url, familia, nova_aba))
        return {"nova_aba": True, "janela": "dono", "visivel": True}

    abridor = AbridorDeNavegador(
        navegadores={"brave": "/nao-precisa-existir"},
        principal="brave",
        lancar=_anotando(lancados),
        reutilizar_aba=pela_extensao,
    )

    url = "https://www.youtube.com/watch?v=video"
    assert abridor.abrir(url, reutilizar_aba=False) == ("brave", False)
    assert pedidos == [(url, "brave", True)]
    assert lancados == [], "com o navegador aberto, o binário não é executado"


def test_sem_extensao_o_binario_abre_o_navegador_com_a_url(
    instalados: tuple[Path, Path],
) -> None:
    _, bins = instalados
    lancados: list[tuple[str, ...]] = []
    abridor = AbridorDeNavegador(
        navegadores={"brave": f"{bins}/brave-stable"},
        principal="brave",
        lancar=_anotando(lancados),
        reutilizar_aba=lambda *_: None,  # nenhuma extensão conectada
    )

    assert abridor.abrir("https://exemplo.com", reutilizar_aba=False) == ("brave", False)
    assert lancados == [(f"{bins}/brave-stable", "https://exemplo.com")]


def test_sem_navegador_ativo_abrir_o_navegador_lanca_um_e_so_entao(
    instalados: tuple[Path, Path],
) -> None:
    _, bins = instalados
    lancados: list[tuple[str, ...]] = []
    rodando: set[str] = set()
    abridor = AbridorDeNavegador(
        navegadores={"brave": f"{bins}/brave-stable"},
        principal="brave",
        lancar=_anotando(lancados),
        mostrar_aberto=lambda _f: None,
        em_execucao=lambda f: 4242 if f in rodando else None,
    )

    primeiro = abridor.abrir_sozinho()
    rodando.add("brave")  # agora ele está aberto
    segundo = abridor.abrir_sozinho()

    assert primeiro == NavegadorAberto("brave", 1)
    assert segundo == NavegadorAberto("brave", None, ja_aberto=True)
    assert lancados == [(f"{bins}/brave-stable",)], "uma vez só"


def test_o_navegador_rodando_se_acha_pelo_executavel_no_proc(tmp_path: Path) -> None:
    """Só o executável (`/proc/<pid>/exe`) é lido — nunca o ambiente nem a linha de comando."""
    proc = tmp_path / "proc"
    for pid, alvo in (
        ("101", "/usr/bin/python3.12"),
        ("202", "/opt/brave.com/brave/brave"),
        ("303", "/app/lib/firefox/firefox"),  # o Firefox do Flatpak, de dentro da caixa
        ("404", "/usr/lib64/chromium-browser/chromium-browser (deleted)"),  # atualizado rodando
        ("505", "/usr/bin/zenity"),  # não é o Zen
    ):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "exe").symlink_to(alvo)
    (proc / "606").mkdir()  # de outro usuário: o exe não se deixa ler
    (proc / "self").mkdir()

    assert navegador_em_execucao("brave", raiz=proc) == 202
    assert navegador_em_execucao("firefox", raiz=proc) == 303
    assert navegador_em_execucao("chromium", raiz=proc) == 404
    assert navegador_em_execucao("zen", raiz=proc) is None
    assert navegador_em_execucao("vivaldi", raiz=proc) is None
    assert navegador_em_execucao("brave", raiz=tmp_path / "sem-proc") is None


def test_binario_que_sumiu_diz_para_escolher_de_novo(tmp_path: Path) -> None:
    abridor = AbridorDeNavegador(
        navegadores={"brave": str(tmp_path / "apagado")},
        principal="brave",
        lancar=lambda *a, **k: 0,
    )
    with pytest.raises(AppRecusado, match="escolha o binário de novo"):
        abridor.abrir("https://exemplo.com")


def test_entradas_da_configuracao_ida_e_volta(instalados: tuple[Path, Path]) -> None:
    pares = {"brave": "/a/brave", "firefox": "/b/firefox"}
    assert separar(juntar(pares)) == pares
    assert argv_da_entrada("/nao/existe") == ()


# --- sites.open pelo executor ----------------------------------------------------------------
def _anotando(lancados: list[tuple[str, ...]]) -> Callable[..., int]:
    def lancar(argv: tuple[str, ...], **_: object) -> int:
        lancados.append(tuple(argv))
        return 1

    return lancar


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


def _executor(
    tmp_path: Path, auditoria: LogDeAuditoria, **mudancas: object
) -> ExecutorDeFerramentas:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        modo=Modo.PADRAO,
        pasta_do_jarvis=tmp_path / "area",
        session_id="01a1c000-0000-7000-8000-000000000007",
        sites_sem_confirmar=frozenset({"exemplo.com"}),
    )
    executor = ExecutorDeFerramentas(pdp=pdp, lar=lar, **mudancas)  # type: ignore[arg-type]
    executor.preparar()
    return executor


def test_sites_open_vai_para_o_navegador_principal_e_nao_para_o_portal(
    tmp_path: Path, auditoria: LogDeAuditoria, instalados: tuple[Path, Path]
) -> None:
    _, bins = instalados
    pelo_portal: list[str] = []
    lancados: list[tuple[str, ...]] = []
    executor = _executor(
        tmp_path,
        auditoria,
        abrir_site=pelo_portal.append,
        navegadores=AbridorDeNavegador(
            navegadores={"brave": f"{bins}/brave-stable", "firefox": f"{bins}/firefox"},
            principal="brave",
            lancar=_anotando(lancados),
        ),
    )

    principal = executor.executar("sites.open", {"url": "https://exemplo.com/a"}, cancelado=NUNCA)
    outro = executor.executar(
        "sites.open", {"url": "https://exemplo.com/b", "navegador": "firefox"}, cancelado=NUNCA
    )

    assert principal.status == "ok" and principal.dados["navegador"] == "brave"
    assert principal.dados["reutilizou_aba"] is False
    assert outro.status == "ok" and outro.dados["navegador"] == "firefox"
    assert pelo_portal == [], "com navegador configurado o portal não é usado"
    assert lancados == [
        (f"{bins}/brave-stable", "https://exemplo.com/a"),
        (f"{bins}/firefox", "https://exemplo.com/b"),
    ]


def test_sites_open_sem_principal_continua_pelo_portal(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    pelo_portal: list[str] = []
    executor = _executor(
        tmp_path,
        auditoria,
        abrir_site=pelo_portal.append,
        navegadores=AbridorDeNavegador(navegadores={}, principal=""),
    )
    resultado = executor.executar("sites.open", {"url": "https://exemplo.com"}, cancelado=NUNCA)
    assert resultado.status == "ok" and "navegador" not in resultado.dados
    assert pelo_portal == ["https://exemplo.com"]


def test_navegador_nao_configurado_e_erro_que_diz_o_que_ha(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    executor = _executor(
        tmp_path,
        auditoria,
        navegadores=AbridorDeNavegador(
            navegadores={"brave": "/x/brave"}, principal="brave", lancar=lambda *a, **k: 0
        ),
    )
    resultado = executor.executar(
        "sites.open", {"url": "https://exemplo.com", "navegador": "opera"}, cancelado=NUNCA
    )
    assert resultado.status == "erro" and "brave" in resultado.motivo


def test_a_url_chega_ao_navegador_como_um_argumento_so(
    tmp_path: Path, auditoria: LogDeAuditoria, instalados: tuple[Path, Path]
) -> None:
    _, bins = instalados
    lancados: list[tuple[str, ...]] = []
    executor = _executor(
        tmp_path,
        auditoria,
        navegadores=AbridorDeNavegador(
            navegadores={"brave": f"{bins}/brave-stable"},
            principal="brave",
            lancar=_anotando(lancados),
        ),
    )
    # `--` e `;` dentro da URL são texto da URL, não opção nem comando.
    executor.executar(
        "sites.open", {"url": "https://exemplo.com/?a=1;--incognito"}, cancelado=NUNCA
    )
    assert lancados == [(f"{bins}/brave-stable", "https://exemplo.com/?a=1;--incognito")]
    assert Path(lancados[0][0]).is_absolute()


def test_aberto_e_sem_vir_para_a_frente_o_kwin_traz_a_janela_dele(
    instalados: tuple[Path, Path],
) -> None:
    """No Wayland do KDE o navegador não pega o foco sozinho: a extensão diz `visivel: false` e
    o «abre o Brave» parecia falhar (dono, 2026-10-21). O gerenciador de janelas traz a janela
    que mostra a aba atual — e nada é lançado."""
    _, bins = instalados
    lancados: list[tuple[str, ...]] = []
    pedidos: list[tuple[str, str]] = []

    def focar(familia: str, titulo: str) -> bool:
        pedidos.append((familia, titulo))
        return True

    abridor = AbridorDeNavegador(
        navegadores={"brave": f"{bins}/brave-stable"},
        principal="brave",
        lancar=_anotando(lancados),
        mostrar_aberto=lambda _f: {"tab_id": 7, "titulo": "YouTube", "visivel": False},
        focar_janela=focar,
    )

    aberto = abridor.abrir_sozinho()

    assert aberto == NavegadorAberto("brave", None, ja_aberto=True, visivel=True)
    assert pedidos == [("brave", "YouTube")] and lancados == []


def test_aberto_sem_extensao_o_kwin_traz_a_janela_e_nada_e_lancado(
    instalados: tuple[Path, Path],
) -> None:
    _, bins = instalados
    lancados: list[tuple[str, ...]] = []
    abridor = AbridorDeNavegador(
        navegadores={"brave": f"{bins}/brave-stable"},
        principal="brave",
        lancar=_anotando(lancados),
        mostrar_aberto=lambda _f: None,  # sem extensão conectada
        em_execucao=lambda _f: 4242,
        focar_janela=lambda _f, _t: True,
    )

    assert abridor.abrir_sozinho() == NavegadorAberto("brave", None, ja_aberto=True, visivel=True)
    assert lancados == []
