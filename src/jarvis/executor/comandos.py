"""Comandos do desktop por `argv` fixo — nunca shell, nunca texto do modelo como programa.

Volume, brilho, mídia, janelas, área de transferência e notificação do desktop são programas que o
sistema já tem (`wpctl`, `gdbus`, `wl-copy`, `notify-send`, `wmctrl`…). Esta é a **única** porta do
executor para eles, e a terceira abertura nomeada do teste `test_sem_shell` (depois do lançador de
apps e do portal de sites):

- só entram programas da lista fechada `PROGRAMAS` — o nome do programa nunca vem do modelo, e sim
  do código de cada ferramenta, que monta o `argv` inteiro a partir de **argumentos tipados**
  (inteiros dentro de faixa, enums, ids de janela conferidos contra a lista real);
- sem shell: `subprocess.run` com lista, `shell=False`, tempo limite, saída truncada;
- **injetável**: toda ferramenta recebe um `Lancador`, e o teste passa um falso que grava o `argv` e
  devolve a saída combinada — nenhum teste toca o desktop do dono.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

PROGRAMAS: Final[frozenset[str]] = frozenset(
    {
        "wpctl",
        "pactl",
        "brightnessctl",
        "gdbus",
        "playerctl",
        "wl-copy",
        "wl-paste",
        "xclip",
        "notify-send",
        "wmctrl",
    }
)
"""Tudo o que o executor pode chamar por aqui. Acrescentar é decisão de revisão, não de runtime."""
LIMITE_DA_SAIDA: Final = 64 * 1024
PRAZO_PADRAO_S: Final = 5.0


class ComandoRecusado(ValueError):
    """O `argv` não é de um programa da lista, ou veio malformado."""


class ComandoIndisponivel(RuntimeError):
    """O programa não está instalado (ou não respondeu): a frase diz qual, para o dono instalar."""


@dataclass(frozen=True, slots=True)
class Saida:
    codigo: int
    saida: str = ""
    erro: str = ""

    @property
    def ok(self) -> bool:
        return self.codigo == 0


Lancador = Callable[[Sequence[str], float, str | None], Saida]
"""`(argv, prazo_s, entrada) -> Saida`. O de teste grava e responde; o de verdade é `executar`."""


def instalado(programa: str) -> bool:
    return shutil.which(programa) is not None


def executar(
    argv: Sequence[str], prazo_s: float = PRAZO_PADRAO_S, entrada: str | None = None
) -> Saida:
    """O lançador de verdade. `argv[0]` tem de ser da lista, e o resto vai como argumentos, sem
    interpretação nenhuma de shell."""
    if not argv or argv[0] not in PROGRAMAS:
        raise ComandoRecusado(f"{argv[0] if argv else '(vazio)'} não está na lista de programas")
    if any("\x00" in a for a in argv):
        raise ComandoRecusado("argumento com byte nulo")
    if not instalado(argv[0]):
        raise ComandoIndisponivel(f"{argv[0]} não está instalado nesta máquina")
    try:
        concluido = subprocess.run(  # noqa: S603 — argv fixo da lista, sem shell
            list(argv),
            input=entrada,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=prazo_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ComandoIndisponivel(f"{argv[0]} não respondeu em {prazo_s:.0f} s") from None
    return Saida(
        concluido.returncode,
        concluido.stdout[:LIMITE_DA_SAIDA],
        concluido.stderr[:LIMITE_DA_SAIDA],
    )


@dataclass(slots=True)
class LancadorFalso:
    """Para o teste: responde por programa (`wpctl` → `Saida`) e guarda cada `argv` que recebeu."""

    respostas: dict[str, Saida | Callable[[Sequence[str]], Saida]] = field(default_factory=dict)
    chamadas: list[list[str]] = field(default_factory=list)
    ausentes: frozenset[str] = frozenset()
    """Programas que "não estão instalados" (levantam `ComandoIndisponivel`)."""

    def __call__(self, argv: Sequence[str], prazo_s: float, entrada: str | None) -> Saida:
        if not argv or argv[0] not in PROGRAMAS:
            raise ComandoRecusado(f"{argv[0] if argv else '(vazio)'} não está na lista")
        self.chamadas.append([*argv, *([f"<<{entrada}"] if entrada is not None else [])])
        if argv[0] in self.ausentes:
            raise ComandoIndisponivel(f"{argv[0]} não está instalado nesta máquina")
        resposta = self.respostas.get(argv[0], Saida(0))
        return resposta(argv) if callable(resposta) else resposta
