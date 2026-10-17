"""O cofre do bruto: o texto de cada episódio de conversa vai cifrado (ADR-0026, regra 6).

A regra é **cifrar antes da primeira gravação**, não depois: conversa gravada em claro e cifrada
mais tarde já deixou cópia em claro no disco (WAL, backup, lixeira do sistema). Por isso o
histórico **recusa** abrir um banco em disco sem cofre — o único lugar sem cifra é o banco
`:memory:` dos testes e das medições.

A cifra é Fernet (`cryptography`, Apache-2.0 OR BSD-3-Clause): AES-128-CBC com HMAC-SHA256,
autenticada — bruto adulterado não decifra, levanta. Nada de cifra feita à mão.

A chave mora no **chaveiro do SO** (`keyring`, o mesmo das chaves de API da ADR-0017), nunca no
disco ao lado do banco: chave junto do dado cifrado não protege contra quem copiou o disco. Sem
chaveiro, não há cofre, e sem cofre não há histórico em disco (P9: degradar, não improvisar).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Protocol

from cryptography.fernet import Fernet, InvalidToken

SERVICO_DO_CHAVEIRO: Final = "jarvis"
NOME_DA_CHAVE: Final = "memoria-cofre-v1"


class CofreIndisponivel(RuntimeError):
    """Não há como cifrar: sem chaveiro ou sem chave. O histórico em disco não abre."""


class BrutoAdulterado(ValueError):
    """O bruto não decifra com a chave: adulterado, truncado ou de outra chave."""


class Cofre(Protocol):
    def cifrar(self, claro: bytes) -> bytes: ...

    def decifrar(self, cifrado: bytes) -> bytes: ...


@dataclass(slots=True)
class CofreFernet:
    """Cifra autenticada com uma chave Fernet. A chave nunca aparece em `repr`."""

    chave: bytes = field(repr=False)
    _fernet: Fernet = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._fernet = Fernet(self.chave)

    def cifrar(self, claro: bytes) -> bytes:
        return self._fernet.encrypt(claro)

    def decifrar(self, cifrado: bytes) -> bytes:
        try:
            return self._fernet.decrypt(cifrado)
        except InvalidToken as erro:
            raise BrutoAdulterado("o bruto não decifra com esta chave") from erro


def nova_chave() -> bytes:
    return Fernet.generate_key()


def cofre_do_chaveiro(*, criar: bool = True) -> CofreFernet:
    """O cofre com a chave do chaveiro do SO; cria a chave na primeira vez, se `criar`."""
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError as erro:  # pragma: no cover — depende do grupo instalado
        raise CofreIndisponivel(
            "sem `keyring`: a chave do cofre só mora no chaveiro do SO"
        ) from erro
    try:
        guardada = keyring.get_password(SERVICO_DO_CHAVEIRO, NOME_DA_CHAVE)
        if guardada is None:
            if not criar:
                raise CofreIndisponivel("o chaveiro não tem a chave do cofre da memória")
            guardada = nova_chave().decode("ascii")
            keyring.set_password(SERVICO_DO_CHAVEIRO, NOME_DA_CHAVE, guardada)
    except KeyringError as erro:
        raise CofreIndisponivel(f"chaveiro do SO indisponível: {type(erro).__name__}") from erro
    return CofreFernet(guardada.encode("ascii"))
