"""As exibições abertas na janela do Jarvis e o que as `tela.*` fazem com elas (ADR-0055).

A porta é do laço (`jarvis.voz.app`), que a liga só quando há janela: no terminal as `tela.*` nem
aparecem para o modelo. Ela guarda cada exibição em duas formas — o HTML do modelo, já limpo (o que
`tela.ler` devolve para ele mudar), e o documento com o tema do Jarvis na frente (o que a janela
desenha) — e avisa a janela por duas portas (`ao_mostrar`, `ao_fechar`), chamadas da linha de quem
pediu: quem liga ali emite um sinal e volta.

Tudo o que chega à janela passou pelo sanitizador aqui; a janela sanitiza de novo na fronteira dela
(`jarvis.gui.componentes`), e o documento limpo é ponto fixo — limpar de novo devolve o mesmo.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Final

from jarvis.tela.sanitizar import sanitizar
from jarvis.tela.tema import CSS_DO_TEMA

LIMITE_DE_ABERTAS: Final = 3
"""Três exibições ao mesmo tempo, no máximo: a quarta fecha a mais velha (é só uma vista)."""
LIMITE_DO_TITULO: Final = 60
_ID: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_TEMA_LIMPO: Final = sanitizar("", tema=CSS_DO_TEMA).css


class TelaIndisponivel(ValueError):
    """Não há janela onde mostrar (o terminal, o modo sem tela): vira o erro da ferramenta."""


@dataclass(frozen=True, slots=True)
class Exibicao:
    """Uma exibição aberta."""

    id: str
    titulo: str
    html: str
    """O HTML do modelo, limpo e sem o tema: o que `tela.ler` devolve e o que ele manda de volta."""
    documento: str
    """O que a janela desenha: o tema do Jarvis antes da folha do modelo."""
    fundo: str = ""
    removidos: tuple[str, ...] = ()

    @property
    def caracteres(self) -> int:
        return len(self.html)


@dataclass(slots=True)
class PortaDaTela:
    """As exibições abertas, por id, da mais velha para a mais nova."""

    ao_mostrar: Callable[[Exibicao], None]
    """A janela cria (ou troca) o módulo desta exibição."""
    ao_fechar: Callable[[str], None]
    """A janela fecha o módulo desta exibição."""
    maximo: int = LIMITE_DE_ABERTAS
    _abertas: dict[str, Exibicao] = field(default_factory=dict, repr=False)
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _contador: int = 0

    def mostrar(self, html: str, *, titulo: str = "", identificador: str = "") -> Exibicao:
        """Limpa, guarda e mostra. Com o `identificador` de uma aberta, troca o conteúdo dela."""
        if identificador and not _ID.match(identificador):
            raise ValueError(
                f"id {identificador!r} inválido: letras minúsculas, números e hífen, até 32"
            )
        seguro = sanitizar(html, grade=True)
        if seguro.vazio:
            tirado = ", ".join(seguro.removidos) or "nada"
            raise ValueError(
                f"o conteúdo ficou vazio depois da limpeza (tirado: {tirado}); mande HTML simples "
                "com texto — sem script, imagem nem link"
            )
        documento = replace(seguro, css=f"{_TEMA_LIMPO} {seguro.css}".strip()).documento
        fechar: list[str] = []
        with self._trava:
            if identificador in self._abertas:
                del self._abertas[identificador]  # vai para o fim: é a mais nova
                escolhido = identificador
            else:
                self._contador += 1
                escolhido = identificador or f"t{self._contador}"
                while len(self._abertas) >= self.maximo:
                    mais_velha = next(iter(self._abertas))
                    del self._abertas[mais_velha]
                    fechar.append(mais_velha)
            exibicao = Exibicao(
                id=escolhido,
                titulo=" ".join(titulo.split())[:LIMITE_DO_TITULO] or "Na tela",
                html=seguro.documento,
                documento=documento,
                fundo=seguro.fundo,
                removidos=seguro.removidos,
            )
            self._abertas[escolhido] = exibicao
        for velha in fechar:
            self.ao_fechar(velha)
        self.ao_mostrar(exibicao)
        return exibicao

    def ler(self, identificador: str = "") -> Exibicao:
        """A exibição pedida, ou a mais nova."""
        with self._trava:
            if not self._abertas:
                raise ValueError("não há nada na tela agora")
            if not identificador:
                return next(reversed(self._abertas.values()))
            achada = self._abertas.get(identificador)
            abertas = ", ".join(self._abertas)
        if achada is None:
            raise ValueError(f"não há exibição {identificador!r} na tela; abertas: {abertas}")
        return achada

    def fechar(self, identificador: str = "", *, todas: bool = False) -> list[str]:
        """Fecha a pedida, a mais nova (sem id) ou todas. Devolve os ids fechados."""
        with self._trava:
            if todas:
                fechadas = list(self._abertas)
            elif identificador:
                fechadas = [identificador] if identificador in self._abertas else []
            else:
                fechadas = list(self._abertas)[-1:]
            for alvo in fechadas:
                del self._abertas[alvo]
        for alvo in fechadas:
            self.ao_fechar(alvo)
        return fechadas

    def fechada_pelo_dono(self, identificador: str) -> None:
        """O dono fechou o módulo na janela: a porta esquece (a janela já fechou)."""
        with self._trava:
            self._abertas.pop(identificador, None)

    def abertas(self) -> tuple[Exibicao, ...]:
        with self._trava:
            return tuple(self._abertas.values())


__all__ = ["LIMITE_DE_ABERTAS", "Exibicao", "PortaDaTela", "TelaIndisponivel"]
