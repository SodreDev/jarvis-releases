"""Abrir um aplicativo que o dono autorizou — sem shell e sem argumento vindo do modelo (SPEC §5.6).

Pedido do dono (2026-10-17): executar **não** é o modelo montando comando; é uma tool tipada
com parâmetro nomeado, resolvida pelo código. Aqui o modelo diz só um **nome** ("o Dolphin",
"navegador"); o código resolve esse nome contra um **registro** montado dos `.desktop` do sistema
(spec freedesktop Desktop Entry) e filtrado pela lista que o dono autorizou na configuração. O
que roda é o `Exec` daquele arquivo, com os códigos de campo (`%f`, `%U`…) retirados — nenhum
caractere do pedido chega ao `argv`.

**A única exceção à varredura de shell do executor** (`tests/unit/processos/test_sem_shell.py`)
mora neste arquivo e é nomeada lá: `os.posix_spawn`, com `argv` em lista, sem shell, com ambiente
saneado (sem chave de API nenhuma) e numa sessão própria (`setsid`). `Exec` que começa por shell
(`sh -c`, `bash`…) ou por elevação (`sudo`, `pkexec`) é recusado ao montar o registro.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final, cast

from jarvis.apps.resolvedor import RepositorioDeAliases, Resolucao, ResolvedorDeApps

PASTAS_DE_APLICATIVOS: Final[tuple[str, ...]] = (
    "~/.local/share/applications",
    "~/.local/share/flatpak/exports/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/usr/local/share/applications",
    "/usr/share/applications",
)
"""Na ordem da precedência do XDG: o do usuário vence o do sistema com o mesmo id."""
CODIGOS_DE_CAMPO: Final = frozenset(
    {"%f", "%F", "%u", "%U", "%i", "%c", "%k", "%d", "%D", "%n", "%N", "%v", "%m"}
)
INTERPRETADORES_RECUSADOS: Final = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "fish",
        "ksh",
        "csh",
        "tcsh",
        "sudo",
        "pkexec",
        "su",
        "doas",
        "run0",
    }
)
VARIAVEIS_DO_AMBIENTE: Final = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "XDG_DATA_DIRS",
    "XDG_CONFIG_DIRS",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
)
"""O que o app precisa para abrir na sessão do dono — e só isso: nada de `GROQ_API_KEY` & cia."""


class AppRecusado(LookupError):
    """O nome não resolve para um app autorizado. A mensagem diz o que existe."""


@dataclass(frozen=True, slots=True)
class App:
    id: str
    """O nome do arquivo sem `.desktop` (ex.: `org.kde.dolphin`)."""
    nome: str
    nomes: tuple[str, ...]
    """Nome, nome em pt e o id: tudo o que o dono pode dizer para chamá-lo."""
    argv: tuple[str, ...]
    arquivo: Path
    sem_exibicao: bool = False
    """`NoDisplay=true`: serviço, painel de configuração, handler — não é um app para abrir."""
    categorias: tuple[str, ...] = ()
    esquemas: tuple[str, ...] = ()
    """Os `x-scheme-handler/…` do `MimeType`: `https` é o que faz dele um navegador."""
    generico: str = ""
    """`GenericName` do desktop entry; serve para buscar, não para montar argv."""
    keywords: tuple[str, ...] = ()
    """`Keywords` do desktop entry; recupera candidatos, mas não é autorização por si só."""
    exec_nome: str = ""
    """Nome-base do executável já validado no `Exec`, para a fala "code"/"discord"."""


def _sem_acento(texto: str) -> str:
    return (
        "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
        .casefold()
        .strip()
    )


def dividir_exec(texto: str) -> list[str]:
    """O `Exec` em argumentos, com as aspas da spec Desktop Entry — e nada de shell (sem `shlex`,
    proibido aqui: a regra de aspas da spec é menor e é essa que vale)."""
    argumentos: list[str] = []
    atual: list[str] = []
    entre_aspas = False
    tem = False
    i = 0
    while i < len(texto):
        c = texto[i]
        if entre_aspas:
            if c == "\\" and i + 1 < len(texto) and texto[i + 1] in '"`$\\':
                atual.append(texto[i + 1])
                i += 2
                continue
            if c == '"':
                entre_aspas = False
            else:
                atual.append(c)
        elif c == '"':
            entre_aspas, tem = True, True
        elif c.isspace():
            if atual or tem:
                argumentos.append("".join(atual))
                atual, tem = [], False
        else:
            atual.append(c)
        i += 1
    if entre_aspas:
        raise ValueError("aspas sem fechar no Exec")
    if atual or tem:
        argumentos.append("".join(atual))
    return argumentos


def ler_desktop(arquivo: Path) -> App | None:
    """Um `.desktop` de aplicativo visível e com `Exec` aceitável, ou `None`."""
    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    secao = ""
    campos: dict[str, str] = {}
    for linha in linhas:
        linha = linha.strip()
        if linha.startswith("[") and linha.endswith("]"):
            secao = linha[1:-1]
            continue
        if secao == "Desktop Entry" and "=" in linha and not linha.startswith("#"):
            chave, valor = linha.split("=", 1)
            campos.setdefault(chave.strip(), valor.strip())
    if campos.get("Type") != "Application" or campos.get("Hidden") == "true":
        return None
    try:
        argv = [a for a in dividir_exec(campos.get("Exec", "")) if a not in CODIGOS_DE_CAMPO]
    except ValueError:
        return None
    if not argv or any("%" in a for a in argv):
        return None
    if Path(argv[0]).name in INTERPRETADORES_RECUSADOS:
        return None
    identificador = arquivo.name.removesuffix(".desktop")
    nome = campos.get("Name", identificador)
    generico = campos.get("GenericName[pt_BR]", campos.get("GenericName[pt]", "")) or campos.get(
        "GenericName", ""
    )
    keywords = tuple(
        dict.fromkeys(
            palavra
            for chave in ("Keywords[pt_BR]", "Keywords[pt]", "Keywords")
            for palavra in campos.get(chave, "").split(";")
            if palavra
        )
    )
    exec_nome = Path(argv[0]).name
    nomes = tuple(
        dict.fromkeys(
            n
            for n in (
                nome,
                campos.get("Name[pt_BR]", ""),
                campos.get("Name[pt]", ""),
                generico,
                identificador,
                exec_nome,
            )
            if n
        )
    )
    return App(
        id=identificador,
        nome=nome,
        nomes=nomes,
        argv=tuple(argv),
        arquivo=arquivo,
        sem_exibicao=campos.get("NoDisplay") == "true",
        categorias=tuple(c for c in campos.get("Categories", "").split(";") if c),
        esquemas=tuple(
            m.removeprefix("x-scheme-handler/")
            for m in campos.get("MimeType", "").split(";")
            if m.startswith("x-scheme-handler/")
        ),
        generico=generico,
        keywords=keywords,
        exec_nome=exec_nome,
    )


def app_de_binario(caminho: str) -> App | None:
    """Um binário escolhido à mão vira um app com o nome do arquivo; nada do que o modelo disser
    chega ao `argv`. Recusa o que não é executável, e os interpretadores/elevadores."""
    arquivo = Path(caminho).expanduser()
    if not arquivo.is_absolute() or not arquivo.is_file() or not os.access(arquivo, os.X_OK):
        return None
    if arquivo.name in INTERPRETADORES_RECUSADOS:
        return None
    return App(
        id=f"caminho:{arquivo}",
        nome=arquivo.name,
        nomes=(arquivo.name,),
        argv=(str(arquivo),),
        arquivo=arquivo,
        exec_nome=arquivo.name,
    )


def app_de_caminho(caminho: str) -> App | None:
    """O que o dono apontou à mão: um `.desktop` (lido como os do sistema) ou um binário."""
    arquivo = Path(caminho).expanduser()
    if arquivo.suffix == ".desktop":
        return ler_desktop(arquivo) if arquivo.is_absolute() else None
    return app_de_binario(caminho)


def listar_apps(*, pastas: Sequence[str] = PASTAS_DE_APLICATIVOS) -> tuple[App, ...]:
    """Os aplicativos instalados que dá para abrir, por nome — é a lista que a tela mostra.

    Fora ficam os `NoDisplay` e os que são só painel de configuração do KDE/GNOME (categoria
    `Settings`): nenhum dono quer marcar `kcm_clock` para o Jarvis abrir."""
    encontrados: dict[str, App] = {}
    for pasta in pastas:
        base = Path(pasta).expanduser()
        if not base.is_dir():
            continue
        for arquivo in sorted(base.glob("*.desktop")):
            app = ler_desktop(arquivo)
            if app is not None and app.id not in encontrados:
                encontrados[app.id] = app
    visiveis = [
        a
        for a in encontrados.values()
        if not a.sem_exibicao
        and "Settings" not in a.categorias
        and "Screensaver" not in a.categorias
    ]
    return tuple(sorted(visiveis, key=lambda a: _sem_acento(a.nome)))


def listar_binarios_do_path(*, ambiente: Mapping[str, str] | None = None) -> tuple[App, ...]:
    """Binários instalados no ``PATH`` como rótulos de catálogo, sem executá-los.

    Eles não viram autorizados automaticamente: para abrir um deles o dono ainda o escolhe em
    ``apps_extras``. A coleta existe para a descoberta/hotwords e para não precisar de apelido
    manual quando um app não instala desktop entry.
    """
    fonte = os.environ if ambiente is None else ambiente
    achados: dict[str, App] = {}
    for entrada in fonte.get("PATH", "").split(os.pathsep):
        pasta = Path(entrada)
        if not entrada or not pasta.is_dir():
            continue
        try:
            arquivos = sorted(pasta.iterdir(), key=lambda arquivo: arquivo.name.casefold())
        except OSError:
            continue
        for arquivo in arquivos:
            app = app_de_binario(str(arquivo))
            if app is not None and app.nome not in achados:
                achados[app.nome] = app
    return tuple(achados.values())


@dataclass(frozen=True, slots=True)
class RegistroDeApps:
    autorizados: Mapping[str, App]
    instalados: frozenset[str]
    """Ids encontrados no sistema, autorizados ou não — para a sugestão dizer o que falta."""
    catalogo: Mapping[str, App] = field(default_factory=dict)
    """Desktop entries e, quando pedido, binários do PATH; não implica autorização."""
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    repositorio_de_aliases: RepositorioDeAliases | None = None

    @classmethod
    def montar(
        cls,
        autorizados: Iterable[str],
        *,
        pastas: Sequence[str] = PASTAS_DE_APLICATIVOS,
        extras: Iterable[str] = (),
        incluir_binarios_do_path: bool = False,
        ambiente: Mapping[str, str] | None = None,
        repositorio_de_aliases: RepositorioDeAliases | None = None,
    ) -> RegistroDeApps:
        encontrados: dict[str, App] = {}
        for pasta in pastas:
            base = Path(pasta).expanduser()
            if not base.is_dir():
                continue
            for arquivo in sorted(base.glob("*.desktop")):
                app = ler_desktop(arquivo)
                if app is not None and app.id not in encontrados:
                    encontrados[app.id] = app
        if incluir_binarios_do_path:
            for app in listar_binarios_do_path(ambiente=ambiente):
                encontrados.setdefault(app.id, app)
        pedidos = {a.removesuffix(".desktop") for a in autorizados}
        liberados = {i: encontrados[i] for i in sorted(pedidos) if i in encontrados}
        for caminho in extras:
            escolhido = app_de_caminho(caminho)
            if escolhido is not None:
                liberados.setdefault(escolhido.id, escolhido)
                encontrados.setdefault(escolhido.id, escolhido)
        repositorio = repositorio_de_aliases or RepositorioDeAliases.padrao(ambiente)
        aliases = repositorio.carregar()
        return cls(
            autorizados=liberados,
            instalados=frozenset(encontrados),
            catalogo=encontrados,
            aliases=aliases,
            repositorio_de_aliases=repositorio,
        )

    def resolver_detalhado(self, nome: str) -> Resolucao:
        return ResolvedorDeApps(self.autorizados.values(), aliases=self.aliases).resolver(nome)

    def resolver(self, nome: str) -> App:
        """O app autorizado que o dono chamou por este nome — exato, ou o único que começa
        assim. Fora disso, recusa dizendo os parecidos."""
        resultado = self.resolver_detalhado(nome)
        if resultado.estado == "encontrado" and resultado.app is not None:
            # O índice foi construído logo acima só com ``self.autorizados.values()``, que são
            # Apps. O protocolo do resolvedor evita acoplamento circular; aqui recuperamos o
            # tipo concreto exigido pelo lançador.
            return cast(App, resultado.app)
        if resultado.estado == "ambiguo":
            raise AppRecusado(
                "não abri por ambiguidade: " + resultado.pergunta + " Diga o nome completo."
            )
        raise AppRecusado(self._sugestao(nome, _sem_acento(nome)))

    def com_correcao(self, fala: str, app_id: str) -> RegistroDeApps:
        """Persiste uma correção explícita do dono e devolve registro renovado.

        Só aceita um id já autorizado: uma frase parecida nunca amplia o alcance do Jarvis.
        """
        if app_id not in self.autorizados:
            raise AppRecusado("a correção aponta para aplicativo não autorizado")
        if self.repositorio_de_aliases is None:
            raise AppRecusado("não há repositório de aliases configurado")
        self.repositorio_de_aliases.aprender(fala, app_id)
        return replace(self, aliases=self.repositorio_de_aliases.carregar())

    def _sugestao(self, nome: str, alvo: str) -> str:
        if not self.autorizados:
            return (
                f"{nome!r} não está no registro: nenhum aplicativo está autorizado ainda "
                "(apps_autorizados na configuração)"
            )
        pontuados = sorted(
            self.autorizados.values(),
            key=lambda a: (
                -max(SequenceMatcher(None, alvo, _sem_acento(n)).ratio() for n in a.nomes)
            ),
        )
        parecidos = ", ".join(a.nome for a in pontuados[:3])
        return f"{nome!r} não está entre os aplicativos autorizados. Parecidos: {parecidos}"


def ambiente_saneado(origem: Mapping[str, str] | None = None) -> dict[str, str]:
    fonte = os.environ if origem is None else origem
    return {k: fonte[k] for k in VARIAVEIS_DO_AMBIENTE if k in fonte}


def lancar(app: App, *, ambiente: Mapping[str, str] | None = None) -> int:
    """Abre o app numa sessão própria e devolve o pid. Quem espera o filho é uma linha à parte,
    para não sobrar processo zumbi; o Jarvis não fica preso a ele."""
    if sys.platform == "win32":  # pragma: no cover — Menu Iniciar/AppX ainda não implementado
        raise AppRecusado("abrir aplicativo no Windows ainda não foi implementado")
    executavel = app.argv[0] if Path(app.argv[0]).is_absolute() else shutil.which(app.argv[0])
    if executavel is None:
        raise AppRecusado(f"{app.nome}: o executável {app.argv[0]!r} não está no PATH")
    return _separar(executavel, app.argv, ambiente, nome=f"app-{app.id}")


def lancar_argv(argv: Sequence[str], *, ambiente: Mapping[str, str] | None = None) -> int:
    """O mesmo `lancar`, para quem já tem o `argv` montado pelo código (o navegador do dono +
    uma URL validada). Nada aqui vem do modelo além da URL, que é um único elemento do `argv` e
    já passou por `validar_url` (só http/https)."""
    if sys.platform == "win32":  # pragma: no cover
        raise AppRecusado("abrir programa no Windows ainda não foi implementado")
    executavel = argv[0] if Path(argv[0]).is_absolute() else shutil.which(argv[0])
    if executavel is None:
        raise AppRecusado(f"o executável {argv[0]!r} não está no PATH")
    return _separar(executavel, argv, ambiente, nome="programa-aberto")


def _separar(
    executavel: str, argv: Sequence[str], ambiente: Mapping[str, str] | None, *, nome: str
) -> int:
    """Sobe o programa sem shell, em sessão própria (`start_new_session` = `setsid` no filho), sem
    ligação com o terminal do Jarvis. Foi `os.posix_spawn(setsid=True)`, que nem toda plataforma
    ou build do Python tem (`NotImplementedError: setsid unavailable`, achado do dono em
    2026-10-17); `Popen` com `start_new_session` é o equivalente portátil."""
    try:
        filho = subprocess.Popen(  # noqa: S603 — argv sem shell; executável resolvido acima
            [executavel, *argv[1:]],
            executable=executavel,
            env=ambiente_saneado(ambiente),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as erro:
        raise AppRecusado(f"não consegui abrir {Path(executavel).name}: {erro}") from None
    threading.Thread(target=filho.wait, daemon=True, name=nome).start()
    return filho.pid
