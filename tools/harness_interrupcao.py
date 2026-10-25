"""A palavra de ativação dita por cima de uma fala normal do Jarvis corta? (ADR-0040; dono, 2026-10-25)

    uv run --frozen python tools/harness_interrupcao.py                 # tabela no terminal
    uv run --frozen python tools/harness_interrupcao.py --publicar      # e em docs/medicoes

Tudo sintético, nenhum dispositivo: a resposta do Jarvis é a voz piper local; o microfone ouve o
**eco** dela (atrasado e atenuado pela perda do caminho alto-falante → microfone) mais o ruído da
sala e, num momento, o dono — a mesma voz, sem eco, no nível dele. A vigia é a do laço
(`VigiaDeInterrupcao`), com o mesmo `transcrever` dele: o whisper local com a dica e o filtro da
ADR-0043 (`julgar_texto`). O resultado do ASR chega com a latência pedida, em quadros de áudio.

Mede, por perda do eco × nível do dono × frase:

- **corte** — a vigia cortou a fala pelo nome (o que o dono quer);
- **falso corte** — só o eco, sem o dono: a vigia não pode cortar a fala do próprio Jarvis.

E o **aprendizado** do portão de eco: antes de cada caso, `--turnos-antes` respostas inteiras com o
dono comentando por cima, sem o nome (o que derrubava a perda aprendida — o auto-reforço).

O que isto não prova: sala, alto-falante, microfone e voz de verdade; o ASR da nuvem do dono
(Groq) no lugar do whisper local.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Final

from jarvis.audio_io.quadro import MS_POR_QUADRO, Quadro, energia_db
from jarvis.audio_io.sintese import aplicar_ganho_db, eco, misturar, ruido_rosa, silencio
from jarvis.voz.app import motor_de_asr, motor_de_tts
from jarvis.voz.config import Configuracao
from jarvis.voz.dica import dica_do_asr
from jarvis.voz.interface import MotorDeAsr, transcrever_com_sinais
from jarvis.voz.interrupcao import Acao, PortaoDeEco, VigiaDeInterrupcao
from jarvis.voz.palavra import DetectorDePalavra
from jarvis.voz.ruido import PoliticaDeRuido, julgar_texto, palavras_da_dica

RESPOSTA: Final = (
    "Hoje o dia vai ser de sol com algumas nuvens à tarde, e a temperatura chega a vinte e oito "
    "graus. À noite esfria um pouco, então vale levar um casaco leve se você for sair depois das "
    "oito. Amanhã deve chover de manhã cedo."
)
"""Uma fala normal do Jarvis: três frases, uns dez segundos."""
COMENTARIO: Final = "Nossa, que calor que vai fazer hoje, hein."
FRASES: Final = ("Jarvis.", "Jarvis, para.", "Jarvis, que horas são?")
PERDAS_DB: Final = (6.0, 12.0, 20.0)
"""Perda do caminho alto-falante → microfone: 6 dB é caixa alta perto do microfone (o pior caso);
20 dB, notebook com volume moderado."""
NIVEIS_DO_DONO_DB: Final = (-6.0, -12.0, -18.0)
"""O pico da fala do dono no microfone, relativo ao pico da fala do Jarvis no alto-falante."""
COMECO_DO_DONO_MS: Final = 2500
ATRASO_DO_ECO_MS: Final = 30
RUIDO_DA_SALA_DB: Final = -62.0
LIMIAR_DO_VAD_DB: Final = -50.0
"""O VAD do laço diz "fala" no eco também: aqui, energia acima disto (o portão é quem separa)."""


@dataclass(frozen=True, slots=True)
class Caso:
    perda_db: float
    nivel_db: float | None
    """`None` = só o eco (o caso do falso corte)."""
    frase: str


@dataclass(frozen=True, slots=True)
class Resultado:
    caso: Caso
    cortou: bool
    motivo: str
    perda_aprendida_db: float


def _pico_db(amostras: bytes) -> float:
    return max(
        (energia_db(amostras[i : i + 640]) for i in range(0, len(amostras) - 640, 640)),
        default=-120.0,
    )


def _no_nivel(amostras: bytes, alvo_db: float) -> bytes:
    return aplicar_ganho_db(amostras, alvo_db - _pico_db(amostras))


def _quadros(amostras: bytes) -> list[bytes]:
    return [amostras[i : i + 640] for i in range(0, len(amostras) - 639, 640)]


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


def _transcritor(asr: MotorDeAsr, dica: str) -> Callable[[bytes], str]:
    politica = PoliticaDeRuido()
    palavras = palavras_da_dica(dica)

    def transcrever(amostras: bytes) -> str:
        transcricao = transcrever_com_sinais(asr, amostras)
        veredito = julgar_texto(
            transcricao.hipotese.texto, transcricao.sinais, politica=politica, dica=palavras
        )
        return "" if veredito.descartado else veredito.texto

    return transcrever


def _falar(
    vigia: VigiaDeInterrupcao,
    atrasado: _Atrasado,
    jarvis: bytes,
    microfone: bytes,
) -> tuple[bool, str]:
    """Uma fala do Jarvis, quadro a quadro: a referência vai ao portão, o microfone à vigia."""
    vigia.comecar(vigia.modo)
    vigia.falando(RESPOSTA)
    for referencia, mic in zip(_quadros(jarvis), _quadros(microfone), strict=False):
        vigia.portao.referencia(referencia)
        atrasado.tique()
        quadro = Quadro(0, mic, 0)
        acao = vigia.ouvir(quadro, fala_no_vad=quadro.energia_db > LIMIAR_DO_VAD_DB)
        if acao is Acao.CORTAR:
            return True, str(vigia.decisoes[-1].motivo)
    vigia.terminar()
    motivo = str(vigia.decisoes[-1].motivo) if vigia.decisoes else "nenhuma_decisao"
    return False, motivo


def medir(
    asr: MotorDeAsr,
    falar: Callable[[str], bytes],
    *,
    dica: str,
    latencia_ms: float,
    turnos_antes: int,
    casos: Sequence[Caso],
    portao: Callable[[], PortaoDeEco] = PortaoDeEco,
) -> list[Resultado]:
    jarvis = _no_nivel(falar(RESPOSTA), -12.0)
    comentario = falar(COMENTARIO)
    ditas = {frase: falar(frase) for frase in {c.frase for c in casos}}
    sala = ruido_rosa(len(jarvis) / 32, aleatorio=Random(3), pico=1.0)
    sala = _no_nivel(sala, RUIDO_DA_SALA_DB)
    transcrever = _transcritor(asr, dica)
    resultados = []
    for caso in casos:
        atrasado = _Atrasado(latencia_ms)
        vigia = VigiaDeInterrupcao(
            transcrever=transcrever,
            palavra=DetectorDePalavra(),
            enviar=atrasado,
            portao=portao(),
        )
        o_eco = eco(jarvis, atraso_ms=ATRASO_DO_ECO_MS, ganho_db=-caso.perda_db)
        nivel = caso.nivel_db if caso.nivel_db is not None else -18.0
        for vez in range(turnos_antes):
            # Respostas anteriores: o portão aprende a perda — com o dono comentando por cima.
            dono = _no_nivel(comentario, -12.0 + nivel)
            mic = misturar(o_eco, sala, silencio(1000 + 700 * vez) + dono)
            _falar(vigia, atrasado, jarvis, mic)
        trechos = [o_eco, sala]
        if caso.nivel_db is not None:
            dono = _no_nivel(ditas[caso.frase], -12.0 + caso.nivel_db)
            trechos.append(silencio(COMECO_DO_DONO_MS) + dono)
        cortou, motivo = _falar(vigia, atrasado, jarvis, misturar(*trechos))
        resultados.append(Resultado(caso, cortou, motivo, vigia.portao.perda_db))
    return resultados


def casos_padrao() -> list[Caso]:
    com_o_dono = [
        Caso(perda, nivel, frase)
        for perda in PERDAS_DB
        for nivel in NIVEIS_DO_DONO_DB
        for frase in FRASES
    ]
    so_o_eco = [Caso(perda, None, "") for perda in PERDAS_DB]
    return com_o_dono + so_o_eco


def resumo(resultados: Sequence[Resultado]) -> str:
    linhas = ["| perda do eco | dono (rel.) | frase | cortou | motivo | perda aprendida |"]
    linhas.append("|---|---|---|---|---|---|")
    for r in resultados:
        dono = "—" if r.caso.nivel_db is None else f"{r.caso.nivel_db:+.0f} dB"
        frase = r.caso.frase or "(só o eco)"
        linhas.append(
            f"| {r.caso.perda_db:.0f} dB | {dono} | {frase} | {'sim' if r.cortou else 'não'} "
            f"| {r.motivo} | {r.perda_aprendida_db:.1f} dB |"
        )
    hits = [r for r in resultados if r.caso.nivel_db is not None]
    falsos = [r for r in resultados if r.caso.nivel_db is None]
    linhas.append("")
    linhas.append(
        f"**Corte com o nome: {sum(r.cortou for r in hits)}/{len(hits)}** · "
        f"**falso corte pelo eco: {sum(r.cortou for r in falsos)}/{len(falsos)}**"
    )
    return "\n".join(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--latencia-ms", type=float, default=600.0)
    parser.add_argument("--turnos-antes", type=int, default=3)
    parser.add_argument("--modelo", default="small")
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
    asr = motor_de_asr(configuracao, raiz=raiz, cancelado=lambda: False, dica=dica)
    tts = motor_de_tts(configuracao, raiz=raiz, cancelado=lambda: False)
    resultados = medir(
        asr,
        tts.sintetizar,
        dica=dica,
        latencia_ms=args.latencia_ms,
        turnos_antes=args.turnos_antes,
        casos=casos_padrao(),
    )
    texto = resumo(resultados)
    print(texto)
    if args.publicar is not None:
        args.publicar.write_text(texto + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
