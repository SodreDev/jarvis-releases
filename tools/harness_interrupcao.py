"""A palavra de ativação dita por cima de uma fala do Jarvis corta? (ADR-0040; dono, 2026-10-25)

    nice -n 19 uv run --frozen python tools/harness_interrupcao.py             # tabela no terminal
    nice -n 19 uv run --frozen python tools/harness_interrupcao.py --publicar docs/medicoes/x.md

Tudo sintético, nenhum dispositivo: a resposta do Jarvis é a voz piper local; o microfone ouve o
**eco** dela pela sala — o caminho direto atrasado e atenuado pela perda do alto-falante →
microfone **mais a reverberação** (uma resposta ao impulso sintética: ruído com decaimento
exponencial até o RT60 da sala) —, o ruído da sala e, num momento, o dono: a mesma voz, perto do
microfone, com pouca reverberação, no nível dele. O eco é calculado quadro a quadro do que o
Jarvis **tocou**: quando a vigia pausa (a contínua conferindo), o alto-falante cala e só a cauda
da sala segue no microfone — como na máquina de verdade.

A vigia é a do laço (`VigiaDeInterrupcao`), com o mesmo `transcrever` dele: o whisper local com a
dica e o filtro da ADR-0043 (`julgar_texto`). O resultado do ASR chega com a latência pedida, em
quadros de áudio (a Groq do dono fica em ~450 ms no turno, pela trilha; o whisper small, mais).

Mede, por variante da vigia × sala × modo × nível do dono × frase:

- **corte** — a vigia cortou a fala pelo nome (ou pela ordem de parar, na contínua);
- **falso corte** — só o eco, sem o dono: a vigia não pode cortar a fala do próprio Jarvis;
- **pausa à toa** — na contínua, só o eco pausou o Jarvis (ele gagueja).

E o **aprendizado** do portão de eco: antes de cada caso, `--turnos-antes` respostas inteiras com o
dono comentando por cima, sem o nome (o que derrubava a perda aprendida — o auto-reforço).

As variantes repõem o que a vigia era antes do conserto, peça por peça, para dizer qual delas
derrubava o corte. O que isto não prova: sala, alto-falante, microfone e voz de verdade; o ASR da
nuvem do dono (Groq) no lugar do whisper local.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Final

import numpy as np

from jarvis.audio_io.dsp import CanceladorDeEco
from jarvis.audio_io.quadro import MS_POR_QUADRO, PISO_DB, Quadro, energia_db
from jarvis.audio_io.sintese import ruido_rosa
from jarvis.voz import interrupcao
from jarvis.voz.app import motor_de_asr, motor_de_tts
from jarvis.voz.config import Configuracao
from jarvis.voz.dica import dica_do_asr
from jarvis.voz.escuta import ModoDeEscuta
from jarvis.voz.interface import MotorDeAsr, transcrever_com_sinais
from jarvis.voz.interrupcao import Acao, PortaoDeEco, VigiaDeInterrupcao
from jarvis.voz.palavra import DetectorDePalavra
from jarvis.voz.ruido import PoliticaDeRuido, julgar_texto, palavras_da_dica

TAXA: Final = 16000
AMOSTRAS_POR_QUADRO: Final = 320
RESPOSTA: Final = (
    "Hoje o dia vai ser de sol com algumas nuvens à tarde, e a temperatura chega a vinte e oito "
    "graus. À noite esfria um pouco, então vale levar um casaco leve se você for sair depois das "
    "oito. Amanhã deve chover de manhã cedo."
)
"""Uma fala normal do Jarvis: três frases, uns dez segundos."""
COMENTARIO: Final = "Nossa, que calor que vai fazer hoje, hein."
FRASES: Final = ("Jarvis.", "Jarvis, para.", "Jarvis, que horas são?")
NIVEIS_DO_DONO_DB: Final = (-6.0, -12.0, -18.0)
"""O pico da fala do dono no microfone, relativo ao pico da fala do Jarvis no alto-falante."""
COMECO_DO_DONO_MS: Final = 2500
RUIDO_DA_SALA_DB: Final = -62.0
LIMIAR_DO_VAD_DB: Final = -50.0
"""O VAD do laço diz "fala" no eco também: aqui, energia acima disto (o portão é quem separa)."""
PICO_DO_JARVIS_DB: Final = -12.0


@dataclass(frozen=True, slots=True)
class Sala:
    """O caminho alto-falante → microfone."""

    nome: str
    perda_db: float
    """Atenuação do caminho direto: 6 dB é caixa alta perto do microfone (o pior caso)."""
    rt60_ms: float
    """Tempo para a reverberação cair 60 dB; 0 = sem reverberação (o eco seco de antes)."""
    reverberacao_db: float = 0.0
    """Energia da cauda relativa à do caminho direto (0 dB: tanto quanto o direto — sala comum,
    caixa a um metro)."""
    atraso_ms: float = 30.0


SALAS: Final = (
    Sala("seca, caixa perto", 6.0, 0.0),
    Sala("sala, caixa perto", 6.0, 500.0),
    Sala("sala, notebook", 12.0, 500.0),
    Sala("sala viva, notebook", 12.0, 900.0, reverberacao_db=3.0),
    Sala("sala, volume baixo", 20.0, 500.0),
    Sala("notebook, saída atrasada 150 ms", 12.0, 500.0, atraso_ms=150.0),
)


@dataclass(frozen=True, slots=True)
class Variante:
    """Como a vigia está: a de agora, ou a de antes do conserto, peça por peça."""

    nome: str
    suspeitar_ms: int = interrupcao.FALA_PARA_SUSPEITAR_MS
    aprende_com_trecho: bool = False
    """`True` = o portão aprende a perda também com um trecho aberto (o auto-reforço de antes)."""
    filtro: bool = True
    """O filtro da ADR-0043 na transcrição da vigia."""
    perda_pelo_quadro: bool = False
    """`True` = o portão de antes, que media a perda contra o quadro de agora (e não pico contra
    pico) — a que inflava nos vales da fala."""
    aec: bool = True
    """O cancelador de eco do F1-04 no caminho da vigia."""


@dataclass(frozen=True, slots=True)
class Caso:
    sala: Sala
    modo: ModoDeEscuta
    nivel_db: float | None
    """`None` = só o eco (o caso do falso corte)."""
    frase: str


@dataclass(frozen=True, slots=True)
class Resultado:
    variante: str
    caso: Caso
    cortou: bool
    pausou: bool
    motivo: str
    ms: float
    """Do começo da fala do dono até o corte, em tempo de áudio (0 sem corte)."""
    perda_aprendida_db: float


class _PortaoQueSempreAprende(PortaoDeEco):
    """O portão de antes: aprende a perda com qualquer quadro, até com o dono falando."""

    @property
    def aprender(self) -> bool:
        return True

    @aprender.setter
    def aprender(self, _valor: bool) -> None:
        pass


class _PortaoDeAntes(_PortaoQueSempreAprende):
    """O portão até 2026-10-29: a perda observada era o pico da referência contra o quadro."""

    def ver(self, quadro: Quadro) -> bool:
        self._referencias.append(self._referencia_do_quadro)
        self._referencia_do_quadro = PISO_DB
        nivel = quadro.energia_db
        passou = nivel >= self.limiar_db()
        maior = max(self._referencias)
        if maior > interrupcao.REFERENCIA_ATIVA_DB:
            observada = min(
                interrupcao.PERDA_MAXIMA_DB, max(interrupcao.PERDA_MINIMA_DB, maior - nivel)
            )
            if not passou:
                self.perda_db += interrupcao.APRENDIZADO * (observada - self.perda_db)
            elif observada < self.perda_db:
                self.perda_db += interrupcao.APRENDIZADO_COM_FALA * (observada - self.perda_db)
        else:
            self._niveis_do_ambiente.append(nivel)
            self.ambiente_db = sorted(self._niveis_do_ambiente)[
                min(
                    len(self._niveis_do_ambiente) - 1,
                    int(interrupcao.PERCENTIL_DO_AMBIENTE * len(self._niveis_do_ambiente)),
                )
            ]
        return passou


@contextlib.contextmanager
def _suspeita_em(ms: int) -> Iterator[None]:
    antes = interrupcao.FALA_PARA_SUSPEITAR_MS
    interrupcao.FALA_PARA_SUSPEITAR_MS = ms  # type: ignore[misc]
    try:
        yield
    finally:
        interrupcao.FALA_PARA_SUSPEITAR_MS = antes  # type: ignore[misc]


# --- áudio ----------------------------------------------------------------------------------
def _vetor(amostras: bytes) -> np.ndarray:
    return np.frombuffer(amostras, dtype=np.int16).astype(np.float64)


def _bytes(vetor: np.ndarray) -> bytes:
    return np.clip(np.round(vetor), -32768, 32767).astype(np.int16).tobytes()


def _pico_db(vetor: np.ndarray) -> float:
    quadros = len(vetor) // AMOSTRAS_POR_QUADRO
    if quadros == 0:
        return -120.0
    blocos = vetor[: quadros * AMOSTRAS_POR_QUADRO].reshape(quadros, AMOSTRAS_POR_QUADRO)
    rms = np.sqrt(np.mean(blocos**2, axis=1)) / 32768.0
    return float(20.0 * np.log10(max(float(rms.max()), 1e-9)))


def _no_nivel(vetor: np.ndarray, alvo_db: float) -> np.ndarray:
    fator: float = 10.0 ** ((alvo_db - _pico_db(vetor)) / 20.0)
    return vetor * fator


def resposta_ao_impulso(sala: Sala, *, semente: int = 7) -> np.ndarray:
    """O caminho direto (atrasado, atenuado) e a cauda: ruído gaussiano com decaimento exponencial
    até o RT60, com a energia pedida relativa ao direto."""
    atraso = int(sala.atraso_ms * TAXA / 1000)
    direto = 10.0 ** (-sala.perda_db / 20.0)
    if sala.rt60_ms <= 0:
        h = np.zeros(atraso + 1)
        h[atraso] = direto
        return h
    tamanho = int(sala.rt60_ms * TAXA / 1000)
    t = np.arange(tamanho) / TAXA
    cauda = np.random.default_rng(semente).standard_normal(tamanho)
    cauda *= np.exp(-6.9078 * t / (sala.rt60_ms / 1000.0))  # −60 dB no RT60
    cauda[: int(0.005 * TAXA)] = 0.0  # as primeiras reflexões chegam uns ms depois do direto
    energia = direto**2 * 10.0 ** (sala.reverberacao_db / 10.0)
    cauda *= np.sqrt(energia / max(float(np.sum(cauda**2)), 1e-12))
    h = np.zeros(atraso + tamanho)
    h[atraso] = direto
    h[atraso:] += cauda
    return h


class _Sala:
    """O microfone, quadro a quadro: o eco do que o alto-falante **tocou** até agora (com a
    reverberação), o ruído e o dono."""

    def __init__(self, h: np.ndarray, sala: np.ndarray, dono: np.ndarray | None) -> None:
        self.sala = sala
        self.dono = dono
        # Soma por sobreposição (overlap-add) na frequência: cada quadro tocado espalha a cauda
        # dele pelos próximos quadros do microfone.
        self.n_fft = 1 << int(np.ceil(np.log2(len(h) + AMOSTRAS_POR_QUADRO)))
        self.h_f = np.fft.rfft(h, self.n_fft)
        self.acumulado = np.zeros(self.n_fft)
        self.posicao = 0

    def quadro(self, alto_falante: np.ndarray) -> bytes:
        if np.any(alto_falante):
            espalhado = np.fft.irfft(np.fft.rfft(alto_falante, self.n_fft) * self.h_f, self.n_fft)
            self.acumulado += espalhado
        o_eco = self.acumulado[:AMOSTRAS_POR_QUADRO].copy()
        self.acumulado = np.concatenate(
            [self.acumulado[AMOSTRAS_POR_QUADRO:], np.zeros(AMOSTRAS_POR_QUADRO)]
        )
        mic = o_eco + self._de(self.sala) + self._de(self.dono)
        self.posicao += len(alto_falante)
        return _bytes(mic)

    def _de(self, sinal: np.ndarray | None) -> np.ndarray:
        fatia = np.zeros(AMOSTRAS_POR_QUADRO)
        if sinal is None or self.posicao >= len(sinal):
            return fatia
        pedaco = sinal[self.posicao : self.posicao + AMOSTRAS_POR_QUADRO]
        fatia[: len(pedaco)] = pedaco
        return fatia


# --- ASR -------------------------------------------------------------------------------------
class _Atrasado:
    """O `enviar` da vigia: roda já, mas o resultado só fica pronto depois de `quadros` quadros —
    a latência do ASR, em tempo de áudio."""

    def __init__(self, latencia_ms: float) -> None:
        self.quadros = max(0, int(latencia_ms / MS_POR_QUADRO))
        self._pendentes: list[tuple[int, Future[object], object]] = []

    def __call__(self, funcao: Callable[[], object]) -> Future[object]:
        futuro: Future[object] = Future()
        self._pendentes.append((self.quadros, futuro, funcao()))
        return futuro

    def tique(self) -> None:
        restantes = []
        for falta, futuro, valor in self._pendentes:
            if falta <= 0:
                if not futuro.cancelled():
                    futuro.set_result(valor)
            else:
                restantes.append((falta - 1, futuro, valor))
        self._pendentes = restantes


class _Transcritor:
    """O `transcrever` do laço (ASR + filtro da ADR-0043), com cache pelo áudio: as variantes
    mandam muitas vezes o mesmo trecho."""

    def __init__(self, asr: MotorDeAsr, dica: str) -> None:
        self.asr = asr
        self.politica = PoliticaDeRuido()
        self.palavras = palavras_da_dica(dica)
        self._cache: dict[bytes, tuple[str, str]] = {}
        self.chamadas = 0
        self.segundos = 0.0

    def bruto(self, amostras: bytes) -> tuple[str, str]:
        """(texto do ASR, texto depois do filtro)."""
        chave = hashlib.blake2b(amostras, digest_size=16).digest()
        if chave not in self._cache:
            comeco = time.monotonic()
            transcricao = transcrever_com_sinais(self.asr, amostras)
            self.segundos += time.monotonic() - comeco
            self.chamadas += 1
            veredito = julgar_texto(
                transcricao.hipotese.texto,
                transcricao.sinais,
                politica=self.politica,
                dica=self.palavras,
            )
            filtrado = "" if veredito.descartado else veredito.texto
            self._cache[chave] = (transcricao.hipotese.texto, filtrado)
        return self._cache[chave]

    def com_filtro(self, amostras: bytes) -> str:
        return self.bruto(amostras)[1]

    def sem_filtro(self, amostras: bytes) -> str:
        return self.bruto(amostras)[0]


# --- uma fala do Jarvis ------------------------------------------------------------------------
def _falar(
    vigia: VigiaDeInterrupcao,
    atrasado: _Atrasado,
    jarvis: np.ndarray,
    sala: _Sala,
) -> tuple[bool, bool, str, float]:
    """Uma fala do Jarvis, quadro a quadro: o alto-falante toca (ou cala, pausado), a referência
    vai ao portão, o microfone à vigia. Devolve (cortou, pausou, motivo, ms do corte)."""
    vigia.comecar(vigia.modo)
    vigia.falando(RESPOSTA)
    cursor = 0
    pausado = pausou = False
    quadro_n = 0
    silencio = np.zeros(AMOSTRAS_POR_QUADRO)
    limite = len(jarvis) + 2 * TAXA  # a cauda e uma eventual pausa no fim
    while sala.posicao < limite:
        if not pausado and cursor < len(jarvis):
            saida = jarvis[cursor : cursor + AMOSTRAS_POR_QUADRO]
            if len(saida) < AMOSTRAS_POR_QUADRO:
                saida = np.concatenate([saida, np.zeros(AMOSTRAS_POR_QUADRO - len(saida))])
            cursor += AMOSTRAS_POR_QUADRO
        elif not pausado:
            break  # acabou de falar
        else:
            saida = silencio
        if saida is not silencio:
            vigia.referencia(_bytes(saida))
        mic = sala.quadro(saida)
        atrasado.tique()
        quadro = Quadro(quadro_n, mic, 0)
        quadro_n += 1
        acao = vigia.ouvir(quadro, fala_no_vad=energia_db(mic) > LIMIAR_DO_VAD_DB)
        if acao is Acao.PAUSAR:
            pausado = pausou = True
        elif acao is Acao.RETOMAR:
            pausado = False
        elif acao is Acao.CORTAR:
            ms = sala.posicao / TAXA * 1000.0 - COMECO_DO_DONO_MS
            return True, pausou, str(vigia.decisoes[-1].motivo), ms
    vigia.terminar()
    motivo = str(vigia.decisoes[-1].motivo) if vigia.decisoes else "nenhuma_decisao"
    return False, pausou, motivo, 0.0


def medir(
    transcritor: _Transcritor,
    falar: Callable[[str], bytes],
    *,
    latencia_ms: float,
    turnos_antes: int,
    casos: Sequence[Caso],
    variantes: Sequence[Variante],
    progresso: Callable[[str], None] = lambda _texto: None,
) -> list[Resultado]:
    jarvis = _no_nivel(_vetor(falar(RESPOSTA)), PICO_DO_JARVIS_DB)
    comentario = _vetor(falar(COMENTARIO))
    ditas = {frase: _vetor(falar(frase)) for frase in {c.frase for c in casos if c.frase}}
    duracao = len(jarvis) + 4 * TAXA
    ruido = _vetor(ruido_rosa(duracao / 16, aleatorio=Random(3), pico=1.0))  # noqa: S311 — semente fixa
    ruido = _no_nivel(ruido, RUIDO_DA_SALA_DB)
    perto = Sala("dono", 0.0, 250.0, reverberacao_db=-9.0, atraso_ms=0.0)
    h_do_dono = resposta_ao_impulso(perto, semente=11)
    resultados = []
    for variante in variantes:
        transcrever = transcritor.com_filtro if variante.filtro else transcritor.sem_filtro
        fabrica: Callable[[], PortaoDeEco] = (
            _PortaoDeAntes
            if variante.perda_pelo_quadro
            else _PortaoQueSempreAprende
            if variante.aprende_com_trecho
            else PortaoDeEco
        )
        with _suspeita_em(variante.suspeitar_ms):
            for caso in casos:
                h = resposta_ao_impulso(caso.sala)
                atrasado = _Atrasado(latencia_ms)
                vigia = VigiaDeInterrupcao(
                    transcrever=transcrever,
                    palavra=DetectorDePalavra(),
                    enviar=atrasado,
                    portao=fabrica(),
                    modo=caso.modo,
                    cancelador=CanceladorDeEco() if variante.aec else None,
                )
                nivel = caso.nivel_db if caso.nivel_db is not None else -18.0
                for vez in range(turnos_antes):
                    # Respostas anteriores: o portão aprende a perda — com o dono comentando por
                    # cima, sem o nome (na contínua isso pausa; o que se quer é o estado do portão).
                    dono = np.convolve(_no_nivel(comentario, PICO_DO_JARVIS_DB + nivel), h_do_dono)
                    dono = np.concatenate([np.zeros(int((1.0 + 0.7 * vez) * TAXA)), dono])
                    _falar(vigia, atrasado, jarvis, _Sala(h, ruido, dono))
                dono_do_caso: np.ndarray | None = None
                if caso.nivel_db is not None:
                    dito = np.convolve(
                        _no_nivel(ditas[caso.frase], PICO_DO_JARVIS_DB + caso.nivel_db), h_do_dono
                    )
                    dono_do_caso = np.concatenate(
                        [np.zeros(COMECO_DO_DONO_MS * TAXA // 1000), dito]
                    )
                cortou, pausou, motivo, ms = _falar(
                    vigia, atrasado, jarvis, _Sala(h, ruido, dono_do_caso)
                )
                resultados.append(
                    Resultado(
                        variante.nome, caso, cortou, pausou, motivo, ms, vigia.portao.perda_db
                    )
                )
                progresso(
                    f"{variante.nome} · {caso.sala.nome} · {caso.modo} · {caso.nivel_db} · "
                    f"{caso.frase or '(eco)'} → {'CORTA' if cortou else 'não'} ({motivo})"
                )
    return resultados


def casos_padrao(
    salas: Sequence[Sala] = SALAS,
    frases: Sequence[str] = FRASES,
    niveis: Sequence[float] = NIVEIS_DO_DONO_DB,
    modos: Sequence[ModoDeEscuta] = (ModoDeEscuta.PALAVRA, ModoDeEscuta.CONTINUA),
) -> list[Caso]:
    casos: list[Caso] = []
    for modo in modos:
        for sala in salas:
            casos.extend(Caso(sala, modo, nivel, frase) for nivel in niveis for frase in frases)
            casos.append(Caso(sala, modo, None, ""))
    return casos


VARIANTES: Final = (
    Variante(
        "antes (portão de 25/10, sem AEC)",
        suspeitar_ms=240,
        aprende_com_trecho=True,
        perda_pelo_quadro=True,
        aec=False,
    ),
    Variante("portão pico a pico, sem AEC", aec=False),
    Variante("agora (portão pico a pico + AEC)"),
    Variante("agora, sem o filtro da ADR-0043", filtro=False),
)


def resumo(resultados: Sequence[Resultado]) -> str:
    """Uma linha por variante × sala × modo: cortes, falsos cortes, pausas à toa."""
    linhas = [
        "| variante | sala | modo | corte com o nome | falso corte (só eco) | pausa à toa (só eco) "
        "| ms do corte (mediana) | perda aprendida |",
        "|---|---|---|---|---|---|---|---|",
    ]
    grupos: dict[tuple[str, str, str], list[Resultado]] = {}
    for r in resultados:
        grupos.setdefault((r.variante, r.caso.sala.nome, str(r.caso.modo)), []).append(r)
    for (variante, sala, modo), rs in grupos.items():
        hits = [r for r in rs if r.caso.nivel_db is not None]
        ecos = [r for r in rs if r.caso.nivel_db is None]
        ms = sorted(r.ms for r in hits if r.cortou)
        mediana = f"{ms[len(ms) // 2]:.0f}" if ms else "—"
        perda = sum(r.perda_aprendida_db for r in rs) / len(rs)
        linhas.append(
            f"| {variante} | {sala} | {modo} | {sum(r.cortou for r in hits)}/{len(hits)} "
            f"| {sum(r.cortou for r in ecos)}/{len(ecos)} | {sum(r.pausou for r in ecos)}/"
            f"{len(ecos)} | {mediana} | {perda:.1f} dB |"
        )
    linhas.append("")
    linhas.append("| variante | corte com o nome | falso corte pelo eco | pausa à toa |")
    linhas.append("|---|---|---|---|")
    por_variante: dict[str, list[Resultado]] = {}
    for r in resultados:
        por_variante.setdefault(r.variante, []).append(r)
    for variante, rs in por_variante.items():
        hits = [r for r in rs if r.caso.nivel_db is not None]
        ecos = [r for r in rs if r.caso.nivel_db is None]
        linhas.append(
            f"| {variante} | **{sum(r.cortou for r in hits)}/{len(hits)}** "
            f"| **{sum(r.cortou for r in ecos)}/{len(ecos)}** "
            f"| {sum(r.pausou for r in ecos)}/{len(ecos)} |"
        )
    return "\n".join(linhas)


def falhas(resultados: Sequence[Resultado]) -> str:
    """Os motivos de não cortar, por variante (para achar a causa)."""
    contagem: dict[tuple[str, str], int] = {}
    for r in resultados:
        if r.caso.nivel_db is not None and not r.cortou:
            chave = (r.variante, r.motivo)
            contagem[chave] = contagem.get(chave, 0) + 1
    linhas = ["| variante | motivo de não cortar | casos |", "|---|---|---|"]
    linhas.extend(f"| {v} | {m} | {n} |" for (v, m), n in sorted(contagem.items()))
    return "\n".join(linhas)


def medir_portao(falar: Callable[[str], bytes]) -> str:
    """Sem ASR, em segundos: quantos quadros do eco e do dono («Jarvis, para.») passam no portão,
    e a perda que ele aprende, com o portão de antes, o de agora e o de agora com o cancelador."""
    jarvis = _no_nivel(_vetor(falar(RESPOSTA)), PICO_DO_JARVIS_DB)
    dito = _vetor(falar("Jarvis, para."))
    ruido = _no_nivel(np.random.default_rng(1).standard_normal(len(jarvis) + 4 * TAXA), -62.0)
    perto = Sala("dono", 0.0, 250.0, reverberacao_db=-9.0, atraso_ms=0.0)
    h_do_dono = resposta_ao_impulso(perto, semente=11)
    jeitos: tuple[tuple[str, Callable[[], PortaoDeEco], bool], ...] = (
        ("antes (perda contra o quadro)", _PortaoDeAntes, False),
        ("pico a pico", PortaoDeEco, False),
        ("pico a pico + AEC", PortaoDeEco, True),
    )
    linhas = [
        "| portão | sala | eco que passa (3 respostas) | perda aprendida "
        "| dono −6 dB | dono −12 dB |",
        "|---|---|---|---|---|---|",
    ]
    for nome, fabrica, aec in jeitos:
        for sala in SALAS:
            h = resposta_ao_impulso(sala)
            celulas = []
            eco_txt = perda_txt = ""
            for nivel in (-6.0, -12.0):
                vigia = VigiaDeInterrupcao(
                    transcrever=lambda _a: "",
                    portao=fabrica(),
                    cancelador=CanceladorDeEco() if aec else None,
                )
                microfone = _Sala(h, ruido, None)
                passou = total = 0
                for _vez in range(3):
                    for i in range(0, len(jarvis) - AMOSTRAS_POR_QUADRO, AMOSTRAS_POR_QUADRO):
                        saida = jarvis[i : i + AMOSTRAS_POR_QUADRO]
                        vigia.referencia(_bytes(saida))
                        quadro = Quadro(0, microfone.quadro(saida), 0)
                        if vigia.cancelador is not None:
                            quadro = vigia._sem_o_eco_do_quadro(quadro)
                        passou += vigia.portao.ver(quadro)
                        total += 1
                eco_txt = f"{passou}/{total} ({100 * passou / total:.0f}%)"
                perda_txt = f"{vigia.portao.perda_db:.1f} dB (direto: {sala.perda_db:.0f} dB)"
                dono = np.convolve(_no_nivel(dito, PICO_DO_JARVIS_DB + nivel), h_do_dono)
                dono = np.concatenate([np.zeros(COMECO_DO_DONO_MS * TAXA // 1000), dono])
                microfone = _Sala(h, ruido, dono)
                vigia.portao.aprender = False
                fala = passou = 0
                for i in range(0, len(jarvis) - AMOSTRAS_POR_QUADRO, AMOSTRAS_POR_QUADRO):
                    saida = jarvis[i : i + AMOSTRAS_POR_QUADRO]
                    vigia.referencia(_bytes(saida))
                    quadro = Quadro(0, microfone.quadro(saida), 0)
                    if vigia.cancelador is not None:
                        quadro = vigia._sem_o_eco_do_quadro(quadro)
                    passa = vigia.portao.ver(quadro)
                    pedaco = dono[i : i + AMOSTRAS_POR_QUADRO]
                    if len(pedaco) == AMOSTRAS_POR_QUADRO and energia_db(_bytes(pedaco)) > -45:
                        fala += 1
                        passou += passa
                celulas.append(f"{passou}/{fala}")
            linhas.append(
                f"| {nome} | {sala.nome} | {eco_txt} | {perda_txt} | {celulas[0]} | {celulas[1]} |"
            )
    return "\n".join(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--latencia-ms", type=float, default=600.0)
    parser.add_argument("--turnos-antes", type=int, default=2)
    parser.add_argument("--modelo", default="small")
    parser.add_argument(
        "--variantes", default="", help="índices das variantes, ex.: 0,3 (padrão: todas)"
    )
    parser.add_argument(
        "--enxuto",
        action="store_true",
        help="3 salas, 2 níveis, 2 frases: a matriz que cabe em ~1 h de whisper small na CPU",
    )
    parser.add_argument(
        "--so-portao", action="store_true", help="só o portão, sem ASR (segundos, não horas)"
    )
    parser.add_argument("--publicar", type=Path, default=None)
    args = parser.parse_args(argv)
    configuracao = Configuracao(
        asr="asr-whisper-local",
        tts="tts-piper-epitran",
        voz="pt_BR-faber-medium",
        modelo_do_asr=args.modelo,
    )
    dica = dica_do_asr("jarvis")
    raiz = Path.home() / ".cache" / "jt" / "harness-interrupcao"
    tts = motor_de_tts(configuracao, raiz=raiz, cancelado=lambda: False)
    if args.so_portao:
        print(medir_portao(tts.sintetizar))
        return 0
    asr = motor_de_asr(configuracao, raiz=raiz, cancelado=lambda: False, dica=dica)
    transcritor = _Transcritor(asr, dica)
    variantes = (
        [VARIANTES[int(i)] for i in args.variantes.split(",")] if args.variantes else VARIANTES
    )
    casos = (
        casos_padrao(
            salas=(SALAS[0], SALAS[2], SALAS[3], SALAS[5]),
            frases=("Jarvis, para.", "Jarvis, que horas são?"),
            niveis=(-6.0, -12.0),
        )
        if args.enxuto
        else casos_padrao()
    )
    comeco = time.monotonic()
    resultados = medir(
        transcritor,
        tts.sintetizar,
        latencia_ms=args.latencia_ms,
        turnos_antes=args.turnos_antes,
        casos=casos,
        variantes=variantes,
        progresso=lambda texto: print(texto, file=sys.stderr, flush=True),
    )
    cabecalho = (
        f"whisper {args.modelo} local (int8, CPU) + filtro da ADR-0043 · voz piper pt_BR-faber-"
        f"medium · latência do ASR simulada {args.latencia_ms:.0f} ms · {args.turnos_antes} "
        f"respostas antes de cada caso · {transcritor.chamadas} transcrições "
        f"({transcritor.segundos:.0f} s de ASR, {time.monotonic() - comeco:.0f} s no total)."
    )
    texto = f"{cabecalho}\n\n{resumo(resultados)}\n\n{falhas(resultados)}"
    print(texto)
    if args.publicar is not None:
        args.publicar.write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
