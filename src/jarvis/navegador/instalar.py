"""Instala (e remove) o manifesto do host nativo nos lugares onde Firefox e Chromium o procuram.

O release traz o host (`jarvis-native-host`) e os modelos de manifesto (`extensao/host/*.json`, com
o marcador `__JARVIS_NATIVE_HOST_ABSOLUTO__` no `path`). O navegador exige **caminho absoluto** no
Linux, então alguém tem de trocar o marcador:

- `.deb` e `.rpm`: o **empacotador** troca por `/usr/bin/jarvis-native-host` e instala nos caminhos
  de sistema (`destinos_do_sistema`);
- AppImage, ou instalação à mão: o **dono** roda `jarvis-native-host --instalar`, que grava nos
  caminhos do usuário (`destinos_do_usuario`) — nunca em perfil de navegador, só no diretório de
  manifestos que a documentação de cada navegador define;
- repositório clonado (desenvolvimento, sem release): `uv run jarvis-native-host --instalar` faz o
  mesmo que o AppImage, mas o stub lança o host **deste** repositório pelo Python do `uv`.

Caminhos (acesso em 2026-10-18): Chrome e Chromium em
<https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging>, Firefox em
<https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests>. Nos
derivados do Chromium o manifesto do usuário mora em `<pasta de dados>/NativeMessagingHosts`
(conferido no Chromium 155 em contêiner, 2026-10-19: com outro `--user-data-dir`, a pasta vai junto)
— por isso o Brave, o Edge e o Vivaldi têm a sua, e o Brave do dono não achava o host na do Chrome.

Navegador em **Flatpak** não serve: o Native Messaging não lança programa fora da caixa de areia
(o Firefox depende de um portal que o xdg-desktop-portal não publica; acesso em 2026-10-19,
<https://firefox-source-docs.mozilla.org/toolkit/components/extensions/webextensions/native-messaging-portal-design.html>).

Instalar o manifesto **não instala a extensão**: ela é carregada pelo dono no navegador (ver
`docs/COMO-TESTAR.md`). Sem os dois, o host não é lançado e nada acontece.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from jarvis.dados import caminho as caminho_de_dados
from jarvis.dados import raiz_do_repositorio
from jarvis.navegador.protocolo import NOME_DO_HOST

MARCADOR: Final = "__JARVIS_NATIVE_HOST_ABSOLUTO__"
ARQUIVO: Final = f"{NOME_DO_HOST}.json"
EXECUTAVEL_DO_PACOTE: Final = "/usr/bin/jarvis-native-host"
NOME_DO_EXECUTAVEL: Final = "jarvis-native-host"
EXTENSAO_NO_USUARIO: Final = Path(".local/share/jarvis/extensao")
STUB_NO_USUARIO: Final = Path(".local/share/jarvis/bin") / NOME_DO_EXECUTAVEL


@dataclass(frozen=True, slots=True)
class Destino:
    navegador: str
    modelo: str
    """`chrome` (Chrome e Chromium: `allowed_origins`) ou `firefox` (`allowed_extensions`)."""
    pasta: Path

    @property
    def arquivo(self) -> Path:
        return self.pasta / ARQUIVO


def destinos_do_usuario(home: Path) -> tuple[Destino, ...]:
    """Um por navegador. Gravar o de um navegador que não está instalado é inofensivo (um JSON
    numa pasta que ele leria) e vale se ele for instalado depois; `--remover` apaga todos."""
    config = home / ".config"
    return (
        Destino("firefox", "firefox", home / ".mozilla" / "native-messaging-hosts"),
        Destino("chrome", "chrome", config / "google-chrome" / "NativeMessagingHosts"),
        Destino("chromium", "chrome", config / "chromium" / "NativeMessagingHosts"),
        Destino(
            "brave", "chrome", config / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts"
        ),
        Destino("edge", "chrome", config / "microsoft-edge" / "NativeMessagingHosts"),
        Destino("vivaldi", "chrome", config / "vivaldi" / "NativeMessagingHosts"),
    )


def destinos_do_sistema(raiz: Path = Path("/")) -> tuple[Destino, ...]:
    """Onde o `.deb`/`.rpm` instala, sob `raiz` (a árvore do pacote, ou `/` no sistema)."""
    return (
        Destino("chrome", "chrome", raiz / "etc/opt/chrome/native-messaging-hosts"),
        Destino("chromium", "chrome", raiz / "etc/chromium/native-messaging-hosts"),
        Destino("firefox", "firefox", raiz / "usr/lib/mozilla/native-messaging-hosts"),
        Destino("firefox64", "firefox", raiz / "usr/lib64/mozilla/native-messaging-hosts"),
    )


class InstalacaoRecusada(ValueError):
    """O modelo ou o executável não servem (caminho relativo, marcador ausente, JSON torto)."""


def modelo_do_release(modelo: str, *, base: Path | None = None) -> str:
    pasta = base if base is not None else caminho_de_dados("extensao/host")
    return (pasta / f"{NOME_DO_HOST}.{modelo}.json").read_text(encoding="utf-8")


def manifesto_pronto(texto_do_modelo: str, executavel: str) -> str:
    """O manifesto com o `path` real. Só troca o marcador: qualquer outra coisa no `path` é erro."""
    if not PurePosixPath(executavel).is_absolute():
        raise InstalacaoRecusada(f"o navegador exige caminho absoluto no Linux: {executavel!r}")
    try:
        dados = json.loads(texto_do_modelo)
    except json.JSONDecodeError as erro:
        raise InstalacaoRecusada(f"modelo de manifesto que não é JSON: {erro}") from None
    if not isinstance(dados, dict) or dados.get("path") != MARCADOR:
        raise InstalacaoRecusada(f"o modelo não tem o marcador {MARCADOR} no path")
    if dados.get("type") != "stdio" or dados.get("name") != NOME_DO_HOST:
        raise InstalacaoRecusada("o modelo não é do host stdio do Jarvis")
    dados["path"] = executavel
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"


def instalar(
    destinos: Sequence[Destino],
    executavel: str,
    ler_modelo: Callable[[str], str] = modelo_do_release,
) -> list[Path]:
    escritos: list[Path] = []
    for destino in destinos:
        texto = manifesto_pronto(ler_modelo(destino.modelo), executavel)
        destino.pasta.mkdir(parents=True, exist_ok=True)
        destino.arquivo.write_text(texto, encoding="utf-8")
        destino.arquivo.chmod(0o644)
        escritos.append(destino.arquivo)
    return escritos


def remover(destinos: Sequence[Destino]) -> list[Path]:
    """Apaga **só** o arquivo do Jarvis em cada pasta; pasta e vizinhos ficam como estavam."""
    apagados: list[Path] = []
    for destino in destinos:
        if destino.arquivo.is_file():
            destino.arquivo.unlink()
            apagados.append(destino.arquivo)
    return apagados


def _escrever_stub(home: Path, comentario: str, comando: str) -> Path:
    """O caminho fixo que os manifestos apontam. Trocar de AppImage para o repositório (ou o
    contrário) reescreve só este arquivo; os manifestos continuam valendo."""
    stub = home / STUB_NO_USUARIO
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(f'#!/bin/sh\n# {comentario}\nexec {comando} "$@"\n', encoding="utf-8")
    stub.chmod(0o755)
    return stub


def escrever_stub_do_appimage(home: Path, appimage: str) -> Path:
    """AppImage: o navegador precisa de um caminho fixo, e o ponto de montagem não é.
    O stub chama o próprio AppImage no modo host nativo (`AppRun --native-host`)."""
    if not PurePosixPath(appimage).is_absolute():
        raise InstalacaoRecusada(f"caminho do AppImage não é absoluto: {appimage!r}")
    return _escrever_stub(
        home,
        "Gerado por `jarvis-native-host --instalar`: abre o AppImage no modo host nativo.",
        f"{shlex.quote(appimage)} --native-host",
    )


def escrever_stub_de_desenvolvimento(home: Path, python: str) -> Path:
    """Repositório clonado: o navegador lança o host **deste** código pelo Python do ambiente do
    `uv` (`.venv/bin/python`). `-I` como no pacote: sem `PYTHONPATH`, sem a pasta atual no
    caminho — o navegador passa o ambiente da sessão, e ele não decide o que o host importa."""
    if not PurePosixPath(python).is_absolute():
        raise InstalacaoRecusada(f"caminho do Python não é absoluto: {python!r}")
    return _escrever_stub(
        home,
        "Gerado por `uv run jarvis-native-host --instalar` (repositório): o host deste código.",
        f"{shlex.quote(python)} -I -m jarvis.navegador.host",
    )


def copiar_extensao(home: Path, origem: Path | None = None) -> Path:
    """Uma cópia da extensão em lugar fixo, para «Carregar sem compactação» (num AppImage, a
    pasta original mora num ponto de montagem que some)."""
    fonte = origem if origem is not None else caminho_de_dados("extensao")
    destino = home / EXTENSAO_NO_USUARIO
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fonte, destino, dirs_exist_ok=True)
    return destino


FLATPAKS: Final[dict[str, str]] = {
    "org.mozilla.firefox": "Firefox",
    "org.chromium.Chromium": "Chromium",
    "com.google.Chrome": "Google Chrome",
    "com.brave.Browser": "Brave",
    "com.microsoft.Edge": "Microsoft Edge",
    "com.vivaldi.Vivaldi": "Vivaldi",
}
"""Navegadores em Flatpak que o instalador reconhece, para avisar que a ponte não funciona neles."""


def navegadores_em_flatpak(home: Path) -> tuple[str, ...]:
    """Os que têm pasta em `~/.var/app` (já abriram ao menos uma vez como Flatpak)."""
    return tuple(nome for app, nome in FLATPAKS.items() if (home / ".var" / "app" / app).is_dir())


def proximos_passos(extensao: Path, home: Path) -> list[str]:
    """O que o dono faz no navegador depois do `--instalar` — o código não toca no navegador."""
    passos = [
        "próximos passos (no navegador, uma vez):",
        "  1. Brave, Chrome, Chromium, Edge ou Vivaldi: abra brave://extensions (ou chrome://"
        "extensions), ligue o «Modo do desenvolvedor», clique em «Carregar sem compactação» e "
        f"escolha {extensao}. Se ela já estava carregada, clique em «Recarregar» (↻) no cartão "
        "dela: o navegador só procura o host de novo quando a extensão reinicia.",
        "  2. Firefox: about:debugging#/runtime/this-firefox → «Carregar extensão temporária…» → "
        f"{extensao / 'manifest.json'} (o Firefox de release só aceita extensão sem assinatura "
        "como temporária: some ao fechar).",
        "  3. Abas que já estavam abertas antes de carregar a extensão: recarregue a aba (F5).",
        "  4. Ligue o controle no Jarvis: janela → Acesso → Navegadores → «deixar o Jarvis "
        "controlar as abas» (ou navegador_controlado = true no jarvis-voz.toml).",
        "  5. Confira: `uv run jarvis-voz --diagnostico` (seção navegador) ou pergunte ao Jarvis "
        "«a extensão do navegador está conectada?».",
    ]
    em_flatpak = navegadores_em_flatpak(home)
    if em_flatpak:
        passos.append(
            f"atenção: {', '.join(em_flatpak)} em Flatpak não lança o host nativo fora da caixa de "
            "areia — use a versão do pacote do sistema (rpm/deb) desse navegador."
        )
    return passos


def principal(
    argumentos: Sequence[str],
    ambiente: Mapping[str, str],
    home: Path,
    *,
    ler_modelo: Callable[[str], str] = modelo_do_release,
    onde_esta_o_executavel: Callable[[str], str | None] = shutil.which,
    saida: Callable[[str], object] = print,
    repositorio: Path | None = None,
    python: str = sys.executable,
) -> int:
    """`--instalar` grava os manifestos do usuário; `--remover` apaga. Devolve o código de saída.

    Quem lança o host, em ordem: o AppImage (`$APPIMAGE`), o `repositorio` clonado (o Python que
    roda isto, `python`) ou o executável do pacote no PATH. O `main` passa o repositório só quando
    este código roda de dentro dele (`jarvis.dados.raiz_do_repositorio`)."""
    if list(argumentos) not in (["--instalar"], ["--remover"]):
        saida("uso: jarvis-native-host --instalar | --remover")
        return 2
    destinos = destinos_do_usuario(home)
    if argumentos[0] == "--remover":
        apagados = remover(destinos)
        saida(f"removidos {len(apagados)} manifesto(s): " + ", ".join(map(str, apagados)))
        return 0
    appimage = ambiente.get("APPIMAGE", "")
    try:
        if appimage:
            executavel = str(escrever_stub_do_appimage(home, appimage))
            extensao = copiar_extensao(home)
            origem = f"o AppImage {appimage}"
        elif repositorio is not None:
            executavel = str(escrever_stub_de_desenvolvimento(home, python))
            extensao = copiar_extensao(home, repositorio / "extensao")
            origem = f"o código de {repositorio}; rode de novo depois de mudar a extensão"
        else:
            achado = onde_esta_o_executavel(NOME_DO_EXECUTAVEL)
            if not achado:
                saida(f"{NOME_DO_EXECUTAVEL} não está no PATH: instale o pacote ou use o AppImage")
                return 1
            executavel = str(Path(achado).resolve())
            extensao = caminho_de_dados("extensao")
            origem = "o pacote instalado"
        escritos = instalar(destinos, executavel, ler_modelo)
    except (InstalacaoRecusada, OSError) as erro:
        saida(f"não instalei: {erro}")
        return 1
    saida(f"host nativo: {executavel} — lança {origem}")
    for arquivo in escritos:
        saida(f"manifesto: {arquivo}")
    saida(f"extensão para carregar no navegador: {extensao}")
    for linha in proximos_passos(extensao, home):
        saida(linha)
    return 0


def main() -> int:  # pragma: no cover — liga o processo real
    return principal(sys.argv[1:], os.environ, Path.home(), repositorio=raiz_do_repositorio())
