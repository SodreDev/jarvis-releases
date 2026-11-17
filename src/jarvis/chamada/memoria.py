"""O que o Jarvis lembra de quem ligou, entre chamadas, e os recados (ADR-0074).

Decisão do dono (2026-11-17): o Jarvis lembra do chat/interlocutor entre chamadas — quem monta um
plano com ele pode continuar na próxima ligação. O que fica é **só o que a pessoa disse**, nas
palavras que o agente da chamada anotou (`chamada.lembrar_interlocutor`), e volta à chamada
seguinte **como dado**, entre os delimitadores dela. Nunca é autoridade: a chave é o nome/número
que o app de chamada mostra (falsificável) e nada aqui marca alguém como o dono — o TOTP é pedido
de novo a cada chamada.

Arquivos 0600 ao lado da configuração; retenção configurável (`chamada.toml`); o que passou do
prazo some na leitura seguinte. A transcrição bruta da chamada **não** vem para cá: ela vive só na
memória do agente durante a chamada."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.social.arquivo import escrever_privado

ARQUIVO_DAS_NOTAS: Final = "chamada-interlocutores.json"
ARQUIVO_DOS_RECADOS: Final = "chamada-recados.json"
NOTAS_POR_INTERLOCUTOR: Final = 20
CARACTERES_DA_NOTA: Final = 300
CARACTERES_DO_RECADO: Final = 500
DIA_S: Final = 24 * 3600


def chave(interlocutor: str) -> str:
    """Como o app mostra, sem diferença de maiúscula e de espaço."""
    return " ".join(str(interlocutor).casefold().split())[:120]


def _texto(valor: object, limite: int) -> str:
    return " ".join(str(valor or "").split())[:limite]


@dataclass(slots=True)
class _ArquivoJson:
    caminho: Path | None
    dados: dict[str, Any] = field(default_factory=dict)

    def ler(self) -> dict[str, Any]:
        if self.caminho is None:
            return self.dados
        try:
            lido = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return lido if isinstance(lido, dict) else {}

    def gravar(self, dados: dict[str, Any]) -> None:
        self.dados = dados
        if self.caminho is not None:
            escrever_privado(self.caminho, json.dumps(dados, ensure_ascii=False))


@dataclass(slots=True)
class MemoriaDosInterlocutores:
    """As notas por interlocutor. `caminho=None` = só em memória (testes)."""

    caminho: Path | None = None
    retencao_dias: Callable[[], int] = lambda: 30
    relogio: Callable[[], float] = time.time
    _arquivo: _ArquivoJson = field(init=False)

    def __post_init__(self) -> None:
        self._arquivo = _ArquivoJson(self.caminho)

    def _vivas(self) -> dict[str, list[dict[str, Any]]]:
        limite = self.relogio() - self.retencao_dias() * DIA_S
        dados = self._arquivo.ler()
        vivas: dict[str, list[dict[str, Any]]] = {}
        for nome, notas in dados.items():
            if not isinstance(notas, list):
                continue
            ficam = [
                n
                for n in notas
                if isinstance(n, dict) and isinstance(n.get("t"), (int, float)) and n["t"] >= limite
            ]
            if ficam:
                vivas[nome] = ficam
        return vivas

    def notas(self, interlocutor: str) -> list[dict[str, Any]]:
        """As notas que ainda valem: `{"quando": "AAAA-MM-DD", "nota": ...}`, da mais antiga."""
        return [
            {"quando": time.strftime("%Y-%m-%d", time.localtime(n["t"])), "nota": n["nota"]}
            for n in self._vivas().get(chave(interlocutor), [])
        ]

    def lembrar(self, interlocutor: str, nota: str) -> bool:
        texto = _texto(nota, CARACTERES_DA_NOTA)
        if not texto or not chave(interlocutor):
            return False
        vivas = self._vivas()
        lista = vivas.setdefault(chave(interlocutor), [])
        lista.append({"t": self.relogio(), "nota": texto})
        del lista[:-NOTAS_POR_INTERLOCUTOR]
        self._arquivo.gravar(vivas)
        return True

    def esquecer(self, interlocutor: str) -> None:
        vivas = self._vivas()
        vivas.pop(chave(interlocutor), None)
        self._arquivo.gravar(vivas)


@dataclass(slots=True)
class Recados:
    """Os recados das chamadas, com retenção. O Jarvis principal recebe cada um como evento."""

    caminho: Path | None = None
    retencao_dias: Callable[[], int] = lambda: 30
    relogio: Callable[[], float] = time.time
    _arquivo: _ArquivoJson = field(init=False)

    def __post_init__(self) -> None:
        self._arquivo = _ArquivoJson(self.caminho)

    def todos(self) -> list[dict[str, Any]]:
        limite = self.relogio() - self.retencao_dias() * DIA_S
        lista = self._arquivo.ler().get("recados", [])
        return [
            r
            for r in (lista if isinstance(lista, list) else [])
            if isinstance(r, dict) and isinstance(r.get("t"), (int, float)) and r["t"] >= limite
        ]

    def guardar(self, recado: dict[str, Any]) -> None:
        self._arquivo.gravar({"recados": [*self.todos(), {**recado, "t": self.relogio()}]})


__all__ = [
    "ARQUIVO_DAS_NOTAS",
    "ARQUIVO_DOS_RECADOS",
    "CARACTERES_DO_RECADO",
    "MemoriaDosInterlocutores",
    "Recados",
    "chave",
]
