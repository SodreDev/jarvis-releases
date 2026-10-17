"""O corpo das tools `memoria.*`: só roda com a decisão do PDP, e o que devolve passa pelo D20.

A ordem é a do executor (§2): **decisão** (`allow`, ou `confirm` com a confirmação do dono) →
**schema** do manifesto (o `input_schema` inteiro, não só os nomes) → **efeito** no livro →
**saída filtrada** para o motor que vai lê-la. O estado da escrita (`active` × `proposed`) sai da
mesma função que o PDP usou (`estado_da_escrita`), para os dois nunca divergirem.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from jarvis.manifesto.validador import PASTA_CATALOGO, carregar_manifesto
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.politica.memoria import (
    LEITURAS_DE_HISTORICO,
    AlcanceDeMemoria,
    Proveniencia,
    estado_da_escrita,
    pode_ir_para_motor,
)
from jarvis.politica.pdp import Decisao, Veredito
from jarvis.voz.interface import Onde


class NaoAutorizado(PermissionError):
    """A chamada não tem a decisão que a autoriza: nada é executado."""


@dataclass(frozen=True, slots=True)
class Chamada:
    tool_id: str
    args: Mapping[str, Any]
    decisao: Decisao
    proveniencia: Proveniencia | None = None
    confirmado: bool = False
    """O dono confirmou na UI (ou por voz, onde a §5.3 permite) — só conta com `confirm`."""
    destino_onde: Onde = Onde.LOCAL
    destino_motor: str = ""
    """O motor de conversa que vai ler o resultado: é contra ele que o D20 decide."""


def _manifestos() -> dict[str, dict[str, Any]]:
    return {
        str(m["id"]): m
        for m in (carregar_manifesto(a) for a in sorted(PASTA_CATALOGO.glob("memoria.*.yaml")))
    }


@dataclass(slots=True)
class FerramentasDeMemoria:
    livro: LivroDeMemoria
    alcance: AlcanceDeMemoria = field(default_factory=AlcanceDeMemoria)
    manifestos: dict[str, dict[str, Any]] = field(default_factory=_manifestos)

    def executar(self, chamada: Chamada) -> dict[str, Any]:
        manifesto = self.manifestos.get(chamada.tool_id)
        if manifesto is None:
            raise NaoAutorizado(f"{chamada.tool_id} não é tool de memória do catálogo")
        self._autorizar(chamada)
        args = dict(chamada.args)
        jsonschema.validate(args, manifesto["input_schema"])
        stub = importlib.import_module("jarvis.capacidades." + chamada.tool_id.replace(".", "_"))
        stub.validar_entrada(args)
        corpo: Callable[[Chamada, dict[str, Any]], dict[str, Any]] = getattr(
            self, "_" + chamada.tool_id.split(".", 1)[1]
        )
        return corpo(chamada, args)

    # --- autorização ---------------------------------------------------------------------
    def _autorizar(self, chamada: Chamada) -> None:
        decisao = chamada.decisao
        if decisao.veredito is Veredito.DENY:
            raise NaoAutorizado(f"o PDP negou: {decisao.motivo}")
        if decisao.veredito is Veredito.CONFIRM and not chamada.confirmado:
            raise NaoAutorizado(f"precisa da confirmação do dono: {decisao.motivo}")
        if decisao.grant is not None and decisao.grant.tool_id != chamada.tool_id:
            raise NaoAutorizado("o grant é de outra tool")

    def _fonte(self, chamada: Chamada) -> tuple[str, str]:
        proveniencia = chamada.proveniencia
        if proveniencia is None or proveniencia.turno is None:
            raise NaoAutorizado("escrita de memória sem episódio de origem (ADR-0026, regra 2)")
        return proveniencia.turno.episode_id, f"s2:{proveniencia.motor or 'desconhecido'}"

    # --- D20 na saída --------------------------------------------------------------------
    def _para_o_motor(self, chamada: Chamada, itens: list[dict[str, Any]]) -> dict[str, Any]:
        do_historico = chamada.tool_id in LEITURAS_DE_HISTORICO
        liberados = [
            item
            for item in itens
            if pode_ir_para_motor(
                str(item.get("pii_class", "none")),
                do_historico=do_historico,
                onde=chamada.destino_onde,
                motor=chamada.destino_motor,
                alcance=self.alcance,
            )
        ]
        saida: dict[str, Any] = {"achados": liberados}
        if len(liberados) < len(itens):
            saida["omitidos"] = len(itens) - len(liberados)
            saida["motivo_da_omissao"] = (
                "classe de dado que não vai para este motor (D20: sensível nunca vai para a "
                "nuvem; histórico só se o dono ligou para este motor)"
            )
        if not liberados:
            saida["resposta"] = "não encontrei evidência"
        return saida

    # --- leituras ------------------------------------------------------------------------
    def _buscar_historico(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        itens = self.livro.buscar_historico(
            args["consulta"], desde=args.get("desde"), ate=args.get("ate"), k=args.get("k", 5)
        )
        return self._para_o_motor(chamada, itens)

    def _ler_mensagem(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        turnos = self.livro.ler_mensagem(args["episode_id"], vizinhos=args.get("vizinhos", 2))
        filtrado = self._para_o_motor(chamada, turnos)
        return {"turnos": filtrado.pop("achados"), **filtrado}

    def _buscar(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        return self._para_o_motor(
            chamada, self.livro.buscar(args["consulta"], instante=args.get("instante"))
        )

    # --- escritas ------------------------------------------------------------------------
    def _lembrar(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        fonte, extrator = self._fonte(chamada)
        estado = estado_da_escrita(chamada.tool_id, args, chamada.proveniencia)
        return self.livro.lembrar(
            args["texto"],
            estado=estado,
            fonte=fonte,
            extrator=extrator,
            sujeito=args.get("sujeito"),
            predicado=args.get("predicado"),
        )

    def _atualizar(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        fonte, _ = self._fonte(chamada)
        return self.livro.atualizar(
            args["assertion_id"], args["texto"], motivo=args["motivo"], fonte=fonte
        )

    def _criar_no(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        fonte, extrator = self._fonte(chamada)
        return self.livro.criar_no(
            args["tipo"],
            args["nome"],
            apelidos=args.get("apelidos", ()),
            estado=estado_da_escrita(chamada.tool_id, args, chamada.proveniencia),
            fonte=fonte,
            extrator=extrator,
        )

    def _criar_aresta(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        fonte, extrator = self._fonte(chamada)
        return self.livro.criar_aresta(
            args["origem"],
            args["relacao"],
            args["destino"],
            estado=estado_da_escrita(chamada.tool_id, args, chamada.proveniencia),
            fonte=fonte,
            extrator=extrator,
            desde=args.get("desde"),
            ate=args.get("ate"),
        )

    def _retratar(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        self._fonte(chamada)
        return self.livro.retratar(args["alvo_id"])

    def _apagar(self, chamada: Chamada, args: dict[str, Any]) -> dict[str, Any]:
        self._fonte(chamada)
        return {"removidos": self.livro.apagar(args["alvo_id"], args["escopo"])}
