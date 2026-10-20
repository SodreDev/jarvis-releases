"""A trilha de diagnóstico do turno: o que o Jarvis fez, quanto levou e por que perguntou.

Pedido do dono (2026-10-20, depois de testar o app): para melhorar o Jarvis é preciso ver o que
ele fez em cada turno — que ferramentas chamou, quanto cada uma levou, o que o PDP, o Jev e as
pendências decidiram, o motivo de cada pedido de permissão e os erros de ferramenta e de seletor.

Um JSONL local, rotativo (`turnos.jsonl`, `.1`, `.2`…), **só de metadados**: ids, nomes de
ferramenta, chaves de argumento (nunca os valores), tempos, status, vereditos e os motivos que o
próprio código escreve. Nunca vai texto do dono, texto de página, resultado de ferramenta nem
áudio; todo texto passa pelo `redigir` do projeto e é cortado. Nada sai da máquina. O
`jarvis-voz --diagnostico` lê o último turno daqui (`resumo_do_ultimo_turno`).
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from jarvis.memoryd.importacao import redigir

ARQUIVO: Final = "turnos.jsonl"
TAMANHO_MAXIMO: Final = 512 * 1024
COPIAS: Final = 3
"""Até ~2 MB no total: o arquivo vivo e três antigos."""
CARACTERES_POR_TEXTO: Final = 160
CODIGO_NO_MOTIVO: Final = r"\(([a-z][a-z_]{2,40})\)"
"""O código da extensão que o corpo das browser.* põe entre parênteses: "(alvo_ausente)"."""


def limpo(valor: object) -> object:
    """O que pode ir para a trilha: número e booleano como estão; texto redigido e curto."""
    if valor is None or isinstance(valor, bool | int | float):
        return valor
    if isinstance(valor, list | tuple):
        return [limpo(v) for v in list(valor)[:20]]
    texto = " ".join(redigir(str(valor)).texto.split())
    return texto if len(texto) <= CARACTERES_POR_TEXTO else texto[:CARACTERES_POR_TEXTO] + "…"


class TrilhaDeDiagnostico:
    """Escreve eventos de metadados do turno; segura para várias linhas de execução."""

    def __init__(
        self,
        pasta: Path,
        *,
        tamanho_maximo: int = TAMANHO_MAXIMO,
        copias: int = COPIAS,
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self.pasta = pasta
        self._tamanho_maximo = tamanho_maximo
        self._copias = copias
        self._relogio = relogio
        self._trava = threading.Lock()
        self.turno = ""
        """O turno corrente: os eventos sem `turno` explícito ficam nele."""

    @property
    def arquivo(self) -> Path:
        return self.pasta / ARQUIVO

    def novo_turno(self, turno: str, **campos: object) -> None:
        self.turno = turno
        self.evento("turno.inicio", **campos)

    def evento(self, tipo: str, **campos: object) -> None:
        """Um evento. Falha de disco não derruba o turno: a trilha é ajuda, não requisito."""
        registro: dict[str, object] = {
            "t": round(self._relogio(), 3),
            "turno": campos.pop("turno", None) or self.turno,
            "evento": tipo,
        }
        registro.update({chave: limpo(valor) for chave, valor in campos.items()})
        linha = json.dumps(registro, ensure_ascii=False) + "\n"
        with self._trava:
            try:
                self.pasta.mkdir(parents=True, exist_ok=True)
                self._girar_se_preciso(len(linha.encode("utf-8")))
                with self.arquivo.open("a", encoding="utf-8") as saida:
                    saida.write(linha)
            except OSError:
                return

    def _girar_se_preciso(self, acrescimo: int) -> None:
        try:
            atual = self.arquivo.stat().st_size
        except FileNotFoundError:
            return
        if atual + acrescimo <= self._tamanho_maximo:
            return
        mais_velho = self.pasta / f"{ARQUIVO}.{self._copias}"
        mais_velho.unlink(missing_ok=True)
        for indice in range(self._copias - 1, 0, -1):
            antigo = self.pasta / f"{ARQUIVO}.{indice}"
            if antigo.exists():
                antigo.rename(self.pasta / f"{ARQUIVO}.{indice + 1}")
        self.arquivo.rename(self.pasta / f"{ARQUIVO}.1")


def codigo_do_motivo(motivo: str) -> str:
    """O código de erro da extensão (`alvo_ausente`) quando o motivo o traz entre parênteses."""
    achado = re.search(CODIGO_NO_MOTIVO, motivo)
    return achado.group(1) if achado is not None else ""


def _eventos(pasta: Path) -> list[dict[str, Any]]:
    """Do arquivo vivo e do `.1` (o turno pode ter começado antes da última volta)."""
    eventos: list[dict[str, Any]] = []
    for arquivo in (pasta / f"{ARQUIVO}.1", pasta / ARQUIVO):
        try:
            linhas = arquivo.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for linha in linhas:
            try:
                dado = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(dado, dict):
                eventos.append(dado)
    return eventos


def eventos_do_ultimo_turno(pasta: Path) -> list[dict[str, Any]]:
    eventos = _eventos(pasta)
    inicios = [e for e in eventos if e.get("evento") == "turno.inicio"]
    if not inicios:
        return []
    turno = inicios[-1].get("turno")
    return [e for e in eventos if e.get("turno") == turno]


def _ms(valor: object) -> str:
    return f"{float(valor):.0f} ms" if isinstance(valor, int | float) else "?"


def resumo_do_ultimo_turno(pasta: Path) -> list[str]:
    """O último turno em linhas curtas, para o `jarvis-voz --diagnostico`."""
    eventos = eventos_do_ultimo_turno(pasta)
    if not eventos:
        return ["  nenhum turno registrado ainda (a trilha nasce no primeiro pedido)"]
    inicio = eventos[0]
    quando = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(inicio.get("t", 0))))
    linhas = [f"  turno {inicio.get('turno')} em {quando} · motor {inicio.get('motor', '?')}"]
    for evento in eventos[1:]:
        linhas.append("  " + _linha(evento))
    return linhas


def _linha(evento: Mapping[str, Any]) -> str:
    tipo = evento.get("evento")
    if tipo == "ferramenta":
        detalhe = f" — {evento['motivo']}" if evento.get("motivo") else ""
        codigo = f" [{evento['codigo']}]" if evento.get("codigo") else ""
        return (
            f"ferramenta {evento.get('tool_id')}: {evento.get('status')} em "
            f"{_ms(evento.get('ms'))} (PDP {evento.get('pdp', '?')}){codigo}{detalhe}"
        )
    if tipo == "portao":
        return (
            f"portão {evento.get('tool_id')}: {evento.get('decisao')} "
            f"(PDP {evento.get('pdp')}, {evento.get('jev')}, {_ms(evento.get('ms'))})"
        )
    if tipo == "permissao":
        return (
            f"pediu permissão para {evento.get('tool_id')} ({evento.get('origem')}): "
            f"{evento.get('motivo')} → {evento.get('resposta', '?')}"
        )
    if tipo == "turno.fim":
        return (
            f"fim: {evento.get('fim')} · 1ª fala {_ms(evento.get('ms_primeira_fala'))} · "
            f"1º áudio {_ms(evento.get('ms_primeiro_audio'))} · total {_ms(evento.get('ms_total'))}"
            f" · {evento.get('ferramentas', 0)} ferramenta(s)"
        )
    resto = ", ".join(f"{k}={v}" for k, v in evento.items() if k not in ("t", "turno", "evento"))
    return f"{tipo}: {resto}"


def chaves(argumentos: Mapping[str, Any] | Iterable[str]) -> list[str]:
    """Os nomes dos argumentos — nunca os valores."""
    return sorted(str(chave) for chave in argumentos)
