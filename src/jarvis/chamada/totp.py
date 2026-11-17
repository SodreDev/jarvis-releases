"""O código de uso único que reconhece o dono numa chamada (ADR-0074; RFC 6238 sobre RFC 4226).

Decisão do dono (2026-11-17): TOTP aceito, configurável pelo app; o código fixo de 4 dígitos com
palavra fica só como fator fraco. Aqui mora a parte que não depende de áudio:

- `gerar_segredo`: 160 bits de `secrets`, em base32 (o formato que os apps autenticadores leem);
- `uri_otpauth`: o `otpauth://totp/…` que o app mostra **uma vez** (QR e texto) para o dono
  cadastrar no autenticador;
- `Verificador`: aceita o código da janela atual ±1 passo **uma vez** — o passo aceito fica
  gravado e nenhum código daquele passo ou de antes vale de novo (anti-reuso, mesmo entre
  chamadas e depois de reiniciar o Jarvis). Erros demais num dia bloqueiam até o dono liberar.

O segredo mora onde moram as chaves do app: variável de ambiente, ou o chaveiro do sistema
(`jarvis.gui.chaveiro`). Nunca em arquivo do projeto, log, trilha ou commit; `Verificador` só o
lê no momento de conferir, e nada aqui o imprime. O arquivo de estado (`totp-estado.json`, 0600)
guarda só números: o último passo aceito e as horas dos erros.

Só biblioteca padrão (`hmac`, `hashlib`, `base64`, `secrets`).
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import quote, urlencode

DIGITOS: Final = 6
PASSO_S: Final = 30
JANELA: Final = 1
"""Passos aceitos antes e depois do atual: o relógio do celular e o do PC nunca batem exato."""
BYTES_DO_SEGREDO: Final = 20
"""160 bits: o tamanho que a RFC 4226 recomenda para HMAC-SHA1."""
ERROS_POR_DIA: Final = 6
"""Erros (em todas as chamadas) que bloqueiam o reconhecimento até o dono liberar no app."""
DIA_S: Final = 24 * 3600
VARIAVEL: Final = "JARVIS_TOTP_DA_CHAMADA"
"""O nome do segredo no ambiente e no chaveiro (a «conta» do serviço `jarvis`)."""
EMISSOR: Final = "Jarvis"
ARQUIVO_DO_ESTADO: Final = "totp-estado.json"


class SegredoInvalido(ValueError):
    """O segredo não é base32 válido ou é curto demais."""


def _bytes(segredo: str) -> bytes:
    limpo = "".join(segredo.split()).upper().rstrip("=")
    try:
        bruto = base64.b32decode(limpo + "=" * (-len(limpo) % 8))
    except (ValueError, TypeError) as erro:
        raise SegredoInvalido("o segredo não é base32") from erro
    if len(bruto) < 10:
        raise SegredoInvalido("o segredo tem menos de 80 bits")
    return bruto


def gerar_segredo() -> str:
    """Um segredo novo, em base32 sem `=` (como os autenticadores esperam)."""
    return base64.b32encode(secrets.token_bytes(BYTES_DO_SEGREDO)).decode("ascii").rstrip("=")


def hotp(segredo: str, contador: int, digitos: int = DIGITOS) -> str:
    """RFC 4226 §5.3: HMAC-SHA1 do contador, truncamento dinâmico, `digitos` casas."""
    resumo = hmac.new(_bytes(segredo), struct.pack(">Q", contador), hashlib.sha1).digest()
    deslocamento = resumo[-1] & 0x0F
    numero = struct.unpack(">I", resumo[deslocamento : deslocamento + 4])[0] & 0x7FFFFFFF
    return str(numero % (10**digitos)).zfill(digitos)


def passo(instante: float) -> int:
    """RFC 6238 §4: o contador de tempo (T0 = 0)."""
    return int(instante // PASSO_S)


def totp(segredo: str, instante: float, digitos: int = DIGITOS) -> str:
    return hotp(segredo, passo(instante), digitos)


def uri_otpauth(segredo: str, *, conta: str = "dono", emissor: str = EMISSOR) -> str:
    """O formato do Key Uri (Google Authenticator), aceito pelos autenticadores comuns."""
    _bytes(segredo)  # recusa segredo inválido antes de mostrar
    rotulo = quote(f"{emissor}:{conta}", safe=":")
    parametros = urlencode(
        {
            "secret": "".join(segredo.split()).upper().rstrip("="),
            "issuer": emissor,
            "algorithm": "SHA1",
            "digits": DIGITOS,
            "period": PASSO_S,
        }
    )
    return f"otpauth://totp/{rotulo}?{parametros}"


# --- onde o segredo mora ---------------------------------------------------------------------
class GuardaDoSegredo(Protocol):
    """Onde o segredo mora. Os testes usam uma em memória; o app, `GuardaNoChaveiro`."""

    def ler(self) -> str | None: ...

    def gravar(self, segredo: str) -> None: ...

    def apagar(self) -> None: ...


@dataclass(slots=True)
class GuardaEmMemoria:
    """Para testes e para o modo sem chaveiro (o segredo morre com o processo)."""

    segredo: str | None = None

    def ler(self) -> str | None:
        return self.segredo

    def gravar(self, segredo: str) -> None:
        _bytes(segredo)
        self.segredo = segredo

    def apagar(self) -> None:
        self.segredo = None


@dataclass(slots=True)
class GuardaNoChaveiro:
    """Como as chaves de API: o ambiente ganha (`JARVIS_TOTP_DA_CHAMADA`), senão o chaveiro do
    sistema (`jarvis.gui.chaveiro`). Gravar e apagar mexem só no chaveiro."""

    ambiente: Mapping[str, str] | None = None

    def ler(self) -> str | None:
        fonte = os.environ if self.ambiente is None else self.ambiente
        exportado = fonte.get(VARIAVEL, "").strip()
        if exportado:
            return exportado
        from jarvis.gui import chaveiro

        return chaveiro.valor(VARIAVEL)

    def gravar(self, segredo: str) -> None:
        from jarvis.gui import chaveiro

        _bytes(segredo)
        chaveiro.guardar(VARIAVEL, segredo)

    def apagar(self) -> None:
        from jarvis.gui import chaveiro

        chaveiro.esquecer(VARIAVEL)


# --- conferir --------------------------------------------------------------------------------
class Veredito(StrEnum):
    ACEITO = "aceito"
    ERRADO = "errado"
    REUSADO = "reusado"
    """Código certo, mas de um passo que já foi aceito (replay)."""
    FORMATO = "formato"
    """Não são 6 dígitos: não conta como erro (o STT pode ter ouvido mal)."""
    SEM_SEGREDO = "sem_segredo"
    BLOQUEADO = "bloqueado"


@dataclass(slots=True)
class EstadoDoTotp:
    """Só números, em `totp-estado.json` (0600): o último passo aceito e as horas dos erros."""

    caminho: Path | None = None
    ultimo_passo: int = -1
    erros: list[float] = field(default_factory=list)

    @classmethod
    def ler(cls, caminho: Path | None) -> EstadoDoTotp:
        estado = cls(caminho=caminho)
        if caminho is None:
            return estado
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return estado
        if isinstance(dados, dict):
            ultimo = dados.get("ultimo_passo", -1)
            estado.ultimo_passo = ultimo if isinstance(ultimo, int) else -1
            erros = dados.get("erros", [])
            if isinstance(erros, list):
                estado.erros = [float(e) for e in erros if isinstance(e, (int, float))]
        return estado

    def gravar(self) -> None:
        if self.caminho is None:
            return
        from jarvis.social.arquivo import escrever_privado

        escrever_privado(
            self.caminho, json.dumps({"ultimo_passo": self.ultimo_passo, "erros": self.erros})
        )


@dataclass(slots=True)
class Verificador:
    """Confere um código. Thread-safe não precisa: uma chamada por vez (ADR-0074)."""

    guarda: GuardaDoSegredo
    estado: EstadoDoTotp = field(default_factory=EstadoDoTotp)
    relogio: Callable[[], float] = time.time
    erros_por_dia: int = ERROS_POR_DIA

    def configurado(self) -> bool:
        with contextlib.suppress(Exception):
            return bool(self.guarda.ler())
        return False

    def bloqueado(self) -> bool:
        agora = self.relogio()
        recentes = [e for e in self.estado.erros if agora - e < DIA_S]
        return len(recentes) >= self.erros_por_dia

    def liberar(self) -> None:
        """O dono, no app, libera o bloqueio por erros."""
        self.estado.erros = []
        self.estado.gravar()

    def conferir(self, codigo: str) -> Veredito:
        digitos = "".join(c for c in str(codigo) if c.isdigit())
        if len(digitos) != DIGITOS:
            return Veredito.FORMATO
        try:
            segredo = self.guarda.ler()
        except Exception:
            segredo = None
        if not segredo:
            return Veredito.SEM_SEGREDO
        if self.bloqueado():
            return Veredito.BLOQUEADO
        agora = self.relogio()
        atual = passo(agora)
        try:
            candidatos = [
                p
                for p in range(atual - JANELA, atual + JANELA + 1)
                if hmac.compare_digest(hotp(segredo, p), digitos)
            ]
        except SegredoInvalido:
            return Veredito.SEM_SEGREDO
        aceito = max(candidatos, default=None)
        if aceito is None or aceito <= self.estado.ultimo_passo:
            # O replay conta como erro: quem repete um código já usado não é o dono digitando.
            self.estado.erros = [e for e in self.estado.erros if agora - e < DIA_S] + [agora]
            self.estado.gravar()
            return Veredito.ERRADO if aceito is None else Veredito.REUSADO
        self.estado.ultimo_passo = aceito
        self.estado.gravar()
        return Veredito.ACEITO


__all__ = [
    "ARQUIVO_DO_ESTADO",
    "DIGITOS",
    "VARIAVEL",
    "EstadoDoTotp",
    "GuardaDoSegredo",
    "GuardaEmMemoria",
    "GuardaNoChaveiro",
    "SegredoInvalido",
    "Veredito",
    "Verificador",
    "gerar_segredo",
    "hotp",
    "totp",
    "uri_otpauth",
]
