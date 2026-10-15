"""A curva falso corte × atraso, com A/B pareado e a regra de empate aplicada (cartão F1-07).

    # 1. texto do ASR no instante do corte (precisa do grupo `asr`; cacheado e publicado)
    uv run --frozen python tools/curva_turno.py --preparar-texto

    # 2. treina o classificador semântico SÓ no split `calibracao`
    uv run --frozen python tools/curva_turno.py --treinar

    # 3. varre limiares, publica a curva e aplica a regra de empate
    uv run --frozen python tools/curva_turno.py

**O que este cartão NÃO fecha.** A curva aqui é sobre corpus **sintético**: serve para
**ordenar candidatos** e **pegar regressão**. O aceite (d) da F1 — curva publicada no corpus
real, na máquina do dono — é F1-15 + F1-16. Apresentar esta curva como aceite da fase é motivo
de recusa na revisão, e está escrito no relatório gerado.

**Definições (escritas antes de medir, em `jarvis.agentd.turno`):** falso corte é `yield`
durante a pausa de um item de meio de frase; atraso é o tempo entre o início da pausa e o
`yield` em itens de fim de turno (métrica do SLO-4); item que não decide dentro da pausa
gravada entra em "não decidiu" e fica fora dos percentis.

**Critério de escolha do ponto de operação (declarado antes):** no split `calibracao`, para
cada detector, escolhe-se o limiar de **menor atraso p50 entre os que têm falso corte ≤ 3%**
(o alvo [SUPOSIÇÃO] do SLO-9). Se nenhum limiar alcança 3%, escolhe-se o de **menor falso
corte**. O número publicado sai do split `retido`, com intervalo de confiança por *bootstrap*.

**Regra de empate (do cartão, aplicada por código):** o semântico entra no v1 só se **não for
pior** em nenhuma das duas dimensões (dentro do IC) e for **estritamente melhor** em pelo menos
uma (fora do IC). Empate dentro do IC → fica o `silencio_fixo`.

**Âncoras externas são âncoras, não metas nossas** (aceite (d)): o Semantic VAD de 2023 relata
−53,3% de latência média em conjunto interno; o Voice-Light relata recall de EOT aprendido de
12,53% contra 95,60% do Silero (relatório 01). Números de outro conjunto, outro idioma e outra
definição de corte — servem para situar, não para comparar com os nossos.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.agentd.asr import MotorWhisper
from jarvis.agentd.turno import (
    ARQUIVO_PESOS,
    Contexto,
    Decisao,
    DetectorDeTurno,
    Semantico,
    SilencioFixo,
    gravar_pesos,
)
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, MS_POR_QUADRO, TAXA_PADRAO
from jarvis.corpus.metricas import wer
from jarvis.corpus.rotulos import Rotulo, ler_rotulos
from jarvis.medicao import hardware, percentil

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
CORPUS_PADRAO: Final = RAIZ / "corpus" / "turnos"
ARQUIVO_TEXTO: Final = PASTA_SAIDA / "f1-07-texto-no-corte.csv"
PASTA_WHISPER: Final = Path.home() / ".cache" / "jarvis" / "modelos" / "whisper"
ALVO_SLO9: Final = 0.03
"""SLO-9 da SPEC §7: ≤ 3% de falso corte — marcado lá como [SUPOSIÇÃO] a recalibrar na F1."""
SLO4_P50_MS: Final = 120.0
SLO4_P95_MS: Final = 250.0
LIMIARES_SILENCIO_MS: Final[tuple[float, ...]] = (
    100.0,
    200.0,
    300.0,
    400.0,
    500.0,
    600.0,
    700.0,
    800.0,
    900.0,
    1000.0,
    1200.0,
)
LIMIARES_P_EOT: Final[tuple[float, ...]] = (
    0.20,
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
    0.80,
    0.90,
    0.95,
)
DECISAO_MINIMA: Final = 0.5
"""Fração mínima de itens de fim de turno que o limiar tem de decidir para ser candidato.

Sem esta guarda, "nunca ceder" ganha a comparação: falso corte zero, atraso vazio. Declarada
antes de medir, junto com o resto do critério."""
REAMOSTRAGENS: Final = 1000
SEMENTE_BOOTSTRAP: Final = 20_261_015


@dataclass(frozen=True, slots=True)
class Ponto:
    """Um ponto da curva: um detector num limiar, medido num split."""

    detector: str
    limiar: float
    split: str
    itens_fim: int
    itens_meio: int
    falsos_cortes: int
    nao_decidiu: int
    atrasos_ms: tuple[float, ...]

    @property
    def falso_corte(self) -> float:
        return self.falsos_cortes / self.itens_meio if self.itens_meio else 0.0

    @property
    def atraso_p50(self) -> float:
        return percentil(list(self.atrasos_ms), 50)

    @property
    def atraso_p95(self) -> float:
        return percentil(list(self.atrasos_ms), 95)

    @property
    def decidiu(self) -> int:
        return len(self.atrasos_ms)


@dataclass(frozen=True, slots=True)
class Intervalo:
    """Intervalo de confiança de 95% por *bootstrap* (percentis 2,5 e 97,5)."""

    estimativa: float
    inferior: float
    superior: float

    def sobrepoe(self, outro: Intervalo) -> bool:
        return self.inferior <= outro.superior and outro.inferior <= self.superior

    def __str__(self) -> str:
        return f"{self.estimativa:.3f} [{self.inferior:.3f}; {self.superior:.3f}]"


def ler_wav(caminho: Path) -> bytes:
    with wave.open(str(caminho), "rb") as arquivo:
        return arquivo.readframes(arquivo.getnframes())


# --- texto do ASR no instante do corte ------------------------------------------------
def preparar_texto(corpus: Path, saida: Path, *, itens: int | None = None) -> int:
    """Transcreve `[0, inicio_pausa)` de cada item e publica o cache. **Retomável.**

    Por que cachear: a curva precisa do texto que o ASR **de verdade** produziu no instante do
    corte — usar o texto do rótulo seria dar ao detector semântico um ASR perfeito. E rodar o
    whisper dentro de cada varredura de limiar custaria horas. O cache é publicado junto com a
    medição para a curva ser reproduzível sem o modelo.

    Por que retomável: 500 transcrições levam ~15 min, e um `uv run` disparado em paralelo
    reinstala o pacote e derruba o processo no meio (aconteceu duas vezes neste cartão). Com a
    retomada, o trabalho perdido é um item, não a medição inteira. Cada linha é gravada e
    descarregada na hora, para o arquivo nunca ficar "cheio por metade" sem ninguém saber.
    """
    rotulos = [r for r in ler_rotulos(corpus / "rotulos.jsonl") if r.sintetico]
    if itens is not None:
        rotulos = rotulos[:itens]
    prontos = _sanear_cache(saida, {r.id for r in rotulos})
    faltando = [r for r in rotulos if r.id not in prontos]
    if not faltando:
        return len(rotulos)

    motor = MotorWhisper(tamanho="small", pasta=str(PASTA_WHISPER))
    motor.abrir()
    saida.parent.mkdir(parents=True, exist_ok=True)
    novo_arquivo = not prontos
    with saida.open("a" if prontos else "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        if novo_arquivo:
            escritor.writerow(["item", "modelo", "texto_no_corte", "texto_antes", "wer"])
        for feitos, rotulo in enumerate(faltando, start=1):
            amostras = ler_wav(corpus / rotulo.arquivo)
            corte = int(TAXA_PADRAO * rotulo.inicio_pausa_ms / 1000) * BYTES_POR_AMOSTRA
            texto, _ = motor.transcrever(amostras[:corte])
            escritor.writerow(
                [
                    rotulo.id,
                    motor.modelo,
                    texto,
                    rotulo.texto_antes,
                    f"{wer(rotulo.texto_antes, texto).taxa:.4f}",
                ]
            )
            arquivo.flush()
            if feitos % 25 == 0:
                print(f"  {len(prontos) + feitos}/{len(rotulos)}", flush=True)
    return len(rotulos)


def _sanear_cache(arquivo: Path, ids_validos: set[str]) -> dict[str, str]:
    """Lê o cache descartando linha malformada e reescreve ordenado, antes de retomar.

    Por que existe: um processo morto **no meio de uma linha** deixa meia linha no arquivo, e a
    retomada em modo `append` completa essa meia linha com os campos do item seguinte — nasce
    uma linha que parece dado válido e não é (vi uma com `item="ha."`). Sanear na retomada é
    mais barato do que descobrir isso depois, numa tabela publicada.
    """
    if not arquivo.exists() or not arquivo.stat().st_size:
        return {}
    with arquivo.open(encoding="utf-8") as f:
        linhas = [
            linha
            for linha in csv.DictReader(f)
            if linha.get("item") in ids_validos and (linha.get("texto_no_corte") or "").strip()
        ]
    unicos: dict[str, dict[str, str]] = {}
    for linha in linhas:
        unicos.setdefault(str(linha["item"]), {str(k): str(v) for k, v in linha.items()})
    with arquivo.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(
            f, fieldnames=["item", "modelo", "texto_no_corte", "texto_antes", "wer"]
        )
        escritor.writeheader()
        escritor.writerows(unicos[chave] for chave in sorted(unicos))
    return {chave: unicos[chave]["texto_no_corte"] for chave in sorted(unicos)}


def ler_texto(arquivo: Path) -> dict[str, str]:
    with arquivo.open(encoding="utf-8") as f:
        return {linha["item"]: linha["texto_no_corte"] for linha in csv.DictReader(f)}


# --- simulação da decisão -------------------------------------------------------------
def simular(detector: DetectorDeTurno, rotulo: Rotulo, texto: str) -> float | None:
    """Varre a pausa de 20 em 20 ms e devolve quando o detector cedeu (ou `None`)."""
    for passo_ms in range(0, int(rotulo.pausa_ms) + 1, MS_POR_QUADRO):
        previsao = detector.prever(
            Contexto(pausa_ms=float(passo_ms), texto=texto, estabilidade=1.0)
        )
        if previsao.decisao is Decisao.YIELD:
            return float(passo_ms)
    return None


def medir_ponto(
    detector: DetectorDeTurno,
    limiar: float,
    rotulos: Sequence[Rotulo],
    textos: dict[str, str],
    *,
    split: str,
) -> Ponto:
    atrasos: list[float] = []
    falsos = 0
    nao_decidiu = 0
    fins = meios = 0
    for rotulo in rotulos:
        quando = simular(detector, rotulo, textos.get(rotulo.id, ""))
        if rotulo.fim_de_turno:
            fins += 1
            if quando is None:
                nao_decidiu += 1
            else:
                atrasos.append(quando)
        else:
            meios += 1
            if quando is not None:
                falsos += 1
    return Ponto(
        detector=detector.nome,
        limiar=limiar,
        split=split,
        itens_fim=fins,
        itens_meio=meios,
        falsos_cortes=falsos,
        nao_decidiu=nao_decidiu,
        atrasos_ms=tuple(atrasos),
    )


def detectores(limiar: float, *, semantico: Semantico | None) -> list[tuple[DetectorDeTurno, str]]:
    lista: list[tuple[DetectorDeTurno, str]] = [(SilencioFixo(limiar_ms=limiar), "ms")]
    if semantico is not None:
        lista.append((Semantico(pesos=semantico.pesos, vies=semantico.vies, limiar=limiar), "p"))
    return lista


# --- treino do classificador ----------------------------------------------------------
def exemplos_de_treino(
    rotulos: Sequence[Rotulo], textos: dict[str, str]
) -> tuple[list[dict[str, float]], list[float]]:
    """Um exemplo por instante de decisão: traços no instante `t`, rótulo = era fim de turno."""
    tracos: list[dict[str, float]] = []
    alvos: list[float] = []
    for rotulo in rotulos:
        texto = textos.get(rotulo.id, "")
        for passo_ms in range(100, int(rotulo.pausa_ms) + 1, 100):
            tracos.append(
                Contexto(pausa_ms=float(passo_ms), texto=texto, estabilidade=1.0).tracos()
            )
            alvos.append(1.0 if rotulo.fim_de_turno else 0.0)
    return tracos, alvos


TRACOS_MONOTONOS: Final[frozenset[str]] = frozenset({"pausa_s"})
"""Traços cujo peso é forçado a ser ≥ 0: esperar mais nunca pode reduzir `p_eot`.

Sem esta restrição o classificador aprende a **inversão do corpus sintético** (lá, pausa acima
de 900 ms só existe em meio de frase, porque fomos nós que escolhemos as faixas) e o detector
vira um degrau: cede no instante zero ou nunca cede. Monotonia na pausa é propriedade do
fenômeno, não do corpus — e por isso entra como restrição do modelo, declarada, em vez de ser
"descoberta" nos dados.
"""


def treinar(
    rotulos: Sequence[Rotulo],
    textos: dict[str, str],
    *,
    iteracoes: int = 4000,
    taxa: float = 0.5,
    l2: float = 1e-4,
) -> tuple[dict[str, float], float, int]:
    """Regressão logística por gradiente, determinística, com monotonia na pausa."""
    import numpy as np

    tracos, alvos = exemplos_de_treino(rotulos, textos)
    if not tracos:
        raise ValueError("sem exemplos de treino: falta o cache de texto do ASR")
    # Traço constante no treino não é traço: ele só desloca o viés e aparece no relatório como
    # se tivesse peso. `estabilidade`, por exemplo, é 1,0 em todo o corpus sintético (o cache
    # guarda o texto do prefixo já fechado), e sem este descarte ela levava peso +2,98.
    nomes = [nome for nome in sorted(tracos[0]) if len({t[nome] for t in tracos}) > 1]
    descartados = sorted(set(tracos[0]) - set(nomes))
    if descartados:
        print(f"traço(s) constante(s) descartado(s) no treino: {', '.join(descartados)}")
    if not nomes:
        raise ValueError("todos os traços são constantes no treino: nada para aprender")
    matriz = np.array([[t[n] for n in nomes] for t in tracos], dtype=np.float64)
    alvo = np.array(alvos, dtype=np.float64)
    pesos = np.zeros(len(nomes), dtype=np.float64)
    vies = 0.0
    monotonos = np.array([nome in TRACOS_MONOTONOS for nome in nomes])
    for _ in range(iteracoes):
        z = matriz @ pesos + vies
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))
        erro = p - alvo
        pesos -= taxa * ((matriz.T @ erro) / len(alvo) + l2 * pesos)
        vies -= taxa * float(np.mean(erro))
        # Gradiente projetado: peso de traço monótono não desce abaixo de zero.
        pesos[monotonos] = np.maximum(pesos[monotonos], 0.0)
    return {nome: float(peso) for nome, peso in zip(nomes, pesos, strict=True)}, vies, len(alvo)


# --- bootstrap ------------------------------------------------------------------------
def bootstrap(
    detector: DetectorDeTurno,
    rotulos: Sequence[Rotulo],
    textos: dict[str, str],
    *,
    reamostragens: int = REAMOSTRAGENS,
) -> tuple[Intervalo, Intervalo]:
    """IC de 95% do falso corte e do atraso p50, reamostrando **itens** (não decisões)."""
    decisoes = {r.id: simular(detector, r, textos.get(r.id, "")) for r in rotulos}
    fins = [r for r in rotulos if r.fim_de_turno]
    meios = [r for r in rotulos if not r.fim_de_turno]
    sorteio = random.Random(SEMENTE_BOOTSTRAP)  # noqa: S311 — reamostragem, não segredo

    taxas: list[float] = []
    atrasos: list[float] = []
    for _ in range(reamostragens):
        amostra_meio = [sorteio.choice(meios) for _ in meios] if meios else []
        taxas.append(
            sum(1 for r in amostra_meio if decisoes[r.id] is not None) / len(amostra_meio)
            if amostra_meio
            else 0.0
        )
        amostra_fim = [sorteio.choice(fins) for _ in fins] if fins else []
        valores = [decisoes[r.id] for r in amostra_fim if decisoes[r.id] is not None]
        atrasos.append(percentil([v for v in valores if v is not None], 50))

    def intervalo(valores: list[float], estimativa: float) -> Intervalo:
        return Intervalo(
            estimativa=estimativa,
            inferior=percentil(valores, 2.5),
            superior=percentil(valores, 97.5),
        )

    ponto = medir_ponto(detector, 0.0, rotulos, textos, split="retido")
    return intervalo(taxas, ponto.falso_corte), intervalo(atrasos, ponto.atraso_p50)


# --- escolha e regra de empate --------------------------------------------------------
def escolher_limiar(pontos: Sequence[Ponto]) -> Ponto:
    """Critério declarado antes de medir, em três degraus.

    1. candidato é quem decide em pelo menos metade dos itens de fim de turno (`DECISAO_MINIMA`)
       — senão "nunca ceder" ganharia com falso corte zero e atraso vazio;
    2. entre os candidatos com falso corte ≤ 3% (alvo do SLO-9), o de **menor atraso p50**;
    3. se nenhum candidato alcança 3%, o candidato de **menor falso corte**.
    """
    candidatos = [p for p in pontos if p.itens_fim and p.decidiu / p.itens_fim >= DECISAO_MINIMA]
    if not candidatos:  # nenhum limiar decide o suficiente: o menos pior, declarado como tal
        return max(pontos, key=lambda p: (p.decidiu, -p.falso_corte))
    dentro = [p for p in candidatos if p.falso_corte <= ALVO_SLO9]
    if dentro:
        return min(dentro, key=lambda p: (p.atraso_p50, p.falso_corte))
    return min(candidatos, key=lambda p: (p.falso_corte, p.atraso_p50))


@dataclass(frozen=True, slots=True)
class Veredito:
    """O resultado da regra de empate, com a frase que vai para o relatório."""

    semantico_entra: bool
    motivo: str


def aplicar_regra_de_empate(
    falso_fixo: Intervalo,
    atraso_fixo: Intervalo,
    falso_sem: Intervalo,
    atraso_sem: Intervalo,
    *,
    alvo_de_utilidade: float = ALVO_SLO9,
) -> Veredito:
    """Não pior em nenhuma dimensão (dentro do IC) e estritamente melhor em pelo menos uma.

    **Antes da regra, uma guarda:** o ponto de operação tem de ser *utilizável* — falso corte
    com IC inteiro dentro do alvo do SLO-9. Comparar dois pontos que interrompem o dono em mais
    de um turno a cada três não ordena candidato nenhum; declara-se **inconclusivo** e fica o
    `silencio_fixo`, que é o padrão conservador do cartão. Sem esta guarda a regra "menor
    atraso" premiava quem corta no instante zero: atraso zero por construção, com 59% de falso
    corte.
    """
    inuteis = [
        nome
        for nome, falso in (("silencio_fixo", falso_fixo), ("semantico", falso_sem))
        if falso.superior > alvo_de_utilidade
    ]
    if inuteis:
        return Veredito(
            False,
            "INCONCLUSIVO: nenhum ponto de operação é utilizável neste corpus "
            f"({', '.join(inuteis)} com falso corte acima do alvo de {alvo_de_utilidade:.0%}), "
            "então não há candidatos a ordenar. Fica o `silencio_fixo` por ser o padrão "
            "conservador, e quem decide é o corpus real (F1-15/F1-16)",
        )

    pior_em_falso = falso_sem.inferior > falso_fixo.superior
    pior_em_atraso = atraso_sem.inferior > atraso_fixo.superior
    melhor_em_falso = falso_sem.superior < falso_fixo.inferior
    melhor_em_atraso = atraso_sem.superior < atraso_fixo.inferior

    if pior_em_falso or pior_em_atraso:
        qual = "falso corte" if pior_em_falso else "atraso"
        return Veredito(False, f"o semântico é pior em {qual}, fora do IC: fica o silencio_fixo")
    if melhor_em_falso or melhor_em_atraso:
        qual = "falso corte" if melhor_em_falso else "atraso"
        return Veredito(
            True, f"o semântico é estritamente melhor em {qual}, fora do IC, e não é pior na outra"
        )
    return Veredito(
        False,
        "empate dentro do intervalo de confiança: fica o silencio_fixo, que é mais simples e "
        "mais explicável",
    )


# --- publicação -----------------------------------------------------------------------
@dataclass(slots=True)
class Medicao:
    curva: list[Ponto] = field(default_factory=list)
    escolhidos: dict[str, Ponto] = field(default_factory=dict)
    no_retido: dict[str, Ponto] = field(default_factory=dict)
    intervalos: dict[str, tuple[Intervalo, Intervalo]] = field(default_factory=dict)
    veredito: Veredito | None = None
    custo_us: tuple[float, float] = (0.0, 0.0)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "detector",
                "limiar",
                "split",
                "itens_fim",
                "itens_meio",
                "falso_corte",
                "atraso_p50_ms",
                "atraso_p95_ms",
                "decidiu",
                "nao_decidiu",
            ]
        )
        for p in medicao.curva:
            escritor.writerow(
                [
                    p.detector,
                    f"{p.limiar:g}",
                    p.split,
                    p.itens_fim,
                    p.itens_meio,
                    f"{p.falso_corte:.4f}",
                    f"{p.atraso_p50:.0f}",
                    f"{p.atraso_p95:.0f}",
                    p.decidiu,
                    p.nao_decidiu,
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path, *, modelo_asr: str) -> None:
    maquina = hardware()
    linhas = [
        "# F1-07 — curva falso corte × atraso: semântico vs silêncio fixo",
        "",
        "**Gerado por** `tools/curva_turno.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **ESTE CARTÃO NÃO FECHA O ACEITE (d) DA F1.** A curva é sobre corpus **sintético**: "
        "serve para ordenar candidatos e pegar regressão. O número publicado de SLO-4 e SLO-9 "
        "sai do corpus **real** (F1-15), medido na máquina do dono (F1-16). Apresentar esta "
        "curva como aceite da fase é motivo de recusa na revisão.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- texto do detector semântico: transcrição real de `{modelo_asr}` do áudio até o "
        "início da pausa (cache em `f1-07-texto-no-corte.csv`), **não** o texto do rótulo — "
        "dar ASR perfeito ao semântico inflaria o resultado dele",
        "- A/B **pareado**: os dois detectores veem os mesmos itens, e a decisão é simulada de "
        "20 em 20 ms dentro da pausa gravada",
        "- limiar escolhido no split `calibracao` pelo critério declarado: candidato é quem "
        f'decide em ≥ {DECISAO_MINIMA:.0%} dos itens de fim de turno (senão "nunca ceder" '
        f"ganharia por vácuo); entre eles, menor atraso p50 com falso corte ≤ {ALVO_SLO9:.0%}; "
        "se nenhum alcança, menor falso corte. Número publicado no split `retido`",
        f"- IC de 95% por *bootstrap* de {REAMOSTRAGENS} reamostragens **de itens**",
        "",
        "## Curva no split `calibracao`",
        "",
        "| detector | limiar | falso corte | atraso p50 | atraso p95 | decidiu | não decidiu |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for p in medicao.curva:
        if p.split != "calibracao":
            continue
        unidade = "ms" if p.detector == "silencio_fixo" else ""
        # Atraso só existe onde houve decisão: imprimir 0 ms para quem nunca cedeu seria
        # mostrar o pior resultado possível como se fosse o melhor.
        p50 = f"{p.atraso_p50:.0f} ms" if p.decidiu else "—"
        p95 = f"{p.atraso_p95:.0f} ms" if p.decidiu else "—"
        linhas.append(
            f"| `{p.detector}` | {p.limiar:g}{unidade} | {p.falso_corte:.1%} "
            f"| {p50} | {p95} | {p.decidiu}/{p.itens_fim} | {p.nao_decidiu} |"
        )

    linhas += [
        "",
        "## Ponto de operação escolhido e número no `retido`",
        "",
        "| detector | limiar | falso corte (IC 95%) | atraso p50 (IC 95%) | atraso p95 | "
        "não decidiu |",
        "|---|---:|---|---|---:|---:|",
    ]
    for nome, ponto in medicao.no_retido.items():
        falso, atraso = medicao.intervalos[nome]
        unidade = "ms" if nome == "silencio_fixo" else ""
        linhas.append(
            f"| `{nome}` | {medicao.escolhidos[nome].limiar:g}{unidade} | {falso} | {atraso} "
            f"| {ponto.atraso_p95:.0f} ms | {ponto.nao_decidiu} |"
        )

    veredito = medicao.veredito
    linhas += [
        "",
        "## Regra de empate (escrita antes de medir) e veredito",
        "",
        "> O detector semântico só entra no v1 se, **no mesmo atraso**, reduzir o falso corte, "
        "**ou**, no **mesmo falso corte**, reduzir o atraso. Empate dentro do intervalo de "
        "confiança → fica o `silencio_fixo`, que é mais simples e mais explicável.",
        "",
        "**Veredito:** "
        + (
            "o semântico entra"
            if veredito and veredito.semantico_entra
            else "fica o `silencio_fixo`"
        )
        + f" — {veredito.motivo if veredito else 'sem veredito'}.",
        "",
        "## SLO-4 e SLO-9",
        "",
        f"- **SLO-4** (pausa → decisão), alvo da SPEC §7: p50 ≤ {SLO4_P50_MS:.0f} ms, "
        f"p95 ≤ {SLO4_P95_MS:.0f} ms.",
    ]
    for nome, ponto in medicao.no_retido.items():
        atinge = ponto.atraso_p50 <= SLO4_P50_MS and ponto.atraso_p95 <= SLO4_P95_MS
        falso, _ = medicao.intervalos[nome]
        utilizavel = falso.superior <= ALVO_SLO9
        # "Atinge o SLO-4" sem ponto utilizável não é conquista: cortar no instante zero dá
        # atraso zero por construção. A ressalva anda junto do número, na mesma linha.
        ressalva = (
            ""
            if utilizavel
            else f" — **sem valor: o ponto não é utilizável** (falso corte {falso.estimativa:.1%})"
        )
        linhas.append(
            f"  - `{nome}`: p50 {ponto.atraso_p50:.0f} ms, p95 {ponto.atraso_p95:.0f} ms → "
            f"{'atinge' if atinge else '**não atinge**'}{ressalva}"
        )
    for nome in medicao.no_retido:
        falso, _ = medicao.intervalos[nome]
        cabe = falso.superior <= ALVO_SLO9
        linhas.append(
            f"- **SLO-9** ({ALVO_SLO9:.0%} de falso corte, marcado **[SUPOSIÇÃO]** na SPEC §7) "
            f"com `{nome}`: {falso} → o alvo "
            f"{'se sustenta neste corpus' if cabe else '**não se sustenta nem no sintético**'}."
        )
    linhas += [
        "",
        f"- custo de computação da decisão: {medicao.custo_us[0]:.1f} µs p50 e "
        f"{medicao.custo_us[1]:.1f} µs p95 por chamada (é o nosso código; o atraso acima é "
        "tempo de **áudio**, que é o que o SLO-4 mede)",
        "",
        "## Âncoras externas (são âncoras, não metas nossas)",
        "",
        "- **Semantic VAD (2023)**: −53,3% de latência média em conjunto **interno** deles.",
        "- **Voice-Light**: recall de EOT aprendido de 12,53% contra 95,60% do Silero.",
        "",
        "Outro conjunto, outro idioma, outra definição de corte. Servem para situar a ordem de "
        "grandeza — comparar com os nossos números seria comparar coisas diferentes.",
        "",
        "## O que não foi medido",
        "",
    ]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def medir_custo(detector: DetectorDeTurno, repeticoes: int = 20_000) -> tuple[float, float]:
    """Quanto o nosso código gasta por decisão (µs). Não é o SLO-4, é o custo de CPU."""
    contexto = Contexto(pausa_ms=400.0, texto="abre a pasta de fotos", estabilidade=1.0)
    tempos: list[float] = []
    for _ in range(repeticoes):
        antes = time.perf_counter_ns()
        detector.prever(contexto)
        tempos.append((time.perf_counter_ns() - antes) / 1000.0)
    return percentil(tempos, 50), percentil(tempos, 95)


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    analisa.add_argument("--texto", type=Path, default=ARQUIVO_TEXTO)
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    analisa.add_argument("--pesos", type=Path, default=ARQUIVO_PESOS)
    analisa.add_argument(
        "--preparar-texto",
        action="store_true",
        help="gera o cache de texto do ASR (precisa do modelo)",
    )
    analisa.add_argument("--treinar", action="store_true", help="treina o semântico no calibracao")
    analisa.add_argument("--itens", type=int, default=None, help="limita itens (para teste)")
    analisa.add_argument("--reamostragens", type=int, default=REAMOSTRAGENS)
    args = analisa.parse_args(argv)

    if args.preparar_texto:
        try:
            quantos = preparar_texto(args.corpus, args.texto, itens=args.itens)
        except RuntimeError as erro:
            print(f"FALHOU: {erro}")
            return 2
        print(f"{quantos} item(ns) transcritos no instante do corte → {args.texto}")
        return 0

    if not args.texto.exists():
        print(f"FALHOU: falta o cache de texto ({args.texto}). Rode --preparar-texto primeiro.")
        return 2
    textos = ler_texto(args.texto)
    rotulos = [r for r in ler_rotulos(args.corpus / "rotulos.jsonl") if r.sintetico]
    if args.itens is not None:
        rotulos = rotulos[: args.itens]
    rotulos = [r for r in rotulos if r.id in textos]
    calibracao = [r for r in rotulos if r.split == "calibracao"]
    retido = [r for r in rotulos if r.split == "retido"]
    if not calibracao or not retido:
        print("FALHOU: os dois splits precisam ter itens (o 70/30 vem da criação do corpus)")
        return 2
    for nome_split, grupo in (("calibracao", calibracao), ("retido", retido)):
        fins = sum(1 for r in grupo if r.fim_de_turno)
        meios = len(grupo) - fins
        if not fins or not meios:
            # Falso corte sem item de meio de frase é 0 por vácuo, e atraso sem item de fim de
            # turno não existe. Métrica vazia parece boa — então aqui ela é erro, não resultado.
            print(
                f"FALHOU: o split {nome_split} tem {fins} item(ns) de fim de turno e {meios} de "
                "meio de frase; as duas classes são obrigatórias para a curva significar algo"
            )
            return 2

    if args.treinar:
        pesos, vies, n = treinar(calibracao, textos)
        gravar_pesos(args.pesos, pesos=pesos, vies=vies, treinado_em=time.strftime("%Y-%m-%d"), n=n)
        print(f"pesos treinados em {n} exemplos do split calibracao → {args.pesos}")
        for nome, peso in sorted(pesos.items(), key=lambda item: -abs(item[1])):
            print(f"  {nome:30.30} {peso:+.3f}")
        print(f"  {'(viés)':30.30} {vies:+.3f}")
        return 0

    semantico = Semantico.do_arquivo(args.pesos) if args.pesos.exists() else None
    if semantico is None:
        print(f"FALHOU: faltam os pesos do semântico ({args.pesos}). Rode --treinar.")
        return 2

    medicao = Medicao()
    for limiar in LIMIARES_SILENCIO_MS:
        medicao.curva.append(
            medir_ponto(
                SilencioFixo(limiar_ms=limiar), limiar, calibracao, textos, split="calibracao"
            )
        )
    for limiar in LIMIARES_P_EOT:
        detector = Semantico(pesos=semantico.pesos, vies=semantico.vies, limiar=limiar)
        medicao.curva.append(medir_ponto(detector, limiar, calibracao, textos, split="calibracao"))

    for nome in ("silencio_fixo", "semantico"):
        pontos = [p for p in medicao.curva if p.detector == nome]
        escolhido = escolher_limiar(pontos)
        medicao.escolhidos[nome] = escolhido
        detector_final: DetectorDeTurno = (
            SilencioFixo(limiar_ms=escolhido.limiar)
            if nome == "silencio_fixo"
            else Semantico(pesos=semantico.pesos, vies=semantico.vies, limiar=escolhido.limiar)
        )
        ponto_retido = medir_ponto(detector_final, escolhido.limiar, retido, textos, split="retido")
        medicao.curva.append(ponto_retido)
        medicao.no_retido[nome] = ponto_retido
        medicao.intervalos[nome] = bootstrap(
            detector_final, retido, textos, reamostragens=args.reamostragens
        )

    falso_fixo, atraso_fixo = medicao.intervalos["silencio_fixo"]
    falso_sem, atraso_sem = medicao.intervalos["semantico"]
    medicao.veredito = aplicar_regra_de_empate(falso_fixo, atraso_fixo, falso_sem, atraso_sem)
    medicao.custo_us = medir_custo(
        Semantico(pesos=semantico.pesos, vies=semantico.vies, limiar=0.5)
    )
    medicao.lacunas += [
        (
            "o aceite (d) da F1",
            "não fecha aqui: a curva é sintética e serve para ordenar candidatos; o número "
            "publicado sai do corpus real (F1-15) na máquina do dono (F1-16)",
        ),
        (
            "pausa humana",
            "a pausa aqui é a que **nós** sorteamos (300-900 ms no fim de turno, 200-1200 ms na "
            "hesitação); hesitação, respiração e retomada reais não estão no gerador",
        ),
        (
            "prosódia",
            "o detector semântico usa texto e pausa. Prosódia de TTS é mais limpa que a humana "
            "e favoreceria o semântico justo no eixo comparado — por isso não foi usada",
        ),
        (
            "adaptação por falante",
            "fora do escopo do cartão",
        ),
        ("Windows", "a medição rodou só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-07-turno.csv")
    modelo = next(iter(ler_texto_modelo(args.texto)), "?")
    escrever_markdown(medicao, args.saida / "f1-07-turno.md", modelo_asr=modelo)

    for nome, ponto in medicao.no_retido.items():
        falso, atraso = medicao.intervalos[nome]
        print(
            f"{nome:16.16} limiar {medicao.escolhidos[nome].limiar:7g} | falso corte {falso} "
            f"| atraso p50 {atraso} p95 {ponto.atraso_p95:.0f} ms"
        )
    print(f"\nveredito: {medicao.veredito.motivo}")
    print(f"csv e relatório em {args.saida}")
    return 0


def ler_texto_modelo(arquivo: Path) -> set[str]:
    with arquivo.open(encoding="utf-8") as f:
        return {linha["modelo"] for linha in csv.DictReader(f)}


if __name__ == "__main__":
    sys.exit(main())
