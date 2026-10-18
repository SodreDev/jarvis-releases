"""As regras de memória que o código decide, não o modelo (ADR-0026, regras 1–3, 7 e 8).

Quatro perguntas, todas determinísticas e sem LLM (P1):

1. **Há episódio de origem?** Escrita de memória sem o turno corrente do dono como origem é
   negada (regra 2). O turno vem do `s2`, que o gravou — nunca de argumento do modelo.
2. **A fonte é o dono?** A regra 3 da ADR dizia "fala estável do dono no turno corrente **e** o
   dono pediu". "Pediu" não se decide por código sem virar mapa de frase (P2). O que o código
   confere é a **proveniência do conteúdo**: a memória nasce `active` só se o que vai ser gravado
   (o texto; o nome da entidade; os dois nomes da relação) **está na fala estável do dono neste
   turno**. O modelo julga se o dono quis que lembrasse; a política garante que o que fica ativo
   são palavras dele. Paráfrase, inferência e conteúdo de terceiro nascem `proposed`.
3. **É escrita por iniciativa do Jarvis?** `proposed` sem fonte do dono é a escrita autônoma da
   §6.6 — negada até os seis gates passarem (`escrita_autonoma_liberada`, fatia M4).
4. **Pode ir para este motor?** (D20) `sensitive` nunca vai para motor de nuvem; histórico só vai
   se o dono ligou, por motor, e vem desligado.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from jarvis.voz.interface import Onde

FAMILIA: Final = "memoria."
LEITURAS_DE_HISTORICO: Final[frozenset[str]] = frozenset(
    {"memoria.buscar_historico", "memoria.ler_mensagem"}
)
ESCRITAS_COM_FONTE: Final[frozenset[str]] = frozenset(
    {"memoria.lembrar", "memoria.criar_no", "memoria.criar_aresta"}
)
"""As que criam memória nova: é aqui que a fonte decide `active` × `proposed`."""
ESCRITAS_CONFIRMADAS: Final[frozenset[str]] = frozenset(
    {"memoria.atualizar", "memoria.retratar", "memoria.apagar"}
)
"""As que mudam o que o Jarvis já sabe: sempre confirmam (regra 4), pelo manifesto."""
ESCRITAS: Final = ESCRITAS_COM_FONTE | ESCRITAS_CONFIRMADAS
TRUST_DO_DONO: Final[frozenset[str]] = frozenset({"user_voice", "user_ui"})
PALAVRAS_MINIMAS_DO_TEXTO: Final = 2
"""Uma palavra solta ("sim") casaria com quase qualquer turno; duas já é trecho do dono."""
CLASSE_SENSIVEL: Final = "sensitive"


class Estado(StrEnum):
    ATIVA = "active"
    PROPOSTA = "proposed"


@dataclass(frozen=True, slots=True)
class TurnoCorrente:
    """O turno estável do dono, como o `s2` o gravou no histórico."""

    episode_id: str
    texto: str
    trust: str


@dataclass(frozen=True, slots=True)
class Proveniencia:
    """De onde vem a escrita. Montada pelo `s2` a partir do estado dele, nunca do modelo."""

    turno: TurnoCorrente | None
    motor: str = ""
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class AlcanceDeMemoria:
    """ADR-0026, regra 7: escolhido pelo dono na UI, por nenhuma tool e nenhuma frase (P12)."""

    historico: bool = True
    sensivel: bool = False
    historico_na_nuvem: frozenset[str] = frozenset()
    """D20: os motores (pelo nome) para os quais o dono ligou o histórico. Vazio por padrão."""


@dataclass(frozen=True, slots=True)
class RegraDeMemoria:
    veredito: str
    """`allow`, `deny` ou (só nas regras de abertura) `confirm`. Na memória, o `confirm` fica com
    o tier do manifesto, pelo caminho comum do PDP."""
    motivo: str


def normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.findall(r"\w+", sem_acento.casefold()))


def _na_fala(trecho: str, fala: str, *, minimo: int = 1) -> bool:
    alvo = normalizar(trecho)
    if len(alvo.split()) < minimo:
        return False
    return f" {alvo} " in f" {normalizar(fala)} "


def estado_da_escrita(
    tool_id: str, args: Mapping[str, Any], proveniencia: Proveniencia | None
) -> Estado:
    """`active` só se o conteúdo for fala estável do dono neste turno; senão `proposed`."""
    turno = proveniencia.turno if proveniencia is not None else None
    if turno is None or turno.trust not in TRUST_DO_DONO:
        return Estado.PROPOSTA
    if tool_id == "memoria.lembrar":
        dele = _na_fala(str(args.get("texto", "")), turno.texto, minimo=PALAVRAS_MINIMAS_DO_TEXTO)
    elif tool_id == "memoria.criar_no":
        dele = _na_fala(str(args.get("nome", "")), turno.texto)
    elif tool_id == "memoria.criar_aresta":
        dele = _na_fala(str(args.get("origem", "")), turno.texto) and _na_fala(
            str(args.get("destino", "")), turno.texto
        )
    else:
        dele = True  # as confirmadas: o dono confirma o resultado, a fonte é o turno do pedido
    return Estado.ATIVA if dele else Estado.PROPOSTA


def decidir_memoria(
    tool_id: str,
    args: Mapping[str, Any],
    proveniencia: Proveniencia | None,
    *,
    alcance: AlcanceDeMemoria,
    escrita_autonoma_liberada: bool,
) -> RegraDeMemoria | None:
    """O que a política de memória decide antes da matriz comum. `None` = siga o comum."""
    if not tool_id.startswith(FAMILIA):
        return None
    if tool_id in LEITURAS_DE_HISTORICO and not alcance.historico:
        return RegraDeMemoria("deny", "o dono desligou o alcance de histórico (ADR-0026, regra 7)")
    if tool_id not in ESCRITAS:
        return None
    if proveniencia is None or proveniencia.turno is None:
        return RegraDeMemoria(
            "deny", "escrita de memória sem episódio de origem (ADR-0026, regra 2)"
        )
    if tool_id in ESCRITAS_CONFIRMADAS:
        return None
    if estado_da_escrita(tool_id, args, proveniencia) is Estado.ATIVA:
        return RegraDeMemoria(
            "allow",
            "grant de turno: o conteúdo é fala estável do dono neste turno (ADR-0026, regra 3)",
        )
    if escrita_autonoma_liberada:
        return RegraDeMemoria("allow", "proposta por iniciativa do Jarvis, gates da §6.6 aprovados")
    return RegraDeMemoria(
        "deny",
        "escrita por iniciativa do Jarvis só depois dos gates da §6.6 (ADR-0026, fatia M4)",
    )


def pode_ir_para_motor(
    pii_class: str,
    *,
    do_historico: bool,
    onde: Onde,
    motor: str,
    alcance: AlcanceDeMemoria,
) -> bool:
    """D20: o que uma tool de memória devolve pode entrar no contexto deste motor?"""
    if pii_class == CLASSE_SENSIVEL and not alcance.sensivel:
        return False
    if onde is Onde.LOCAL:
        return True
    if pii_class == CLASSE_SENSIVEL:
        return False  # sensível nunca vai para nuvem, nem com o alcance ligado
    return not do_historico or motor in alcance.historico_na_nuvem
