"""Instala (e remove) o manifesto do host nativo nos lugares onde Firefox e Chromium o procuram.

O release traz o host (`jarvis-native-host`) e os modelos de manifesto (`extensao/host/*.json`, com
o marcador `__JARVIS_NATIVE_HOST_ABSOLUTO__` no `path`). O navegador exige **caminho absoluto** no
Linux, então alguém tem de trocar o marcador:

- `.deb` e `.rpm`: o **empacotador** troca por `/usr/bin/jarvis-native-host` e instala nos caminhos
  de sistema (`destinos_do_sistema`);
- AppImage, ou instalação à mão: o **dono** roda `jarvis-native-host --instalar`, que grava nos
  caminhos do usuário (`destinos_do_usuario`) — nunca em perfil de navegador, só no diretório de
  manifestos que a documentação de cada navegador define.

Caminhos (acesso em 2026-10-18): Chrome e Chromium em
<https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging>, Firefox em
<https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests>.

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
    return (
        Destino("firefox", "firefox", home / ".mozilla" / "native-messaging-hosts"),
        Destino("chrome", "chrome", home / ".config" / "google-chrome" / "NativeMessagingHosts"),
        Destino("chromium", "chrome", home / ".config" / "chromium" / "NativeMessagingHosts"),
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


def escrever_stub_do_appimage(home: Path, appimage: str) -> Path:
    """AppImage: o navegador precisa de um caminho fixo, e o ponto de montagem não é.
    O stub chama o próprio AppImage no modo host nativo (`AppRun --native-host`)."""
    if not PurePosixPath(appimage).is_absolute():
        raise InstalacaoRecusada(f"caminho do AppImage não é absoluto: {appimage!r}")
    stub = home / STUB_NO_USUARIO
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        "#!/bin/sh\n"
        "# Gerado por `jarvis-native-host --instalar`: abre o AppImage no modo host nativo.\n"
        f'exec {shlex.quote(appimage)} --native-host "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def copiar_extensao(home: Path, origem: Path | None = None) -> Path:
    """Uma cópia da extensão em lugar fixo, para «Carregar sem compactação» (num AppImage, a
    pasta original mora num ponto de montagem que some)."""
    fonte = origem if origem is not None else caminho_de_dados("extensao")
    destino = home / EXTENSAO_NO_USUARIO
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fonte, destino, dirs_exist_ok=True)
    return destino


def principal(
    argumentos: Sequence[str],
    ambiente: Mapping[str, str],
    home: Path,
    *,
    ler_modelo: Callable[[str], str] = modelo_do_release,
    onde_esta_o_executavel: Callable[[str], str | None] = shutil.which,
    saida: Callable[[str], object] = print,
) -> int:
    """`--instalar` grava os manifestos do usuário; `--remover` apaga. Devolve o código de saída."""
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
        else:
            achado = onde_esta_o_executavel(NOME_DO_EXECUTAVEL)
            if not achado:
                saida(f"{NOME_DO_EXECUTAVEL} não está no PATH: instale o pacote ou use o AppImage")
                return 1
            executavel = str(Path(achado).resolve())
            extensao = caminho_de_dados("extensao")
        escritos = instalar(destinos, executavel, ler_modelo)
    except (InstalacaoRecusada, OSError) as erro:
        saida(f"não instalei: {erro}")
        return 1
    saida(f"host nativo: {executavel}")
    for arquivo in escritos:
        saida(f"manifesto: {arquivo}")
    saida(f"extensão para carregar no navegador: {extensao}")
    return 0


def main() -> int:  # pragma: no cover — liga o processo real
    return principal(sys.argv[1:], os.environ, Path.home())
