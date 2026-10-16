"""Os indicadores de máquina que a tela mostra — medidos, nunca inventados (ADR-0019).

A referência de interface que o dono aprovou tem CPU, memória e disco num canto. Dois jeitos
de fazer isso: inventar números bonitos, ou ler os do sistema. Inventar está fora — é a regra
8 do CONTRIBUTING ("nenhum número inventado") valendo também para pixel.

Então aqui se lê `/proc` e `statvfs`, sem dependência nova e sem permissão nenhuma. Em sistema
que não tem `/proc` (Windows, por ora), a medida simplesmente **não aparece** — tela com
indicador vazio é honesta; tela com indicador plausível e falso não é.

A fração de CPU é a diferença entre duas leituras: a primeira chamada não tem com o que
comparar e devolve 0, e isso está dito no campo `detalhe`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

PROC: Final = Path("/proc")


@dataclass(slots=True)
class LeitorDeCpu:
    """Guarda a leitura anterior para a próxima poder virar porcentagem."""

    ocupado: int = 0
    total: int = 0

    def fracao(self) -> float | None:
        arquivo = PROC / "stat"
        try:
            primeira = arquivo.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError):
            return None
        campos = [int(valor) for valor in primeira.split()[1:] if valor.isdigit()]
        if len(campos) < 4:
            return None
        total = sum(campos)
        ocioso = campos[3]
        ocupado = total - ocioso
        anterior_ocupado, anterior_total = self.ocupado, self.total
        self.ocupado, self.total = ocupado, total
        if anterior_total == 0 or total <= anterior_total:
            return None
        return (ocupado - anterior_ocupado) / (total - anterior_total)


def _memoria() -> tuple[float, str] | None:
    try:
        linhas = (PROC / "meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    valores: dict[str, int] = {}
    for linha in linhas:
        nome, _, resto = linha.partition(":")
        numero = resto.strip().split(" ")[0]
        if numero.isdigit():
            valores[nome] = int(numero)
    total = valores.get("MemTotal", 0)
    disponivel = valores.get("MemAvailable", 0)
    if not total:
        return None
    usado = total - disponivel
    return usado / total, f"{usado / 1048576:.1f} / {total / 1048576:.0f} GB"


def _disco(caminho: str = "/") -> tuple[float, str] | None:
    try:
        estado = os.statvfs(caminho)
    except OSError:
        return None
    total = estado.f_blocks * estado.f_frsize
    livre = estado.f_bavail * estado.f_frsize
    if not total:
        return None
    usado = total - livre
    return usado / total, f"{usado / 1e12:.1f} / {total / 1e12:.1f} TB"


_CPU: Final = LeitorDeCpu()


def medidas() -> list[dict[str, Any]]:
    """As medidas prontas para a vista de medidores. Lista vazia quando não há o que medir."""
    saida: list[dict[str, Any]] = []
    fracao = _CPU.fracao()
    if fracao is not None:
        saida.append({"rotulo": "CPU", "fracao": fracao, "detalhe": f"{fracao * 100:.0f}%"})
    elif (PROC / "stat").exists():
        saida.append({"rotulo": "CPU", "fracao": 0.0, "detalhe": "medindo…"})
    memoria = _memoria()
    if memoria is not None:
        saida.append({"rotulo": "RAM", "fracao": memoria[0], "detalhe": memoria[1]})
    disco = _disco()
    if disco is not None:
        saida.append({"rotulo": "DISCO", "fracao": disco[0], "detalhe": disco[1]})
    return saida
