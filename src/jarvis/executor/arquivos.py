"""Os corpos das tools de arquivo e de rascunho do catálogo v1 (SPEC §5.6; ADR-0027).

Tudo aqui opera sobre **descritor**, não sobre texto de caminho (§5.5): a raiz chega aberta (no
grant do PDP, ou aberta uma vez para a busca), e cada passo para dentro é relativo a ela —
`RaizAberta.abrir` para o alvo pedido, `dir_fd` com `O_NOFOLLOW` para descer na busca e para
criar o rascunho. Link simbólico não é seguido em lugar nenhum, e o que a lista de negação cobre
(chaves, cofres, perfis de navegador, `.env`) não aparece nem quando está dentro de uma raiz.

Nada aqui tem shell, `subprocess` ou `eval` (aceite F0-03 d, varrido no código).
"""

from __future__ import annotations

import contextlib
import os
import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Final

from jarvis.barramento.envelope import uuid7
from jarvis.politica.canonicalizacao import Sistema, canonicalizar
from jarvis.politica.descritor import AberturaRecusada, RaizAberta
from jarvis.politica.modos import NOMES_NEGADOS, motivo_de_negacao

LIMITE_DA_LISTA: Final = 200
LIMITE_DA_LEITURA: Final = 64 * 1024
LIMITE_DE_ACHADOS: Final = 50
LIMITE_DE_VISITAS: Final = 20_000
PROFUNDIDADE_MAXIMA: Final = 8
PASTA_DE_RASCUNHOS: Final = "rascunhos"
PASTA_DE_AGENDA: Final = "rascunhos/agenda"
EXTENSOES_DE_RASCUNHO: Final = (".md", ".txt")
CRIAR: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
DESCER: Final = (
    os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)

Cancelado = Callable[[], bool]


class Cancelada(RuntimeError):
    """O dono interrompeu no meio: o que já foi feito vale, o resto não é feito."""


@dataclass(frozen=True, slots=True)
class Negado:
    """Alvo dentro da raiz mas na lista de negação: devolvido como recusa, nunca lido."""

    motivo: str


def _negado(absoluto: str, lar: Path, sistema: Sistema) -> str | None:
    nome = PurePosixPath(absoluto).name
    if nome in NOMES_NEGADOS:
        return f"{nome} é segredo (lista de negação da §5.5)"
    return motivo_de_negacao(canonicalizar(absoluto, sistema), lar, sistema)


def _junto(base: str, relativo: str) -> str:
    return base.rstrip("/") + ("" if relativo in ("", ".") else "/" + relativo.strip("/"))


# --- leitura ------------------------------------------------------------------------------
def listar(raiz: RaizAberta, relativo: str, *, lar: Path, sistema: Sistema) -> dict[str, Any]:
    pasta = _junto(str(raiz.caminho), relativo)
    with raiz.abrir(relativo, diretorio=True) as aberto:
        entradas: list[dict[str, Any]] = []
        omitidas = 0
        with os.scandir(aberto.fd) as itens:
            for item in sorted(itens, key=lambda e: e.name.casefold()):
                if _negado(_junto(pasta, item.name), lar, sistema) is not None:
                    omitidas += 1
                    continue
                if item.is_symlink():
                    tipo, tamanho = "link (não seguido)", None
                elif item.is_dir(follow_symlinks=False):
                    tipo, tamanho = "pasta", None
                else:
                    tipo, tamanho = "arquivo", item.stat(follow_symlinks=False).st_size
                entradas.append({"nome": item.name, "tipo": tipo, "bytes": tamanho})
    truncado = len(entradas) > LIMITE_DA_LISTA
    return {
        "pasta": pasta,
        "entradas": entradas[:LIMITE_DA_LISTA],
        "truncado": truncado,
        "omitidas_por_seguranca": omitidas,
    }


def ler_texto(raiz: RaizAberta, relativo: str) -> dict[str, Any]:
    with raiz.abrir(relativo) as aberto:
        tamanho = os.fstat(aberto.fd).st_size
        bruto = os.read(aberto.fd, LIMITE_DA_LEITURA + 1)
    if b"\x00" in bruto:
        raise ValueError("não é um arquivo de texto (tem bytes nulos)")
    truncado = len(bruto) > LIMITE_DA_LEITURA or tamanho > LIMITE_DA_LEITURA
    corpo = bruto[:LIMITE_DA_LEITURA]
    try:
        texto = corpo.decode("utf-8")
    except UnicodeDecodeError as erro:
        if not truncado or erro.start < len(corpo) - 4:
            raise ValueError("não é texto UTF-8") from None
        texto = corpo[: erro.start].decode("utf-8")  # o corte caiu no meio de um caractere
    return {
        "caminho": _junto(str(raiz.caminho), relativo),
        "texto": texto,
        "truncado": truncado,
        "bytes": tamanho,
    }


def procurar(
    raizes: list[RaizAberta],
    consulta: str,
    *,
    lar: Path,
    sistema: Sistema,
    cancelado: Cancelado,
) -> dict[str, Any]:
    """Nome que contém a consulta, sem acento e sem caixa, em todas as raízes do modo."""
    alvo = _sem_acento(consulta)
    achados: list[str] = []
    visitas = 0
    for raiz in raizes:
        for absoluto, nome in _andar(raiz, lar=lar, sistema=sistema, cancelado=cancelado):
            visitas += 1
            if alvo in _sem_acento(nome) and absoluto not in achados:
                achados.append(absoluto)
            if len(achados) > LIMITE_DE_ACHADOS or visitas >= LIMITE_DE_VISITAS:
                return {"achados": achados[:LIMITE_DE_ACHADOS], "truncado": True}
    return {"achados": achados, "truncado": False}


def _andar(
    raiz: RaizAberta, *, lar: Path, sistema: Sistema, cancelado: Cancelado
) -> Iterator[tuple[str, str]]:
    pilha: list[tuple[int, str, int]] = [(os.dup(raiz.fd), str(raiz.caminho), 0)]
    try:
        while pilha:
            fd, caminho, profundidade = pilha.pop()
            try:
                with os.scandir(fd) as itens:
                    for item in itens:
                        if cancelado():
                            raise Cancelada("o dono interrompeu a busca")
                        absoluto = _junto(caminho, item.name)
                        if item.is_symlink() or _negado(absoluto, lar, sistema) is not None:
                            continue
                        yield absoluto, item.name
                        if (
                            item.is_dir(follow_symlinks=False)
                            and profundidade < PROFUNDIDADE_MAXIMA
                        ):
                            try:
                                filho = os.open(item.name, DESCER, dir_fd=fd)
                            except OSError:
                                continue  # sem permissão ou trocado no meio: não entra
                            pilha.append((filho, absoluto, profundidade + 1))
            finally:
                os.close(fd)
    finally:
        for fd, _, _ in pilha:
            os.close(fd)


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()


# --- rascunhos ----------------------------------------------------------------------------
def nome_de_rascunho(bruto: str, *, extensao_padrao: str = ".md") -> str:
    """Um componente só, sem barra, sem `..`, sem começar por ponto: o que o modelo pediu vira
    um nome que não tem como apontar para fora da pasta de rascunhos."""
    caminho = PurePosixPath(bruto.strip())
    base, extensao = caminho.stem, caminho.suffix
    if extensao.lower() not in EXTENSOES_DE_RASCUNHO:
        base, extensao = bruto.strip(), extensao_padrao
    limpo = re.sub(r"[^\w\- ]+", "", _sem_acento(base), flags=re.UNICODE).strip().replace(" ", "-")
    return (limpo[:60] or "rascunho") + extensao.lower()


def gravar_rascunho(
    raiz: RaizAberta, nome: str, texto: str, *, pasta: str = PASTA_DE_RASCUNHOS
) -> dict[str, Any]:
    """Arquivo **novo** na pasta de rascunhos; nome repetido ganha sufixo, nunca sobrescreve."""
    dados = texto.encode("utf-8")
    base, extensao = PurePosixPath(nome).stem, PurePosixPath(nome).suffix
    with raiz.abrir(pasta, diretorio=True) as aberto:
        for tentativa in range(1, 100):
            candidato = nome if tentativa == 1 else f"{base}-{tentativa}{extensao}"
            try:
                fd = os.open(candidato, CRIAR, 0o600, dir_fd=aberto.fd)
            except FileExistsError:
                continue
            try:
                os.write(fd, dados)
            finally:
                os.close(fd)
            return {
                "caminho": _junto(_junto(str(raiz.caminho), pasta), candidato),
                "nome": candidato,
                "bytes": len(dados),
            }
    raise AberturaRecusada("99 rascunhos com o mesmo nome: escolha outro")


def recolher_para_a_lixeira(
    raiz: RaizAberta, relativo: str, *, lixeira: str = "lixeira"
) -> dict[str, Any]:
    """Tira um arquivo da pasta e o põe na lixeira **do Jarvis** (na mesma raiz). Nunca apaga.

    É o "desfazer" do que o Jarvis criou: o arquivo continua existindo, só sai de onde estava, e o
    dono decide o fim dele. O `rename` é sob o descritor da raiz, nos dois lados (§5.5).
    """
    relativo = relativo.strip("/")
    pasta, _, nome = relativo.rpartition("/")
    if not nome:
        raise AberturaRecusada("sem nome de arquivo para recolher")
    if relativo == lixeira or relativo.startswith(lixeira + "/"):
        raise AberturaRecusada("isso já está na lixeira")
    with contextlib.suppress(FileExistsError):
        os.mkdir(lixeira, 0o700, dir_fd=raiz.fd)
    agora = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    with (
        raiz.abrir(pasta or ".", diretorio=True) as origem,
        raiz.abrir(lixeira, diretorio=True) as destino,
    ):
        os.stat(nome, dir_fd=origem.fd, follow_symlinks=False)  # FileNotFoundError se já saiu
        for tentativa in range(1, 100):
            novo = f"{agora}-{nome}" if tentativa == 1 else f"{agora}-{tentativa}-{nome}"
            try:
                os.stat(novo, dir_fd=destino.fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(nome, novo, src_dir_fd=origem.fd, dst_dir_fd=destino.fd)
                return {
                    "recolhido": relativo,
                    "lixeira": _junto(str(raiz.caminho), f"{lixeira}/{novo}"),
                }
    raise AberturaRecusada("lixeira cheia de nomes iguais")


def evento_ics(titulo: str, inicio: str, *, duracao_min: int = 60, local: str = "") -> str:
    """Um VEVENT local, sem convidado e sem fuso (hora da agenda do dono) — RFC 5545."""
    comeco = datetime.fromisoformat(inicio)
    if comeco.tzinfo is not None:
        comeco = comeco.replace(tzinfo=None)
    fim = comeco + timedelta(minutes=duracao_min)
    agora = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Jarvis//rascunho local//PT",
        "BEGIN:VEVENT",
        f"UID:{uuid7()}@jarvis.local",
        f"DTSTAMP:{agora}",
        f"DTSTART:{comeco:%Y%m%dT%H%M%S}",
        f"DTEND:{fim:%Y%m%dT%H%M%S}",
        f"SUMMARY:{_ics(titulo)}",
    ]
    if local:
        linhas.append(f"LOCATION:{_ics(local)}")
    linhas += ["STATUS:TENTATIVE", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(linhas) + "\r\n"


def _ics(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
