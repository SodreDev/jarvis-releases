"""Empacota o Jarvis em AppImage, `.deb` e `.rpm` — os três do **mesmo** AppDir (ADR-0020).

    uv run --frozen python tools/empacotar.py appdir      # monta a árvore instalável
    uv run --frozen python tools/empacotar.py appimage    # AppDir + appimagetool
    uv run --frozen python tools/empacotar.py deb         # AppDir + nfpm
    uv run --frozen python tools/empacotar.py rpm
    uv run --frozen python tools/empacotar.py tudo
    uv run --frozen python tools/empacotar.py verificar   # roda os três em contêiner

**Nada disto escreve no repositório.** Tudo mora em `/tmp/jarvis-dist` (ou no `--destino` que
você passar): artefato de build não é código, e misturar os dois é como um `dist/` esquecido
entra num commit.

**Um AppDir, três embalagens.** O que varia entre AppImage, `.deb` e `.rpm` é a casca; o
conteúdo é o mesmo: um Python relocável, as rodas do projeto, os dados (`licenses/`,
`schemas/`, `tabelas/`, `catalogo/`), os textos de licença obrigatórios e um lançador. Montar
três vezes seria manter três verdades.

**O que NÃO entra:** peso de modelo. A voz do piper (63,2 MB) e os modelos de ASR são baixados
no primeiro uso, com tamanho dito e sha256 conferido (`jarvis.voz.modelos`).

**Reprodutível de onde?** Da trava: as dependências saem de `uv.lock` por `uv export --frozen`,
e a versão do Python é fixa aqui. Duas execuções na mesma trava instalam as mesmas rodas.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

RAIZ: Final = Path(__file__).resolve().parent.parent
DESTINO_PADRAO: Final = Path("/tmp/jarvis-dist")  # noqa: S108 — fora do repositório, de propósito
VERSAO_PYTHON: Final = "3.12"
ID: Final = "dev.sodredev.Jarvis"
NOME: Final = "jarvis"
VERSAO: Final = "0.0.0"
GRUPOS: Final[tuple[str, ...]] = ("gui", "voz", "asr", "dispositivo")
"""O que vai dentro do pacote: a janela, a voz local, o ASR local e o dispositivo de áudio.

`edge` fica de fora de propósito — é extra LGPL de um motor barrado por padrão (ADR-0017), e
o que não é caminho de produto não é distribuído."""

DADOS: Final[tuple[str, ...]] = ("licenses", "schemas", "tabelas", "catalogo", "NOTICE", "LICENSE")
"""O que o produto lê em tempo de execução. `jarvis.dados` procura por aqui via JARVIS_DADOS."""

TEXTOS_DE_LICENCA: Final[tuple[str, ...]] = (
    "licenses/texto/LGPL-3.0.txt",
    "licenses/texto/GPL-3.0.txt",
    "licenses/texto/SecretStorage-BSD-3-Clause.txt",
    "LICENSE",
    "NOTICE",
)
"""Obrigação de redistribuição (ADR-0019): vão para `usr/share/licenses/jarvis` em todo pacote."""

APPIMAGETOOL: Final = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)
NFPM_VERSAO: Final = "2.48.0"
NFPM: Final = (
    f"https://github.com/goreleaser/nfpm/releases/download/v{NFPM_VERSAO}/"
    f"nfpm_{NFPM_VERSAO}_Linux_x86_64.tar.gz"
)

DEPENDENCIAS_DEB: Final[tuple[str, ...]] = (
    "libc6 (>= 2.28)",
    "libglib2.0-0t64 | libglib2.0-0",
    "libgssapi-krb5-2",
    "libgl1",
    "libegl1",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-keysyms1",
    "libxcb-shape0",
    "libfontconfig1",
    "libfreetype6",
    "libdbus-1-3",
)
DEPENDENCIAS_RPM: Final[tuple[str, ...]] = (
    "glib2",
    "krb5-libs",
    "mesa-libGL",
    "mesa-libEGL",
    "libxkbcommon",
    "libxkbcommon-x11",
    "xcb-util-cursor",
    "xcb-util-wm",
    "xcb-util-keysyms",
    "fontconfig",
    "freetype",
    "dbus-libs",
)
"""As bibliotecas do **sistema** que o Qt exige e que a roda não traz: o pacote as declara em
vez de descobrir na cara do dono. (No AppImage elas são requisito da máquina — está no
`COMO-TESTAR.md`, com o comando de instalação por distro.)"""

LANCADOR: Final = """#!/bin/sh
# Lançador do Jarvis. O mesmo script serve ao AppImage e à instalação em /usr: ele descobre a
# raiz a partir do próprio caminho, em vez de depender de onde foi instalado.
set -eu
AQUI=$(dirname "$(readlink -f "$0")")
RAIZ=$(dirname "$AQUI")
export JARVIS_DADOS="${JARVIS_DADOS:-$RAIZ/share/jarvis}"
exec "$RAIZ/lib/jarvis/python/bin/python3" -m jarvis.gui.principal "$@"
"""

APPRUN: Final = """#!/bin/sh
# AppRun do AppImage: o ponto de entrada que o runtime chama depois de montar a imagem.
set -eu
AQUI=$(dirname "$(readlink -f "$0")")
exec "$AQUI/usr/bin/jarvis" "$@"
"""


class Falhou(RuntimeError):
    """Uma etapa do empacotamento não deu certo. A mensagem diz qual e por quê."""


@dataclass(frozen=True, slots=True)
class Lugares:
    """Onde cada coisa é montada. Tudo pendurado no destino, nada no repositório."""

    destino: Path

    @property
    def appdir(self) -> Path:
        return self.destino / "AppDir"

    @property
    def usr(self) -> Path:
        return self.appdir / "usr"

    @property
    def python(self) -> Path:
        return self.usr / "lib" / "jarvis" / "python"

    @property
    def interpretador(self) -> Path:
        return self.python / "bin" / "python3"

    @property
    def ferramentas(self) -> Path:
        return self.destino / "ferramentas"

    @property
    def trabalho(self) -> Path:
        return self.destino / "trabalho"


def rodar(
    argv: Sequence[str], *, onde: Path | None = None, ambiente: dict[str, str] | None = None
) -> None:
    """Um processo com `argv` explícito — nada de shell (SPEC §4, CONTRIBUTING 6)."""
    print(f"  $ {' '.join(argv)}", flush=True)
    fim = subprocess.run(
        list(argv),
        cwd=str(onde or RAIZ),
        env={**os.environ, **(ambiente or {})},
        check=False,
    )
    if fim.returncode != 0:
        raise Falhou(f"saiu com {fim.returncode}: {' '.join(argv)}")


def baixar(url: str, destino: Path) -> Path:
    """Baixa uma ferramenta de build, uma vez. Já baixada, usa a que está lá."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        return destino
    print(f"  baixando {url}", flush=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    with urllib.request.urlopen(url, timeout=300) as resposta, parcial.open("wb") as saida:  # noqa: S310
        shutil.copyfileobj(resposta, saida)
    parcial.replace(destino)
    destino.chmod(0o755)
    return destino


def tamanho(caminho: Path) -> str:
    if caminho.is_file():
        return f"{caminho.stat().st_size / 1_000_000:.1f} MB"
    total = sum(f.stat().st_size for f in caminho.rglob("*") if f.is_file())
    return f"{total / 1_000_000:.1f} MB"


# --- AppDir ---------------------------------------------------------------------------------
def montar_appdir(lugares: Lugares, *, podar: bool = True) -> Path:
    """A árvore instalável: Python relocável + rodas da trava + dados + lançador."""
    appdir = lugares.appdir
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)
    lugares.trabalho.mkdir(parents=True, exist_ok=True)

    print("1/6 Python relocável", flush=True)
    pasta_python = lugares.trabalho / "python"
    if pasta_python.exists():
        shutil.rmtree(pasta_python)
    rodar(["uv", "python", "install", "--install-dir", str(pasta_python), VERSAO_PYTHON])
    instalado = next(pasta_python.glob("cpython-*"), None)
    if instalado is None:
        raise Falhou(f"o uv não deixou nenhum cpython em {pasta_python}")
    lugares.python.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(instalado, lugares.python, symlinks=True)
    # O `uv` marca as instalações dele como "externally managed" para ninguém instalar pacote
    # por cima da cópia **dele**. Esta cópia não é dele: é o runtime privado do aplicativo, e
    # é justamente nela que as rodas do produto entram.
    for marca in lugares.python.glob("lib/python*/EXTERNALLY-MANAGED"):
        marca.unlink()

    print("2/6 dependências da trava", flush=True)
    requisitos = lugares.trabalho / "requisitos.txt"
    argumentos = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"]
    for grupo in GRUPOS:
        argumentos += ["--group", grupo]
    argumentos += ["-o", str(requisitos)]
    rodar(argumentos)
    rodar(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(lugares.interpretador),
            "--no-cache",
            "-r",
            str(requisitos),
        ]
    )

    print("3/6 o próprio Jarvis", flush=True)
    rodar(["uv", "build", "--wheel", "--out-dir", str(lugares.trabalho / "roda")])
    roda = sorted((lugares.trabalho / "roda").glob("jarvis-*.whl"))[-1]
    rodar(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(lugares.interpretador),
            "--no-cache",
            "--no-deps",
            str(roda),
        ]
    )

    print("4/6 dados, licenças e ícones", flush=True)
    dados = lugares.usr / "share" / "jarvis"
    dados.mkdir(parents=True, exist_ok=True)
    for nome in DADOS:
        origem = RAIZ / nome
        if origem.is_dir():
            shutil.copytree(origem, dados / nome, dirs_exist_ok=True)
        else:
            shutil.copy2(origem, dados / nome)
    licencas = lugares.usr / "share" / "licenses" / "jarvis"
    licencas.mkdir(parents=True, exist_ok=True)
    for relativo in TEXTOS_DE_LICENCA:
        shutil.copy2(RAIZ / relativo, licencas / Path(relativo).name)

    sys.path.insert(0, str(RAIZ))
    from tools.icone import gerar  # importado aqui porque precisa do Qt do ambiente de build

    icones = lugares.usr / "share" / "icons" / "hicolor"
    gerar(RAIZ / "src" / "jarvis" / "gui" / "recursos" / "jarvis.svg", icones)
    escalavel = icones / "scalable" / "apps"
    escalavel.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        RAIZ / "src" / "jarvis" / "gui" / "recursos" / "jarvis.svg", escalavel / f"{ID}.svg"
    )

    atalho = RAIZ / "packaging" / "linux" / f"{ID}.desktop"
    aplicativos = lugares.usr / "share" / "applications"
    aplicativos.mkdir(parents=True, exist_ok=True)
    shutil.copy2(atalho, aplicativos / f"{ID}.desktop")
    shutil.copy2(atalho, appdir / f"{ID}.desktop")
    shutil.copy2(icones / "256x256" / "apps" / f"{ID}.png", appdir / f"{ID}.png")
    shutil.copy2(icones / "256x256" / "apps" / f"{ID}.png", appdir / ".DirIcon")

    print("5/6 lançador", flush=True)
    lancador = lugares.usr / "bin" / "jarvis"
    lancador.write_text(LANCADOR, encoding="utf-8")
    lancador.chmod(0o755)
    apprun = appdir / "AppRun"
    apprun.write_text(APPRUN, encoding="utf-8")
    apprun.chmod(0o755)

    print("6/6 poda e medição", flush=True)
    if podar:
        podados = podar_o_que_nao_e_usado(lugares)
        print(f"  podados {podados / 1_000_000:.1f} MB", flush=True)
    print(f"  AppDir: {tamanho(appdir)}", flush=True)
    return appdir


SOBRAS: Final[tuple[str, ...]] = (
    "**/__pycache__",
    "**/*.pyc",
    "usr/lib/jarvis/python/lib/python3.12/test",
    "usr/lib/jarvis/python/lib/python3.12/idlelib",
    "usr/lib/jarvis/python/lib/python3.12/tkinter",
    "usr/lib/jarvis/python/lib/python3.12/lib2to3",
    "usr/lib/jarvis/python/share/man",
    "**/site-packages/PySide6/Qt/translations",
    "**/site-packages/PySide6/assistant",
    "**/site-packages/PySide6/designer",
    "**/site-packages/PySide6/linguist",
    "**/site-packages/PySide6/doc",
    "**/site-packages/PySide6/include",
    "**/site-packages/PySide6/glue",
    "**/site-packages/PySide6/examples",
    "**/site-packages/PySide6/*.pyi",
    "**/site-packages/PySide6/typesystems",
    "**/site-packages/shiboken6_generator",
    "**/site-packages/pip",
    "**/site-packages/pip-*.dist-info",
)
"""O que sai do pacote, e por quê: cache de bytecode (nasce de novo), a suíte do próprio
Python, ferramentas de desenvolvimento do Qt (designer, linguist, assistant), documentação,
cabeçalhos C++, stubs de tipo e traduções do Qt — nada disso é executado pelo produto.

**Nenhum módulo do Qt é removido na lista acima**, e é de propósito: cortar `.so` por
adivinhação é como se descobre, na máquina do dono, que o `QtQuick` precisava de um que
parecia inútil. A poda é de peso morto declarado, e o contêiner de verificação roda a janela
inteira depois dela."""


def podar_o_que_nao_e_usado(lugares: Lugares) -> int:
    liberados = 0
    for padrao in SOBRAS:
        for alvo in lugares.appdir.glob(padrao):
            if not alvo.exists():
                continue
            peso = (
                alvo.stat().st_size
                if alvo.is_file()
                else sum(f.stat().st_size for f in alvo.rglob("*") if f.is_file())
            )
            if alvo.is_dir():
                shutil.rmtree(alvo)
            else:
                alvo.unlink()
            liberados += peso
    return liberados


# --- AppImage -------------------------------------------------------------------------------
def montar_appimage(lugares: Lugares) -> Path:
    ferramenta = baixar(APPIMAGETOOL, lugares.ferramentas / "appimagetool.AppImage")
    saida = lugares.destino / f"Jarvis-{VERSAO}-x86_64.AppImage"
    saida.unlink(missing_ok=True)
    rodar(
        [str(ferramenta), "--no-appstream", str(lugares.appdir), str(saida)],
        ambiente={"APPIMAGE_EXTRACT_AND_RUN": "1", "ARCH": "x86_64"},
    )
    print(f"  AppImage: {saida} ({tamanho(saida)})", flush=True)
    return saida


# --- deb e rpm ------------------------------------------------------------------------------
def nfpm(lugares: Lugares) -> Path:
    binario = lugares.ferramentas / "nfpm"
    if binario.exists():
        return binario
    tarball = baixar(NFPM, lugares.ferramentas / "nfpm.tar.gz")
    with tarfile.open(tarball) as arquivo:
        membro = arquivo.getmember("nfpm")
        arquivo.extract(membro, lugares.ferramentas, filter="data")
    binario.chmod(0o755)
    return binario


def receita(lugares: Lugares, formato: str) -> Path:
    """A receita do nfpm, escrita a partir do AppDir — uma por formato, do mesmo conteúdo."""
    dependencias = DEPENDENCIAS_DEB if formato == "deb" else DEPENDENCIAS_RPM
    linhas = [
        f'name: "{NOME}"',
        f'version: "{VERSAO}"',
        'arch: "amd64"' if formato == "deb" else 'arch: "x86_64"',
        'platform: "linux"',
        'section: "utils"',
        'maintainer: "SodreDev"',
        "description: |",
        "  Assistente pessoal de voz, local por padrão.",
        "  A nuvem só liga por escolha do dono, e o peso dos modelos é baixado no primeiro uso.",
        'vendor: "SodreDev"',
        'homepage: "https://github.com/SodreDev/jarvis"',
        'license: "Apache-2.0"',
        "depends:",
        *[f'  - "{d}"' for d in dependencias],
        "contents:",
        f'  - src: "{lugares.usr}/lib/jarvis"',
        '    dst: "/usr/lib/jarvis"',
        f'  - src: "{lugares.usr}/bin/jarvis"',
        '    dst: "/usr/bin/jarvis"',
        f'  - src: "{lugares.usr}/share/jarvis"',
        '    dst: "/usr/share/jarvis"',
        f'  - src: "{lugares.usr}/share/applications/{ID}.desktop"',
        f'    dst: "/usr/share/applications/{ID}.desktop"',
        f'  - src: "{lugares.usr}/share/icons/hicolor"',
        '    dst: "/usr/share/icons/hicolor"',
        f'  - src: "{lugares.usr}/share/licenses/jarvis"',
        '    dst: "/usr/share/licenses/jarvis"',
        # Sem `type: license` aqui: no rpm esse tipo é por **arquivo**, e apontá-lo para uma
        # pasta faz o nfpm parar com "is a directory". Os textos vão como conteúdo normal,
        # que é o que a obrigação da ADR-0019 pede — estar lá dentro, no caminho declarado.
    ]
    caminho = lugares.trabalho / f"nfpm-{formato}.yaml"
    caminho.write_text("\n".join(linha for linha in linhas if linha) + "\n", encoding="utf-8")
    return caminho


def montar_pacote(lugares: Lugares, formato: str) -> Path:
    ferramenta = nfpm(lugares)
    config = receita(lugares, formato)
    rodar(
        [
            str(ferramenta),
            "package",
            "--packager",
            formato,
            "--config",
            str(config),
            "--target",
            str(lugares.destino),
        ]
    )
    achados = sorted(lugares.destino.glob(f"*.{formato}"), key=lambda p: p.stat().st_mtime)
    if not achados:
        raise Falhou(f"o nfpm não deixou nenhum .{formato} em {lugares.destino}")
    print(f"  {formato}: {achados[-1]} ({tamanho(achados[-1])})", flush=True)
    return achados[-1]


# --- verificação em contêiner ----------------------------------------------------------------
QT_NO_DEBIAN: Final = (
    "libglib2.0-0t64 libgssapi-krb5-2 "
    "libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 "
    "libxcb-keysyms1 libxcb-shape0 libxcb-randr0 libxcb-render-util0 libxcb-xinerama0 "
    "libxcb-xkb1 libfontconfig1 libfreetype6 libdbus-1-3 fonts-dejavu-core"
)
QT_NO_FEDORA: Final = (
    "glib2 krb5-libs "
    "mesa-libGL mesa-libEGL libxkbcommon libxkbcommon-x11 xcb-util-cursor xcb-util-wm "
    "xcb-util-keysyms xcb-util-renderutil fontconfig freetype dbus-libs dejavu-sans-fonts"
)


def em_container(
    nome: str, imagem: str, roteiro: str, lugares: Lugares, *, segundos: int = 900
) -> None:
    """Roda um roteiro dentro de um contêiner, com nome e teto de tempo (nunca `kill` solto)."""
    rodar(
        [
            "podman",
            "run",
            "--rm",
            "--name",
            nome,
            "--timeout",
            str(segundos),
            "-v",
            f"{lugares.destino}:/dist:ro",
            "-e",
            "QT_QPA_PLATFORM=offscreen",
            "-e",
            "QT_QUICK_BACKEND=software",
            imagem,
            "sh",
            "-c",
            roteiro,
        ]
    )


def verificar(lugares: Lugares, *, quais: Sequence[str] = ("appimage", "deb", "rpm")) -> None:
    """Instala e **executa** cada artefato numa distro que não é esta máquina."""
    marca = int(time.time())
    if "appimage" in quais:
        print("verificando o AppImage em debian:stable-slim", flush=True)
        em_container(
            f"jarvis-appimage-{marca}",
            "docker.io/library/debian:stable-slim",
            "set -eux; apt-get update -qq; "
            f"apt-get install -y -qq --no-install-recommends {QT_NO_DEBIAN} >/dev/null; "
            # O AppImage é extraído em vez de montado: contêiner não tem FUSE, e extrair é o
            # caminho que o próprio runtime oferece (`--appimage-extract`).
            "cd /root; cp /dist/Jarvis-*-x86_64.AppImage ./jarvis.AppImage; "
            "chmod +x ./jarvis.AppImage; ./jarvis.AppImage --appimage-extract >/dev/null; "
            "./squashfs-root/AppRun --versao; "
            "./squashfs-root/AppRun --diagnostico | head -20; "
            "./squashfs-root/AppRun --capturar ./telas; ls -la ./telas",
            lugares,
        )
    if "deb" in quais:
        print("verificando o .deb em debian:stable-slim", flush=True)
        em_container(
            f"jarvis-deb-{marca}",
            "docker.io/library/debian:stable-slim",
            "set -eux; apt-get update -qq; "
            "apt-get install -y -qq --no-install-recommends /dist/jarvis_*_amd64.deb >/dev/null; "
            "jarvis --versao; jarvis --diagnostico | head -20; "
            "jarvis --capturar /root/telas; ls -la /root/telas; "
            "test -f /usr/share/applications/dev.sodredev.Jarvis.desktop; "
            "test -f /usr/share/licenses/jarvis/LGPL-3.0.txt",
            lugares,
        )
    if "rpm" in quais:
        print("verificando o .rpm em fedora:44", flush=True)
        em_container(
            f"jarvis-rpm-{marca}",
            "registry.fedoraproject.org/fedora:44",
            "set -eux; dnf install -y -q /dist/jarvis-*.x86_64.rpm >/dev/null; "
            "jarvis --versao; jarvis --diagnostico | head -20; "
            "jarvis --capturar /root/telas; ls -la /root/telas; "
            "test -f /usr/share/applications/dev.sodredev.Jarvis.desktop; "
            "test -f /usr/share/licenses/jarvis/LGPL-3.0.txt",
            lugares,
        )


def main(argv: Sequence[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "etapa",
        choices=("appdir", "appimage", "deb", "rpm", "tudo", "verificar"),
        help="o que fazer",
    )
    analisador.add_argument("--destino", type=Path, default=DESTINO_PADRAO)
    analisador.add_argument(
        "--sem-podar", action="store_true", help="não tira peso morto do AppDir (depuração)"
    )
    analisador.add_argument(
        "--reaproveitar", action="store_true", help="usa o AppDir que já está montado"
    )
    args = analisador.parse_args(argv)
    lugares = Lugares(destino=args.destino)
    lugares.destino.mkdir(parents=True, exist_ok=True)

    comeco = time.monotonic()
    try:
        if args.etapa == "verificar":
            verificar(lugares)
        else:
            if not (args.reaproveitar and lugares.appdir.exists()):
                montar_appdir(lugares, podar=not args.sem_podar)
            if args.etapa in {"appimage", "tudo"}:
                montar_appimage(lugares)
            if args.etapa in {"deb", "tudo"}:
                montar_pacote(lugares, "deb")
            if args.etapa in {"rpm", "tudo"}:
                montar_pacote(lugares, "rpm")
    except Falhou as erro:
        print(f"FALHOU: {erro}", file=sys.stderr)
        return 1
    print(f"pronto em {time.monotonic() - comeco:.0f} s — {lugares.destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
