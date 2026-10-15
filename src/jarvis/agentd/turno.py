"""Detector de turno: quando calar. Duas implementações e uma curva (cartão F1-07).

**O que se otimiza é a curva, não um número** (SPEC §7). Decidir cedo reduz o atraso e aumenta
o falso corte; decidir tarde faz o contrário. Então existem duas implementações atrás da mesma
interface, medidas no mesmo corpus, com os mesmos itens (A/B **pareado**):

- `silencio_fixo` — limiar de silêncio em ms. É o **controle honesto**: simples, explicável, e
  por construção não consegue decidir antes de o silêncio acontecer;
- `semantico` — `p_eot` de um classificador **nosso**, treinado **só no corpus do projeto**
  (regressão logística sobre traços de texto e de pausa). Nada de modelo CC-BY-NC entra aqui, e
  nenhum peso vem de fora: os pesos são gerados por `tools/curva_turno.py --treinar` a partir
  do split `calibracao` e ficam versionados em `pesos_turno.json`.

**Definições, escritas antes de medir** (mudar depois de ver o resultado é escolher o número):

- **falso corte** — o detector diz `yield` **durante** a pausa de um item em que o dono ia
  continuar (`fim_de_turno: false`). Taxa = falsos cortes ÷ itens de meio de frase;
- **atraso** — para itens de fim de turno, milissegundos entre o **início da pausa** e o
  `yield`. É a métrica do SLO-4 (§7: p50 ≤ 120 ms, p95 ≤ 250 ms). Item que não decide dentro da
  pausa disponível entra em coluna própria ("não decidiu") e **fica fora** dos percentis;
- **`unknown` nunca vira `yield`** — sem confiança, não interrompe. É aceite (c) do cartão e
  está em teste.

**Regra de empate, do cartão, aplicada por código e não por prosa no fim do relatório:** o
detector semântico só entra no v1 se, **no mesmo atraso**, reduzir o falso corte, **ou**, no
**mesmo falso corte**, reduzir o atraso. Empate dentro do intervalo de confiança → fica o
`silencio_fixo`, que é mais simples e mais explicável.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from jarvis.barramento.contrato import validar
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.corpus.metricas import palavras

ARQUIVO_PESOS: Final = Path(__file__).resolve().parent / "pesos_turno.json"
LIMIAR_PADRAO_MS: Final = 700.0
"""Limiar do controle. Fica no meio da faixa de pausa de fim de turno do corpus (300-900 ms)."""
P_EOT_PADRAO: Final = 0.5
CONFIANCA_MINIMA: Final = 0.15
"""Abaixo desta distância do limiar, a previsão é `unknown` — e `unknown` não interrompe."""

PALAVRAS_QUE_NAO_FECHAM: Final[frozenset[str]] = frozenset(
    {
        # Preposições, artigos e conjunções: ninguém termina um pedido nelas.
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "na",
        "no",
        "nas",
        "nos",
        "para",
        "pra",
        "por",
        "com",
        "sem",
        "sobre",
        "até",
        "a",
        "o",
        "as",
        "os",
        "um",
        "uma",
        "e",
        "ou",
        "que",
        "antes",
        "depois",
        "junto",
        "só",
        "mais",
        "menos",
        "muito",
        "meu",
        "minha",
        "seu",
    }
)
VERBOS_DE_PEDIDO: Final[frozenset[str]] = frozenset(
    {
        "abre",
        "fecha",
        "renomeia",
        "duplica",
        "compacta",
        "toca",
        "pausa",
        "abaixa",
        "adianta",
        "repete",
        "marca",
        "adia",
        "confirma",
        "cancela",
        "lembra",
        "liga",
        "desliga",
        "manda",
        "move",
        "copia",
        "apaga",
        "mostra",
        "procura",
    }
)


class Decisao(StrEnum):
    """O vocabulário da §3.2 para `TurnPrediction.decision`."""

    HOLD = "hold"
    YIELD = "yield"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Contexto:
    """O que o detector vê no instante da decisão."""

    pausa_ms: float
    texto: str = ""
    estabilidade: float = 1.0
    vad_falando: bool = False

    def tracos(self) -> dict[str, float]:
        """Traços do classificador. São poucos e nomeados de propósito: dá para explicar."""
        termos = palavras(self.texto)
        ultima = termos[-1] if termos else ""
        primeira = termos[0] if termos else ""
        return {
            "pausa_s": self.pausa_ms / 1000.0,
            "palavras": min(len(termos), 12) / 12.0,
            "termina_em_palavra_aberta": 1.0 if ultima in PALAVRAS_QUE_NAO_FECHAM else 0.0,
            "comeca_com_verbo": 1.0 if primeira in VERBOS_DE_PEDIDO else 0.0,
            "estabilidade": self.estabilidade,
        }


@dataclass(frozen=True, slots=True)
class Previsao:
    """`p_eot` e a decisão que sai dele."""

    p_eot: float
    detector: str
    decisao: Decisao

    def envelope(self, *, session_id: str, epoch: int) -> Envelope:
        return validar(
            Envelope(
                session_id=session_id,
                epoch=epoch,
                source="agentd",
                trust=Trust.SYSTEM,
                priority=Prioridade.P1,
                type=Tipo.TURN_PREDICTION,
                payload={
                    "p_eot": round(self.p_eot, 4),
                    "detector": self.detector,
                    "decision": str(self.decisao),
                },
            )
        )


@runtime_checkable
class DetectorDeTurno(Protocol):
    """Decide ceder o turno. Não decide **o que** dizer (isso é o `s2`)."""

    nome: str

    def prever(self, contexto: Contexto) -> Previsao: ...


def _decidir(p_eot: float, limiar: float, detector: str) -> Previsao:
    """`yield` acima do limiar, `hold` abaixo, `unknown` na vizinhança — que nunca interrompe."""
    if abs(p_eot - limiar) < CONFIANCA_MINIMA:
        return Previsao(p_eot=p_eot, detector=detector, decisao=Decisao.UNKNOWN)
    decisao = Decisao.YIELD if p_eot >= limiar else Decisao.HOLD
    return Previsao(p_eot=p_eot, detector=detector, decisao=decisao)


@dataclass(slots=True)
class SilencioFixo:
    """O controle: o turno acabou quando o silêncio passou do limiar. Nada de texto."""

    limiar_ms: float = LIMIAR_PADRAO_MS
    nome: str = "silencio_fixo"

    def prever(self, contexto: Contexto) -> Previsao:
        # p_eot cresce linearmente até o limiar para a curva ter um eixo contínuo; a decisão,
        # porém, é a do controle: silêncio suficiente ou não.
        p_eot = min(1.0, contexto.pausa_ms / self.limiar_ms) if self.limiar_ms > 0 else 1.0
        decisao = Decisao.YIELD if contexto.pausa_ms >= self.limiar_ms else Decisao.HOLD
        return Previsao(p_eot=p_eot, detector=self.nome, decisao=decisao)


@dataclass(slots=True)
class Semantico:
    """Regressão logística sobre traços de texto e pausa, treinada só no corpus do projeto."""

    pesos: dict[str, float] = field(default_factory=dict)
    vies: float = 0.0
    limiar: float = P_EOT_PADRAO
    nome: str = "semantico"
    treinado_em: str = ""

    @classmethod
    def do_arquivo(
        cls, caminho: Path = ARQUIVO_PESOS, *, limiar: float = P_EOT_PADRAO
    ) -> Semantico:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return cls(
            pesos={str(k): float(v) for k, v in dados["pesos"].items()},
            vies=float(dados["vies"]),
            limiar=limiar,
            treinado_em=str(dados.get("treinado_em", "")),
        )

    def p_eot(self, contexto: Contexto) -> float:
        z = self.vies + sum(
            self.pesos.get(nome, 0.0) * valor for nome, valor in contexto.tracos().items()
        )
        return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))

    def prever(self, contexto: Contexto) -> Previsao:
        return _decidir(self.p_eot(contexto), self.limiar, self.nome)


def gravar_pesos(
    caminho: Path, *, pesos: dict[str, float], vies: float, treinado_em: str, n: int
) -> None:
    """Os pesos são **dado**, gerados pelo treino e versionados — nunca editados à mão."""
    caminho.write_text(
        json.dumps(
            {
                "descricao": (
                    "Pesos do detector semântico de turno (cartão F1-07). Gerados por "
                    "`tools/curva_turno.py --treinar` no split `calibracao`; não editar à mão."
                ),
                "treinado_em": treinado_em,
                "n": n,
                "vies": vies,
                "pesos": pesos,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
