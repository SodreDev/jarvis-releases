"""Os modos de permissão do dono: automático e bypass (ADR-0066; dono, 2026-11-14).

O dono mandou acabar com os pedidos de permissão, aceitando os riscos. Dois modos, que ele escolhe
no painel ou pela voz, e que ficam salvos:

- **automático** (o padrão): o Jarvis decide sozinho. Só pedem o sim as ações **destrutivas**:
  matar ou encerrar processo (encerrar app, fechar janela, encerrar o próprio Jarvis com coisa no
  ar) e apagar (arquivo para a lixeira, memória apagada) — e, mesmo nelas, só quando a regra de
  sempre já pedia (o app com trabalho não salvo, por exemplo);
- **bypass**: nenhuma ação pede o sim.

O que **não** é pedido de permissão continua igual nos dois: a lista de negação (chaves, cofres,
perfis de navegador — nunca lidos, logo nunca impressos nem exfiltrados), o catálogo e o nível de
acesso a pastas, o «não fazer» do guarda e do portão, e a auditoria de toda decisão (o motivo diz
o modo que dispensou o sim).

`MATRIZ` não é escolha do dono: é a matriz inteira da SPEC §5.5, que o PDP usa quando ninguém
diz o modo (os testes da matriz e as medições). O aplicativo sempre passa o modo do dono.

Mudar o modo pela voz é do **código**, nunca do modelo: a fala do dono no turno dele é lida por
`comando_de_permissao` antes do motor, e nenhuma ferramenta muda o modo — texto de página ou de
mensagem que diga «modo bypass» não chega aqui.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final


class ModoDePermissao(StrEnum):
    AUTOMATICO = "automatico"
    BYPASS = "bypass"
    MATRIZ = "matriz"
    """A matriz da §5.5 inteira — o padrão do `Pdp` solto (testes); o dono não escolhe este."""


PERMISSAO_PADRAO: Final = ModoDePermissao.AUTOMATICO
MODOS_DO_DONO: Final[tuple[str, ...]] = (ModoDePermissao.AUTOMATICO, ModoDePermissao.BYPASS)

DESTRUTIVAS: Final[frozenset[str]] = frozenset(
    {
        "apps.quit",
        "window.close",
        "jarvis.encerrar",
        "files.move_to_trash",
        "memoria.apagar",
    }
)
"""Matar/encerrar processo e apagar: o que ainda pede o sim no modo automático (quando a regra de
sempre pede). Encerrar app, fechar a janela (pode ser o último processo, com trabalho não salvo),
encerrar o Jarvis com tarefa no ar, mandar arquivo para a lixeira e apagar memória."""

NOME_DO_MODO: Final[dict[str, str]] = {
    ModoDePermissao.AUTOMATICO: "automático",
    ModoDePermissao.BYPASS: "bypass",
    ModoDePermissao.MATRIZ: "matriz completa",
}
FRASE_DO_MODO: Final[dict[str, str]] = {
    ModoDePermissao.AUTOMATICO: (
        "Eu decido sozinho; só peço o seu sim para encerrar programa e apagar arquivo."
    ),
    ModoDePermissao.BYPASS: "Não peço permissão para nada; tudo fica registrado na trilha.",
    ModoDePermissao.MATRIZ: "Peço o sim em tudo que a matriz de risco manda.",
}


def modo_de_permissao(texto: str) -> ModoDePermissao:
    """O modo do arquivo de configuração; o desconhecido (ou vazio) é o padrão do dono."""
    try:
        modo = ModoDePermissao(texto.strip().lower())
    except ValueError:
        return PERMISSAO_PADRAO
    return modo if modo in MODOS_DO_DONO else PERMISSAO_PADRAO


def dispensa_o_sim(modo: ModoDePermissao, tool_id: str) -> bool:
    """O sim que a política pediria para esta ferramenta é dispensado neste modo?"""
    if modo is ModoDePermissao.BYPASS:
        return True
    if modo is ModoDePermissao.AUTOMATICO:
        return tool_id not in DESTRUTIVAS
    return False


def frase_da_troca(modo: ModoDePermissao) -> str:
    return f"Modo {NOME_DO_MODO[modo]}. {FRASE_DO_MODO[modo]}"


def _normal(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).split())


_VERBO: Final = (
    r"(?:ativa|ative|ativar|liga|ligue|ligar|usa|use|usar|entra|entre|entrar|muda|mude|mudar|"
    r"troca|troque|trocar|coloca|coloque|colocar|poe|ponha|por|passa|passe|passar|volta|volte|"
    r"voltar|vai|va|fica|fique|ficar|deixa|deixe|deixar)"
)
_ALVO: Final = r"(?P<alvo>automatico|bypass|by pass|bai pass|baipass|baipas|bipass)"
_COMANDO: Final = re.compile(
    rf"\b{_VERBO}\b(?:\s+\w+){{0,4}}?\s+(?:o\s+|no\s+|pro\s+|para\s+o\s+)?"
    rf"(?:modo|permissao|permissoes)(?:\s+de\s+permissao)?\s+(?:em\s+)?{_ALVO}\b"
)
_SO_O_MODO: Final = re.compile(rf"^(?:jarvis\s+)?modo\s+{_ALVO}$")


def comando_de_permissao(fala: str) -> ModoDePermissao | None:
    """A fala do dono manda trocar o modo de permissão? Lido pelo código, sem rede.

    Precisa de verbo de ordem («ativa o modo bypass», «volta pro modo automático») ou da frase
    só com o modo («modo bypass»). Pergunta («o que é o modo bypass?») não troca nada."""
    texto = _normal(fala).strip(" .!")
    if not texto or "?" in texto:
        return None
    achado = _SO_O_MODO.match(texto.removeprefix("jarvis, ").strip(" ,")) or _COMANDO.search(texto)
    if achado is None:
        return None
    alvo = achado.group("alvo")
    return ModoDePermissao.AUTOMATICO if alvo == "automatico" else ModoDePermissao.BYPASS


__all__ = [
    "DESTRUTIVAS",
    "FRASE_DO_MODO",
    "MODOS_DO_DONO",
    "NOME_DO_MODO",
    "PERMISSAO_PADRAO",
    "ModoDePermissao",
    "comando_de_permissao",
    "dispensa_o_sim",
    "frase_da_troca",
    "modo_de_permissao",
]
