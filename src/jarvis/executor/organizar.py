"""Criar pasta, copiar e mover **dentro das raízes** (tier moderado; dono, 2026-10-18).

Tudo sob **descritor** (§5.5), como o resto dos arquivos: a raiz vem aberta do grant do PDP e cada
passo para dentro é relativo a ela. Regras, além das da política (lista de negação, raiz só de
leitura, link simbólico não seguido):

- **nunca sobrescreve**: nome que já existe ganha sufixo (`-2`, `-3`…) na cópia e no mover — o que
  o dono tem não some por uma frase;
- **cópia** lê da origem (que o PDP também julga, como leitura) e cria arquivo **novo** no destino;
  só arquivo comum, até 50 MB; pasta inteira não (ainda);
- **mover** só dentro da **mesma raiz** (um `rename` sob o descritor): sair de uma raiz para outra
  seria copiar e apagar, e apagar é perigoso;
- **criar pasta** é um nível só, dentro de uma pasta que já existe.
"""

from __future__ import annotations

import errno
import functools
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from jarvis.executor.arquivos import CRIAR
from jarvis.politica.canonicalizacao import CaminhoRecusado, Sistema, canonicalizar
from jarvis.politica.descritor import AberturaRecusada, RaizAberta
from jarvis.politica.pdp import Grant, Pdp, Pedido, Veredito

LIMITE_DA_COPIA: Final = 50 * 1024 * 1024
TENTATIVAS_DE_NOME: Final = 99


class OrganizacaoRecusada(ValueError):
    """A organização não pode ser feita: a frase diz por quê (e o modelo a repassa)."""


def _frase(erro: OSError) -> str:
    """O erro do sistema em português, sem o nome da chamada (`openat2`) que o dono não conhece."""
    if (
        isinstance(erro, FileNotFoundError)
        or os.strerror(errno.ENOENT) in str(erro)
        or "No such file" in str(erro)
    ):
        return "o arquivo ou a pasta não existe"
    if isinstance(erro, IsADirectoryError) or os.strerror(errno.EISDIR) in str(erro):
        return "só copio arquivo comum (pasta inteira ainda não)"
    if isinstance(erro, PermissionError):
        return "sem permissão do sistema para isso"
    return str(erro)


def _traduzindo[**P, R](metodo: Callable[P, R]) -> Callable[P, R]:
    """Todo erro do sistema vira `OrganizacaoRecusada`, com a frase em português."""

    @functools.wraps(metodo)
    def envolvido(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return metodo(*args, **kwargs)
        except OrganizacaoRecusada:
            raise
        except OSError as erro:
            raise OrganizacaoRecusada(_frase(erro)) from None

    return envolvido


def _e_pasta(raiz: RaizAberta, relativo: str) -> bool:
    try:
        with raiz.abrir(relativo, diretorio=True):
            return True
    except OSError:
        return False


def _nome_simples(nome: str) -> str:
    if nome in ("", ".", "..") or "/" in nome or "\\" in nome or nome.startswith("."):
        raise OrganizacaoRecusada(f"nome de arquivo ou pasta inválido: {nome!r}")
    return nome


def _com_sufixo(nome: str, tentativa: int) -> str:
    if tentativa == 1:
        return nome
    base, ext = PurePosixPath(nome).stem, PurePosixPath(nome).suffix
    return f"{base}-{tentativa}{ext}"


@dataclass(slots=True)
class Organizador:
    pdp: Pdp
    lar: Path
    sistema: Sistema
    session_id: str = ""
    call_id: str = ""
    contaminado: bool = False

    # --- caminhos ------------------------------
    def absoluto(self, bruto: str) -> str:
        texto = bruto.strip()
        if texto == "~" or texto.startswith("~/"):
            texto = str(self.lar) + texto[1:]
        if not Path(texto).is_absolute():
            raise OrganizacaoRecusada(
                f"caminho relativo ({bruto!r}): diga o caminho inteiro, por exemplo ~/Documentos/x"
            )
        return texto

    def _relativo(self, grant: Grant, caminho: str) -> str:
        texto = canonicalizar(caminho, self.sistema).texto
        return texto[len(grant.raiz.rstrip("/")) :].lstrip("/") or "."

    def _conferir(self, tool_id: str, caminho: str, args: dict[str, Any]) -> Grant:
        """Uma segunda decisão do PDP, sobre **outro** caminho da mesma chamada (a origem)."""
        try:
            decisao = self.pdp.decidir(
                Pedido(
                    tool_id,
                    args,
                    caminho,
                    session_id=self.session_id,
                    call_id=f"{self.call_id}-origem",
                    contaminado=self.contaminado,
                )
            )
        except CaminhoRecusado as erro:
            raise OrganizacaoRecusada(str(erro)) from None
        if decisao.veredito is not Veredito.ALLOW or decisao.grant is None:
            raise OrganizacaoRecusada(f"a origem foi negada: {decisao.motivo}")
        return decisao.grant

    # --- criar pasta ------------------------------
    @_traduzindo
    def criar_pasta(self, grant: Grant, caminho: str) -> dict[str, Any]:
        relativo = self._relativo(grant, caminho)
        pai, _, nome = relativo.rpartition("/")
        _nome_simples(nome)
        raiz = self.pdp.abrir_para(grant, ".")
        try:
            with raiz.abrir(pai or ".", diretorio=True) as destino:
                os.mkdir(nome, 0o755, dir_fd=destino.fd)
        except FileExistsError:
            raise OrganizacaoRecusada(f"{nome!r} já existe") from None
        except FileNotFoundError:
            raise OrganizacaoRecusada("a pasta de cima não existe: crio um nível só") from None
        return {"caminho": caminho, "nome": nome}

    # --- copiar ------------------------------
    @_traduzindo
    def copiar(
        self, grant_destino: Grant, origem_bruta: str, caminho_destino: str
    ) -> dict[str, Any]:
        origem = self.absoluto(origem_bruta)
        grant_origem = self._conferir("files.read_text", origem, {"path": origem_bruta})
        raiz_origem = self.pdp.abrir_para(grant_origem, ".")
        rel_origem = self._relativo(grant_origem, origem)
        if _e_pasta(raiz_origem, rel_origem):
            raise OrganizacaoRecusada("só copio arquivo comum (pasta inteira ainda não)")
        with raiz_origem.abrir(rel_origem) as aberto:
            info = os.fstat(aberto.fd)
            if not stat.S_ISREG(info.st_mode):
                raise OrganizacaoRecusada("só copio arquivo comum (pasta inteira ainda não)")
            if info.st_size > LIMITE_DA_COPIA:
                raise OrganizacaoRecusada("arquivo grande demais para copiar (passa de 50 MB)")
            conteudo = b""
            while bloco := os.read(aberto.fd, 1 << 20):
                conteudo += bloco
        relativo = self._relativo(grant_destino, caminho_destino)
        pai, _, nome = relativo.rpartition("/")
        _nome_simples(nome)
        raiz = self.pdp.abrir_para(grant_destino, ".")
        try:
            with raiz.abrir(pai or ".", diretorio=True) as destino:
                for tentativa in range(1, TENTATIVAS_DE_NOME + 1):
                    candidato = _com_sufixo(nome, tentativa)
                    try:
                        fd = os.open(candidato, CRIAR, 0o600, dir_fd=destino.fd)
                    except FileExistsError:
                        continue
                    try:
                        os.write(fd, conteudo)
                    finally:
                        os.close(fd)
                    final = caminho_destino.rsplit("/", 1)[0] + "/" + candidato
                    return {
                        "origem": origem,
                        "caminho": final,
                        "nome": candidato,
                        "bytes": len(conteudo),
                    }
        except FileNotFoundError:
            raise OrganizacaoRecusada("a pasta de destino não existe") from None
        raise OrganizacaoRecusada("99 cópias com o mesmo nome: escolha outro")

    # --- mover ------------------------------
    @_traduzindo
    def mover(
        self, grant_destino: Grant, origem_bruta: str, caminho_destino: str
    ) -> dict[str, Any]:
        origem = self.absoluto(origem_bruta)
        grant_origem = self._conferir(
            "files.move", origem, {"origem": origem_bruta, "destino": caminho_destino}
        )
        if grant_origem.raiz != grant_destino.raiz:
            raise OrganizacaoRecusada(
                "mover só dentro da mesma raiz; para outra pasta de outra raiz, copie"
            )
        rel_origem = self._relativo(grant_destino, origem)
        rel_destino = self._relativo(grant_destino, caminho_destino)
        if rel_origem in (".", "") or rel_destino.startswith(rel_origem + "/"):
            raise OrganizacaoRecusada("não dá para mover uma pasta para dentro dela mesma")
        pai_o, _, nome_o = rel_origem.rpartition("/")
        pai_d, _, nome_d = rel_destino.rpartition("/")
        _nome_simples(nome_o)
        _nome_simples(nome_d)
        raiz = self.pdp.abrir_para(grant_destino, ".")
        try:
            with (
                raiz.abrir(pai_o or ".", diretorio=True) as de,
                raiz.abrir(pai_d or ".", diretorio=True) as para,
            ):
                os.stat(nome_o, dir_fd=de.fd, follow_symlinks=False)
                for tentativa in range(1, TENTATIVAS_DE_NOME + 1):
                    candidato = _com_sufixo(nome_d, tentativa)
                    try:
                        os.stat(candidato, dir_fd=para.fd, follow_symlinks=False)
                    except FileNotFoundError:
                        os.rename(nome_o, candidato, src_dir_fd=de.fd, dst_dir_fd=para.fd)
                        final = caminho_destino.rsplit("/", 1)[0] + "/" + candidato
                        return {"de": origem, "para": final, "nome": candidato}
        except FileNotFoundError:
            raise OrganizacaoRecusada("a origem ou a pasta de destino não existe") from None
        except AberturaRecusada as erro:
            raise OrganizacaoRecusada(str(erro)) from None
        raise OrganizacaoRecusada("99 itens com o mesmo nome no destino")

    @_traduzindo
    def desfazer_mover(self, grant: Grant, de: str, para: str) -> None:
        """Volta o que foi movido, se o lugar de origem continua livre."""
        rel_de, rel_para = self._relativo(grant, de), self._relativo(grant, para)
        pai_de, _, nome_de = rel_de.rpartition("/")
        pai_para, _, nome_para = rel_para.rpartition("/")
        raiz = self.pdp.abrir_para(grant, ".")
        with (
            raiz.abrir(pai_para or ".", diretorio=True) as atual,
            raiz.abrir(pai_de or ".", diretorio=True) as antigo,
        ):
            try:
                os.stat(nome_de, dir_fd=antigo.fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(nome_para, nome_de, src_dir_fd=atual.fd, dst_dir_fd=antigo.fd)
                return
        raise OrganizacaoRecusada("o lugar de onde saiu já foi ocupado: não desfaço por cima")
