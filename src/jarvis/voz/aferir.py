"""Dois testes que o dono manda rodar: "o microfone pega?" e "a voz sai?" (ADR-0019).

**Por que isto não mora na janela.** A janela é apresentação: ela não abre dispositivo, não
carrega motor e não sabe o que é um quadro de 20 ms (ADR-0019, e há teste que cobra o
`import`). Mas a aba de diagnóstico precisa dos dois testes — e eles são do mesmo tipo de
coisa que o laço faz, com as mesmas peças do `audio_io` e o mesmo portão de motor do F1-09.
Então eles ficam aqui, ao lado do laço, e a tela só chama.

**O que cada um prova, e o que nenhum dos dois prova.** O teste de microfone abre a fonte do
ambiente e mede energia por quadro: ele responde "chega sinal?" e "quanto?", não "a sua voz é
entendida" — WER é outro assunto (F1-16). O teste de voz sintetiza uma frase curta e entrega
ao sumidouro: ele responde "o motor produz áudio e o sumidouro aceita?", não "soa bem", que é
o ouvido do dono.

Os dois são **cancelávies e com teto**: rodam por um número de quadros, e quem chama pode
parar no meio (a tela, quando o dono fecha a aba). Teste de diagnóstico que não termina é
diagnóstico que vira travamento.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.audio_io.backend import fonte_do_ambiente, sumidouro_do_ambiente
from jarvis.audio_io.captura import SEGUNDOS_POR_QUADRO
from jarvis.audio_io.erros import ErroDeAudio
from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.rede import ErroDeRede
from jarvis.relogio import Relogio, RelogioDoSistema
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.config import Configuracao
from jarvis.voz.interface import Onde
from jarvis.voz.registro import MotorRecusado

FRASE_DE_TESTE: Final = "Olá. Sou o Jarvis, e esta é a minha voz."
SEGUNDOS_PADRAO: Final = 3.0
PISO_DB: Final = -90.0


@dataclass(frozen=True, slots=True)
class NivelDoMicrofone:
    """O que a fonte entregou no período medido. `erro` preenchido é recusa, não silêncio."""

    quadros: int = 0
    pico_db: float = PISO_DB
    medio_db: float = PISO_DB
    device_id: str = ""
    erro: str = ""

    @property
    def deu_certo(self) -> bool:
        return not self.erro and self.quadros > 0

    def frase(self) -> str:
        """Uma frase que o dono entende sem saber o que é dBFS."""
        if self.erro:
            return self.erro
        if self.quadros == 0:
            return "a fonte abriu e não entregou nenhum quadro"
        if self.pico_db <= PISO_DB + 1:
            return (
                f"silêncio digital em {self.quadros} quadros ({self.device_id}): o dispositivo "
                "abriu, e nada chegou. Confira se o microfone certo está escolhido e se ele "
                "não está mudo no sistema"
            )
        if self.pico_db < -45.0:
            return (
                f"muito baixo: pico de {self.pico_db:.0f} dB ({self.device_id}). Fale mais "
                "perto, ou aumente o ganho do microfone no sistema"
            )
        return f"chegando som: pico de {self.pico_db:.0f} dB, média {self.medio_db:.0f} dB"


@dataclass(frozen=True, slots=True)
class ProvaDeVoz:
    """O que a síntese produziu e o que o sumidouro aceitou."""

    amostras: int = 0
    primeiro_pedaco_ms: float = 0.0
    total_ms: float = 0.0
    motor: str = ""
    onde: str = ""
    erro: str = ""

    @property
    def deu_certo(self) -> bool:
        return not self.erro and self.amostras > 0

    @property
    def duracao_s(self) -> float:
        return self.amostras / TAXA_PADRAO

    def frase(self) -> str:
        if self.erro:
            return self.erro
        if self.amostras == 0:
            return "o motor não produziu áudio nenhum"
        return (
            f"{self.motor} [{self.onde}]: {self.duracao_s:.1f} s de áudio, primeiro pedaço em "
            f"{self.primeiro_pedaco_ms:.0f} ms, síntese inteira em {self.total_ms:.0f} ms"
        )


@dataclass(slots=True)
class _Media:
    soma: float = 0.0
    n: int = 0
    pico: float = field(default=PISO_DB)

    def ver(self, db: float) -> None:
        self.soma += db
        self.n += 1
        self.pico = max(self.pico, db)


def medir_microfone(
    configuracao: Configuracao,
    *,
    segundos: float = SEGUNDOS_PADRAO,
    ambiente: Mapping[str, str] | None = None,
    relogio: Relogio | None = None,
    caminho_de_entrada: Path | None = None,
    ao_quadro: Callable[[float], None] | None = None,
    cancelado: Callable[[], bool] | None = None,
) -> NivelDoMicrofone:
    """Abre a fonte, mede energia por quadro e fecha. Nunca deixa o dispositivo aberto.

    `ao_quadro` recebe o dB de cada quadro — é o que move a barrinha de nível na tela sem a
    tela precisar saber o que é um quadro. `cancelado` deixa o dono fechar a aba no meio.
    """
    _ = configuracao
    fonte = fonte_do_ambiente(
        relogio=relogio or RelogioDoSistema(), caminho=caminho_de_entrada, ambiente=ambiente
    )
    try:
        fonte.abrir()
    except ErroDeAudio as erro:
        return NivelDoMicrofone(erro=str(erro))
    media = _Media()
    teto = max(1, int(segundos / SEGUNDOS_POR_QUADRO))
    try:
        for quadro in fonte.quadros():
            db = quadro.energia_db
            media.ver(db)
            if ao_quadro is not None:
                ao_quadro(db)
            if media.n >= teto or (cancelado is not None and cancelado()):
                break
    except ErroDeAudio as erro:
        return NivelDoMicrofone(quadros=media.n, erro=str(erro))
    finally:
        fonte.fechar()
    return NivelDoMicrofone(
        quadros=media.n,
        pico_db=media.pico,
        medio_db=media.soma / media.n if media.n else PISO_DB,
        device_id=fonte.device_id,
    )


def provar_voz(
    configuracao: Configuracao,
    *,
    raiz: Path,
    texto: str = FRASE_DE_TESTE,
    ambiente: Mapping[str, str] | None = None,
    caminho_de_saida: Path | None = None,
    cancelado: Callable[[], bool] | None = None,
) -> ProvaDeVoz:
    """Sintetiza uma frase curta pelo motor configurado e entrega ao sumidouro do ambiente.

    Usa o mesmo caminho do laço — o portão de motor da ADR-0017, o `SintetizadorEmStreaming`
    do F1-09 — porque um teste de voz que sintetizasse por outro caminho provaria outro
    caminho.
    """
    from jarvis.agentd.tts import SintetizadorEmStreaming
    from jarvis.barramento.envelope import uuid7
    from jarvis.voz.app import AplicativoIndisponivel, motor_de_tts

    parar = cancelado or (lambda: False)
    try:
        motor = motor_de_tts(configuracao, raiz=raiz, cancelado=parar, ambiente=ambiente)
    except (AplicativoIndisponivel, ErroDeAudio, SegredoAusente, MotorRecusado, ErroDeRede) as erro:
        return ProvaDeVoz(erro=f"{configuracao.tts}: {erro}")
    except ImportError as erro:  # falta o grupo da voz local (epitran, onnxruntime)
        return ProvaDeVoz(
            erro=f"{configuracao.tts}: falta a biblioteca {erro.name or erro} — `uv sync "
            "--group voz` (a voz local) ou escolha outro motor de fala"
        )
    try:
        sumidouro = sumidouro_do_ambiente(caminho=caminho_de_saida, ambiente=ambiente)
        sumidouro.abrir()
    except (ErroDeAudio, ValueError) as erro:
        return ProvaDeVoz(erro=str(erro), motor=motor.nome, onde=str(motor.onde))

    sintetizador = SintetizadorEmStreaming(
        motor=motor, session_id=str(uuid7()), epoch=1, cancelado=parar
    )
    comeco = time.monotonic()
    primeiro = 0.0
    amostras = 0
    try:
        for pedaco, _trecho in sintetizador.pedacos(texto):
            if primeiro == 0.0:
                primeiro = (time.monotonic() - comeco) * 1000.0
            amostras += sumidouro.escrever(pedaco.amostras)
            if parar():
                break
    except ErroDeAudio as erro:
        return ProvaDeVoz(erro=str(erro), motor=motor.nome, onde=str(motor.onde))
    finally:
        sumidouro.fechar()
    return ProvaDeVoz(
        amostras=amostras,
        primeiro_pedaco_ms=primeiro,
        total_ms=(time.monotonic() - comeco) * 1000.0,
        motor=motor.nome,
        onde="local" if motor.onde is Onde.LOCAL else "NUVEM",
    )
