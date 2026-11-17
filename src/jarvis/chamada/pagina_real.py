"""A aba do WhatsApp Web de verdade, para o agente do canal do dono (ADR-0074, fatia A).

Implementa a porta `PaginaDoWhatsapp` sobre a ponte do navegador (a mesma do monitor e do envio
da ADR-0060), com os métodos da ponte 7:

- `conversas` → `social.lista`: TODAS as linhas que a lista mostra (lidas ou não), com índice e
  nome; o id que o agente vê é `c<índice>`. A lista do WhatsApp é virtual — só as linhas
  desenhadas vêm (o dono fixa o chat dele no topo);
- `abrir` → `social.abrirLinha` com o índice e o nome lidos; se a lista reordenou e o nome da
  linha mudou, nada é clicado e o agente recebe «leia de novo»;
- `cabecalho` → `social.cabecalho`;
- `enviar` → digita no ritmo de pessoa (`jarvis.social.envio.ritmo`, por pedaços curtos),
  **reconfere o cabeçalho** (tem de ser o mesmo que o agente leu) e só então aperta Enter; solta
  o depurador **sempre**, deu certo ou não.

Sem a reação de 20–90 s das respostas a contatos: a mensagem vai ao próprio dono e espera-lo é o
que atrasa a confirmação; o ritmo da digitação continua. Só `gui/ponte.py` monta isto com a ponte
real; nos testes, uma ponte falsa. **Não provado na máquina real**: clique e tecla por CDP numa aba
de FUNDO do WhatsApp (o mesmo «não provado» da ADR-0060)."""

from __future__ import annotations

import contextlib
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from jarvis.chamada.canal_do_dono import LinhaDaLista, normal
from jarvis.navegador.protocolo import MAXIMO_DE_TECLAS
from jarvis.social.envio import Cabecalho, em_pedacos, ritmo

REDE: Final = "whatsapp"


class PonteDaPagina(Protocol):
    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]: ...


class ListaMudou(LookupError):
    """A linha escolhida não tem mais o nome lido: a lista reordenou."""


@dataclass(slots=True)
class PaginaPelaPonte:
    ponte: PonteDaPagina
    familia: Callable[[], str]
    aleatorio: random.Random = field(default_factory=random.SystemRandom)
    _linhas: dict[str, tuple[int, str]] = field(default_factory=dict)
    _cabecalho_lido: Cabecalho | None = None

    def _pedir(self, metodo: str, **params: Any) -> dict[str, Any]:
        return self.ponte.pedir(metodo, self.familia(), rede=REDE, **params)

    def conversas(self) -> list[LinhaDaLista]:
        bruto = self._pedir("social.lista")
        linhas: list[LinhaDaLista] = []
        self._linhas = {}
        for item in bruto.get("conversas") or []:
            if not isinstance(item, dict):
                continue
            indice, nome = item.get("indice"), str(item.get("nome") or "")
            if not isinstance(indice, int) or isinstance(indice, bool) or indice < 0 or not nome:
                continue
            identificador = f"c{indice}"
            self._linhas[identificador] = (indice, nome)
            linhas.append(
                LinhaDaLista(
                    identificador, nome, str(item.get("trecho") or ""), item.get("grupo") is True
                )
            )
        return linhas

    def abrir(self, identificador: str) -> None:
        if identificador not in self._linhas:
            raise LookupError("não há conversa com este id na última leitura da lista")
        indice, nome = self._linhas[identificador]
        self._cabecalho_lido = None
        resposta = self._pedir("social.abrirLinha", indice=indice, nome=nome)
        if resposta.get("mudou"):
            raise ListaMudou("a lista mudou desde a leitura: leia de novo antes de abrir")

    def cabecalho(self) -> Cabecalho:
        dados = self._pedir("social.cabecalho")
        self._cabecalho_lido = Cabecalho(
            nome=str(dados.get("nome", "")),
            telefone=str(dados.get("telefone", "")),
            grupo=bool(dados.get("grupo", False)),
            ambiguo=bool(dados.get("ambiguo", False)),
        )
        return self._cabecalho_lido

    def enviar(self, texto: str) -> None:
        lido = self._cabecalho_lido
        if lido is None:
            raise LookupError("o cabeçalho não foi lido depois de abrir")
        try:
            for pedaco in em_pedacos(ritmo(texto, self.aleatorio)):
                # O protocolo aceita até MAXIMO_DE_TECLAS por pedido: pedaço rápido demais
                # (muitas teclas em 5 s) é cortado de novo.
                for comeco in range(0, len(pedaco), MAXIMO_DE_TECLAS):
                    teclas = pedaco[comeco : comeco + MAXIMO_DE_TECLAS]
                    self._pedir(
                        "social.digitar",
                        texto="".join(t.texto for t in teclas),
                        atrasos=[t.atraso_ms for t in teclas],
                    )
            agora = self.cabecalho()  # reconferir antes do Enter
            if agora.grupo or agora.ambiguo or normal(agora.nome) != normal(lido.nome):
                raise LookupError("o chat aberto mudou durante a digitação: não enviei")
            self._pedir("social.enviar")
        finally:
            with contextlib.suppress(Exception):
                self._pedir("social.soltar")


__all__ = ["ListaMudou", "PaginaPelaPonte", "PonteDaPagina"]
