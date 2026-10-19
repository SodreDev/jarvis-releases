"""Tabelas fechadas de teclas: o que o Jarvis pode apertar, e como cada backend as chama.

O portal recebe **keysyms** (independem do layout do teclado); o `uinput` recebe **códigos de
tecla** do kernel (`linux/input-event-codes.h`) e, por isso, só digita o que tem a mesma posição
nos layouts US e ABNT2: letras, dígitos, espaço, Enter, ponto e vírgula.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

LIMITE_DO_TEXTO: Final = 500
MODIFICADORES: Final[tuple[str, ...]] = ("ctrl", "shift", "alt")

# --- nomes → keysym X11 (usados pelo portal) --------------------------------------------------
KEYSYM_DE_NOME: Final[dict[str, int]] = {
    "enter": 0xFF0D,
    "tab": 0xFF09,
    "esc": 0xFF1B,
    "backspace": 0xFF08,
    "delete": 0xFFFF,
    "space": 0x0020,
    "home": 0xFF50,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
    "pageup": 0xFF55,
    "pagedown": 0xFF56,
    "end": 0xFF57,
}
KEYSYM_DO_MODIFICADOR: Final[dict[str, int]] = {"ctrl": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9}

# --- nomes → código de tecla do kernel (usados pelo uinput) -----------------------------------
CODIGO_DE_NOME: Final[dict[str, int]] = {
    "esc": 1,
    "backspace": 14,
    "tab": 15,
    "enter": 28,
    "space": 57,
    "home": 102,
    "up": 103,
    "pageup": 104,
    "left": 105,
    "right": 106,
    "end": 107,
    "down": 108,
    "pagedown": 109,
    "delete": 111,
}
CODIGO_DO_MODIFICADOR: Final[dict[str, int]] = {"ctrl": 29, "shift": 42, "alt": 56}
_LINHAS_DO_TECLADO: Final = (("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44))
CODIGO_DE_LETRA: Final[dict[str, int]] = {
    letra: inicio + i for linha, inicio in _LINHAS_DO_TECLADO for i, letra in enumerate(linha)
}
CODIGO_DE_DIGITO: Final[dict[str, int]] = {d: 2 + i for i, d in enumerate("1234567890")}
CODIGO_DE_PONTUACAO: Final[dict[str, int]] = {",": 51, ".": 52}

TECLAS_NOMEADAS: Final = frozenset(KEYSYM_DE_NOME)
TECLAS_DE_CARACTERE: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
TECLAS_PERMITIDAS: Final = TECLAS_NOMEADAS | TECLAS_DE_CARACTERE
PROIBIDAS_COM_CTRL_E_ALT: Final = "ctrl+alt"


class TeclaRecusada(ValueError):
    """Tecla ou combinação fora do vocabulário fechado."""


@dataclass(frozen=True, slots=True)
class Combinacao:
    modificadores: tuple[str, ...]
    tecla: str

    @property
    def texto(self) -> str:
        return "+".join((*self.modificadores, self.tecla))

    @property
    def e_enter(self) -> bool:
        return self.tecla == "enter"


def interpretar(bruta: str) -> Combinacao:
    """`ctrl+l`, `enter`, `shift+tab`… Caixa e espaço são perdoados; `super` e `ctrl+alt`, não."""
    partes = [p.strip().lower() for p in bruta.split("+")]
    if not partes or any(not p for p in partes):
        raise TeclaRecusada(f"combinação vazia ou malformada: {bruta!r}")
    *mods, tecla = partes
    if tecla not in TECLAS_PERMITIDAS:
        raise TeclaRecusada(
            f"tecla {tecla!r} fora da lista (letras, dígitos, enter, tab, esc, backspace, delete, "
            "space, setas, home, end, pageup, pagedown)"
        )
    desconhecidos = [m for m in mods if m not in MODIFICADORES]
    if desconhecidos:
        raise TeclaRecusada(
            f"modificador {desconhecidos[0]!r} não é permitido (só ctrl, shift, alt)"
        )
    if len(set(mods)) != len(mods):
        raise TeclaRecusada("modificador repetido")
    if "ctrl" in mods and "alt" in mods:
        raise TeclaRecusada("ctrl+alt é reservado ao sistema (troca de sessão, terminal, reinício)")
    return Combinacao(tuple(m for m in MODIFICADORES if m in mods), tecla)


def validar_texto(texto: str) -> str:
    if not texto or len(texto) > LIMITE_DO_TEXTO:
        raise TeclaRecusada(f"texto vazio ou com mais de {LIMITE_DO_TEXTO} caracteres")
    for c in texto:
        if c in "\n\t":
            continue
        if ord(c) < 0x20 or ord(c) == 0x7F or 0x80 <= ord(c) < 0xA0:
            raise TeclaRecusada("o texto tem caractere de controle")
    return texto


def keysym_do_caractere(c: str) -> int:
    """Latin-1 imprimível: o keysym é o próprio ponto de código; o resto, `0x01000000 + ponto`."""
    if c == "\n":
        return KEYSYM_DE_NOME["enter"]
    if c == "\t":
        return KEYSYM_DE_NOME["tab"]
    ponto = ord(c)
    return ponto if (0x20 <= ponto <= 0x7E or 0xA0 <= ponto <= 0xFF) else 0x01000000 + ponto


def keysym_da_tecla(tecla: str) -> int:
    return KEYSYM_DE_NOME[tecla] if tecla in KEYSYM_DE_NOME else ord(tecla)


def teclas_do_uinput(c: str) -> tuple[int, bool]:
    """`(código, com_shift)` de um caractere que tem a mesma posição em US e ABNT2."""
    if c == "\n":
        return CODIGO_DE_NOME["enter"], False
    if c == " ":
        return CODIGO_DE_NOME["space"], False
    minuscula = c.lower()
    if minuscula in CODIGO_DE_LETRA:
        return CODIGO_DE_LETRA[minuscula], c != minuscula
    if c in CODIGO_DE_DIGITO:
        return CODIGO_DE_DIGITO[c], False
    if c in CODIGO_DE_PONTUACAO:
        return CODIGO_DE_PONTUACAO[c], False
    raise TeclaRecusada(
        f"o caractere {c!r} depende do layout do teclado e o uinput não o digita "
        "(só letras sem acento, dígitos, espaço, Enter, ponto e vírgula)"
    )


def codigo_da_tecla(tecla: str) -> int:
    if tecla in CODIGO_DE_NOME:
        return CODIGO_DE_NOME[tecla]
    if tecla in CODIGO_DE_LETRA:
        return CODIGO_DE_LETRA[tecla]
    return CODIGO_DE_DIGITO[tecla]
