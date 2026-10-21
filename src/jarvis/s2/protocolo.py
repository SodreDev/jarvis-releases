"""O protocolo de texto das propostas de ferramenta (ADR-0028, ADR-0031, ADR-0038).

O motor que roda **sem** ferramenta nenhuma (o `claude -p` provisório, ADR-0018) propõe uma
chamada escrevendo-a no texto. Este leitor separa, ainda no stream, o que é fala do que é
protocolo; nada do protocolo pode chegar à voz nem à tela como resposta do Jarvis (dono,
2026-10-21: o Jarvis lia em voz alta a chamada e os argumentos).

Vale para o adaptador da CLI **e** para o cérebro (`jarvis.s2.cerebro`), que passa todo `Texto`
de qualquer motor por um leitor seu: o motor que esqueceu de separar não fala JSON por isso.
As formas reconhecidas, todas medidas ou vistas no modelo:

- a marca `<<ferramenta>>` (e os apelidos `<<tool>>`, `<<tool_call>>`, `<<chamada>>`) seguida
  de um JSON, em qualquer ponto do texto, partida entre deltas, com cerca ``` em volta;
- o JSON **sem a marca**, quando a primeira chave é `tool_id`, `tool` ou `ferramenta`;
- o bloco em XML do jeito nativo de chamar ferramenta (`<function_calls>`, `<invoke>`,
  `<tool_call>`, `<tool_use>`): a primeira `invoke` vira a proposta, o resto não é fala;
- o raciocínio `<<pensar>>` … `<</pensar>>` (ADR-0031), que sai como `Raciocinio`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.s2.motor import Delta, PedidoDeTool, Raciocinio, Texto

MARCA_DE_FERRAMENTA: Final = "<<ferramenta>>"
"""O protocolo de texto do provisório (ADR-0028): a CLI roda **sem** ferramenta nenhuma (ADR-0018),
então a proposta de chamada chega como uma linha que começa com esta marca e traz um JSON."""
MARCA_DE_RACIOCINIO: Final = "<<pensar>>"
FIM_DO_RACIOCINIO: Final = "<</pensar>>"
"""O canal de raciocínio do protocolo (ADR-0031): o que vem entre as duas marcas é do modelo para
ele mesmo, e sai do leitor como `Raciocinio`. Sem a marca que fecha, vale até a próxima proposta
ou o fim da geração — na dúvida, o texto não vai para a fala."""
APELIDOS_DA_MARCA: Final = ("ferramenta", "tool", "tool_call", "chamada")
CHAVES_DO_JSON: Final = ("tool_id", "tool", "ferramenta")
"""A primeira chave que faz de um objeto JSON solto uma proposta (o modelo esqueceu a marca)."""
ETIQUETAS_DE_BLOCO: Final = ("function_calls", "invoke", "tool_call", "tool_use")
LIMITE_DA_PROPOSTA: Final = 4000
"""Caracteres que uma proposta pode ocupar antes de virar malformada: JSON que nunca fecha não
pode segurar a fala do resto da resposta para sempre."""

_MARCA_RE: Final = re.compile(r"<<\s*(?:" + "|".join(APELIDOS_DA_MARCA) + r")\s*>>", re.I)
_JSON_RE: Final = re.compile(r"\{\s*\"(?:" + "|".join(CHAVES_DO_JSON) + r")\"\s*:", re.I)
_BLOCO_RE: Final = re.compile(r"<\s*(?:\w+:)?(" + "|".join(ETIQUETAS_DE_BLOCO) + r")\b[^>]*>", re.I)
_PENSAR_RE: Final = re.compile(r"<<\s*pensar\s*>>", re.IGNORECASE)
_FIM_DO_PENSAR_RE: Final = re.compile(r"<<\s*/\s*pensar\s*>>", re.IGNORECASE)
_CERCA_NO_FIM: Final = re.compile(r"```(?:json)?\s*$", re.IGNORECASE)
_CERCA_NO_COMECO: Final = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_INVOKE_RE: Final = re.compile(
    r"<\s*(?:\w+:)?invoke\s+name\s*=\s*\"([^\"]+)\"[^>]*>(.*?)<\s*/\s*(?:\w+:)?invoke\s*>",
    re.I | re.S,
)
_PARAMETRO_RE: Final = re.compile(
    r"<\s*(?:\w+:)?parameter\s+name\s*=\s*\"([^\"]+)\"[^>]*>(.*?)<\s*/\s*(?:\w+:)?parameter\s*>",
    re.I | re.S,
)
_INICIOS: Final = (
    *(f"<<{a}>>" for a in APELIDOS_DA_MARCA),
    MARCA_DE_RACIOCINIO,
    *(f'{{"{c}":' for c in CHAVES_DO_JSON),
    *(f"<{e}" for e in ETIQUETAS_DE_BLOCO),
)
"""Como o protocolo pode começar: um fim de texto que ainda pode ser o começo de um destes
espera o próximo delta antes de ir para a fala."""


def _malformado(bruto: str) -> PedidoDeTool:
    return PedidoDeTool("(malformado)", {"bruto": bruto.strip()[:200]})


def _pedido_de(objeto: object, bruto: str) -> PedidoDeTool:
    """O JSON já lido → pedido. Aceita os apelidos que o modelo usa por conta própria
    (`tool`/`name`, `arguments`): recusar por nome de chave é falha que o dono sente como erro."""
    if not isinstance(objeto, dict):
        return _malformado(bruto)
    ferramenta = next(
        (
            objeto[k]
            for k in ("tool_id", "tool", "ferramenta", "id", "name")
            if isinstance(objeto.get(k), str)
        ),
        None,
    )
    argumentos: object = next(
        (objeto[k] for k in ("args", "arguments", "argumentos", "input") if k in objeto), {}
    )
    if ferramenta is None or not isinstance(argumentos, dict):
        return _malformado(bruto)
    return PedidoDeTool(ferramenta, argumentos)


def _pedido_do_bloco(corpo: str) -> PedidoDeTool | None:
    """A primeira `invoke` (ou o JSON) de um bloco em XML; `None` = não há chamada nele."""
    invoke = _INVOKE_RE.search(corpo)
    if invoke is not None:
        argumentos: dict[str, object] = {}
        for nome, valor in _PARAMETRO_RE.findall(invoke.group(2)):
            try:
                argumentos[nome] = json.loads(valor.strip())
            except ValueError:
                argumentos[nome] = valor.strip()
        return PedidoDeTool(invoke.group(1).strip(), argumentos)
    inicio = corpo.find("{")
    if inicio < 0:
        return None
    try:
        objeto, _fim = json.JSONDecoder().raw_decode(corpo[inicio:])
    except ValueError:
        return _malformado(corpo)
    return _pedido_de(objeto, corpo)


@dataclass(slots=True)
class LeitorDoProtocolo:
    """Separa, ainda no stream, o texto falado das propostas de ferramenta.

    A marca vale **em qualquer ponto** do texto (não só no começo da linha): o modelo escreve
    "Vou abrir. <<ferramenta>> {...}" e o JSON não pode ir para a fala. O texto sai assim que
    se sabe que não é o começo de uma marca (só um `<`, um `{` ou uma cerca no fim ficam
    retidos). Depois da marca, o JSON é lido por **balanceamento** — vale em várias linhas, com
    cerca ``` em volta, com texto depois — e a proposta sai no instante em que o objeto fecha,
    sem esperar a quebra de linha nem o fim da geração. JSON que não fecha, ou sem objeto, vira
    um pedido malformado, que o executor recusa e o motor fica sabendo.

    O bloco `<<pensar>>` … `<</pensar>>` (ADR-0031) sai como `Raciocinio`, também no meio do
    texto e partido entre deltas. Uma proposta dentro de um raciocínio aberto fecha o raciocínio
    (o modelo esqueceu a marca de fim), e o que sobra aberto no fim da geração é raciocínio. O
    bloco em XML que não fecha também nunca é fala."""

    _texto: str = ""
    _proposta: str | None = None
    _raciocinio: str | None = None
    _bloco: tuple[str, str] | None = None
    """A etiqueta do bloco em XML aberto e o que veio dentro dele até aqui."""

    def alimentar(self, texto: str) -> Iterator[Delta]:
        while True:
            if self._proposta is not None:
                self._proposta += texto
                texto = ""
                lido = self._ler_proposta(final=False)
                if lido is None:
                    return
                pedido, resto = lido
                yield pedido
                self._proposta = None
                texto = resto
                if not texto:
                    return
                continue
            if self._bloco is not None:
                etiqueta, corpo = self._bloco
                corpo += texto
                texto = ""
                fim = re.search(rf"<\s*/\s*(?:\w+:)?{etiqueta}\s*>", corpo, re.I)
                if fim is None:
                    if len(corpo) > LIMITE_DA_PROPOSTA:
                        self._bloco = None
                        yield Raciocinio(corpo)  # nunca fecha: não é fala nem chamada
                    else:
                        self._bloco = (etiqueta, corpo)
                    return
                self._bloco = None
                achado = _pedido_do_bloco(corpo[: fim.end()])
                yield achado if achado is not None else Raciocinio(corpo[: fim.end()])
                texto = corpo[fim.end() :]
                if not texto:
                    return
                continue
            if self._raciocinio is not None:
                self._raciocinio += texto
                texto = ""
                fim = _FIM_DO_PENSAR_RE.search(self._raciocinio)
                proposta = _MARCA_RE.search(self._raciocinio)
                if fim is None and proposta is None:
                    retido = _retencao(self._raciocinio, (FIM_DO_RACIOCINIO, MARCA_DE_FERRAMENTA))
                    saida = self._raciocinio[: len(self._raciocinio) - retido]
                    self._raciocinio = self._raciocinio[len(self._raciocinio) - retido :]
                    if saida:
                        yield Raciocinio(saida)
                    return
                if fim is not None and (proposta is None or fim.start() < proposta.start()):
                    antes, texto = self._raciocinio[: fim.start()], self._raciocinio[fim.end() :]
                else:
                    assert proposta is not None
                    # A marca da proposta fica no texto: é o ramo do texto comum que a lê.
                    antes = self._raciocinio[: proposta.start()]
                    texto = self._raciocinio[proposta.start() :]
                self._raciocinio = None
                if antes:
                    yield Raciocinio(antes)
                if not texto:
                    return
                continue
            self._texto += texto
            texto = ""
            achados = [
                (m.start(), tipo)
                for tipo, m in (
                    ("marca", _MARCA_RE.search(self._texto)),
                    ("json", _JSON_RE.search(self._texto)),
                    ("bloco", _BLOCO_RE.search(self._texto)),
                    ("pensar", _PENSAR_RE.search(self._texto)),
                )
                if m is not None
            ]
            if not achados:
                retido = _retencao(self._texto, _INICIOS)
                saida = self._texto[: len(self._texto) - retido]
                self._texto = self._texto[len(self._texto) - retido :]
                if saida:
                    yield Texto(saida)
                return
            inicio, tipo = min(achados)
            antes = self._texto[:inicio]
            if tipo == "pensar":
                achada = _PENSAR_RE.search(self._texto)
                assert achada is not None
                texto = self._texto[achada.end() :]
                self._texto = ""
                self._raciocinio = ""
                if antes.strip():
                    yield Texto(antes)
                if not texto:
                    return
                continue
            antes = _CERCA_NO_FIM.sub("", antes)
            if tipo == "bloco":
                aberto = _BLOCO_RE.search(self._texto)
                assert aberto is not None
                self._bloco = (aberto.group(1), self._texto[aberto.start() :])
                self._texto = ""
                if antes.strip():
                    yield Texto(antes)
                continue
            if tipo == "marca":
                achada = _MARCA_RE.search(self._texto)
                assert achada is not None
                self._proposta = self._texto[achada.end() :]
            else:  # o JSON sem a marca: a proposta é o próprio objeto
                self._proposta = self._texto[inicio:]
            self._texto = ""
            if antes.strip():
                yield Texto(antes)
            lido = self._ler_proposta(final=False)
            if lido is None:
                return
            pedido, resto = lido
            yield pedido
            self._proposta = None
            texto = resto
            if not texto:
                return

    def fechar(self) -> Iterator[Delta]:
        if self._proposta is not None:
            lido = self._ler_proposta(final=True)
            self._proposta = None
            if lido is not None:
                yield lido[0]
        if self._bloco is not None:
            # Bloco em XML que não fechou: na dúvida, não é fala.
            _etiqueta, corpo = self._bloco
            self._bloco = None
            yield Raciocinio(corpo)
        if self._raciocinio is not None:
            # Sem a marca que fecha: na dúvida, não é fala.
            resto, self._raciocinio = self._raciocinio, None
            if resto:
                yield Raciocinio(resto)
        if self._texto:
            texto, self._texto = self._texto, ""
            yield Texto(texto)

    def _ler_proposta(self, *, final: bool) -> tuple[PedidoDeTool, str] | None:
        """O pedido e o que sobrou depois dele; `None` enquanto o JSON ainda pode fechar."""
        assert self._proposta is not None
        corpo = _CERCA_NO_COMECO.sub("", self._proposta).lstrip()
        if not corpo:
            if final:
                return _malformado(""), ""
            return None
        if not corpo.startswith("{"):
            linha, quebra, resto = corpo.partition("\n")
            if not quebra and not final:
                return None
            return _malformado(linha), resto
        try:
            objeto, fim = json.JSONDecoder().raw_decode(corpo)
        except ValueError:
            if final or len(corpo) > LIMITE_DA_PROPOSTA:
                return _malformado(corpo), ""
            return None
        resto = corpo[fim:]
        if resto.lstrip().startswith("```"):  # a cerca que fecha o bloco não é fala
            resto = resto.lstrip()[3:]
        return _pedido_de(objeto, corpo[:fim]), resto


def _retencao(texto: str, inicios: Sequence[str]) -> int:
    """Quantos caracteres do fim ainda podem ser o começo do protocolo (e por isso esperam).

    Compara sem espaço nem caixa (`{ "tool_id"` é `{"tool_id"`); a cerca ``` logo antes do que
    espera também espera — senão ela iria para a fala e o JSON, não."""
    retido = 0
    for tamanho in range(min(len(texto), max(len(m) for m in inicios) + 8), 0, -1):
        cauda = texto[-tamanho:]
        compacta = re.sub(r"\s", "", cauda.lower())
        if cauda[0] in "<{" and compacta and any(m.startswith(compacta) for m in inicios):
            retido = tamanho
            break
    cerca = re.search(r"`{1,3}(?:json)?\s*$", texto[: len(texto) - retido], re.I)
    if cerca is not None:
        retido = len(texto) - cerca.start()
    return retido


def sem_protocolo(texto: str) -> str:
    """O texto pronto (não em stream) sem nada do protocolo: o que sobra é só fala.

    A última barreira antes da voz para texto que não passou por um leitor (o resultado de uma
    tarefa, um aviso montado a partir dele)."""
    leitor = LeitorDoProtocolo()
    deltas = [*leitor.alimentar(texto), *leitor.fechar()]
    fala = "".join(d.texto for d in deltas if isinstance(d, Texto))
    return " ".join(fala.split())
