"""A cadeia AEC → NR → AGC com referência do nosso próprio playback (cartão F1-04).

A referência não é "o que o microfone ouviu": é **o que nós mandamos para o alto-falante**.
Por isso ela vem do sumidouro do F1-03 (a fila de playback chama `referencia` com cada fatia
que escreveu, com o `device_id` de saída), e não de uma segunda captura.

`aec_ok` no `AudioActivity` é o que o resto do sistema vê. Ele fica **falso** nos casos em que
a referência deixou de valer, cada um com motivo próprio:

- `dispositivo_trocado` — a saída mudou de dispositivo no meio; zera o filtro, porque o
  caminho acústico é outro;
- `taxa_diferente` — a referência chega em outra taxa; zera o filtro e recusa a referência;
- `referencia_ausente` — estamos tocando e não chega referência; não adapta contra silêncio,
  senão aprende o caminho errado;
- `referencia_atrasada` — a referência acumulou mais do que o filtro cobre; descarta o
  atraso, porque o alinhamento já se perdeu.

Quem transforma `aec_ok = false` em `Cancel(reason: aec_fail)` é o **`agentd`** — a §3.2 fixa
que `Cancel` é dele. O `audio-io` relata o fato e **pausa o playback** enquanto a referência
não vale: continuar falando sem AEC é o caminho curto para o assistente se interromper sozinho.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from jarvis.audio_io.dsp import (
    CanceladorDeEco,
    ControleDeGanho,
    SupressorDeRuido,
    energia_db_de,
    erle_db,
    para_bytes,
    para_float,
)
from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    BYTES_POR_AMOSTRA,
    BYTES_POR_QUADRO,
    TAXA_PADRAO,
    Quadro,
)

MOTIVO_AEC_FAIL: Final = "aec_fail"


class MotivoDeFalha(StrEnum):
    """Por que a referência deixou de valer. Vai no log e no relatório, não em prosa."""

    DISPOSITIVO_TROCADO = "dispositivo_trocado"
    TAXA_DIFERENTE = "taxa_diferente"
    REFERENCIA_AUSENTE = "referencia_ausente"
    REFERENCIA_ATRASADA = "referencia_atrasada"


@dataclass(frozen=True, slots=True)
class Processado:
    """Um quadro depois da cadeia, com o número que diz se ela funcionou."""

    quadro: Quadro
    erle_db: float
    aec_ok: bool
    motivo: MotivoDeFalha | None = None

    @property
    def energia_db(self) -> float:
        return self.quadro.energia_db


@dataclass(slots=True)
class CadeiaDeAec:
    """AEC → NR → AGC, alimentada pela referência de loopback do nosso playback."""

    taxa: int = TAXA_PADRAO
    device_id_de_saida: str = ""
    cancelador: CanceladorDeEco = field(default_factory=CanceladorDeEco)
    supressor: SupressorDeRuido = field(default_factory=SupressorDeRuido)
    controle: ControleDeGanho = field(default_factory=ControleDeGanho)
    usar_nr: bool = True
    usar_agc: bool = True

    aec_ok: bool = True
    motivo: MotivoDeFalha | None = None
    quadros_processados: int = 0
    amostras_de_referencia: int = 0
    _referencia: bytearray = field(default_factory=bytearray, repr=False)

    @property
    def limite_de_atraso(self) -> int:
        """Quanto de referência pode esperar na fila antes de ser atraso (em bytes)."""
        return 2 * self.cancelador.particoes * BYTES_POR_QUADRO

    @property
    def referencia_pendente(self) -> int:
        return len(self._referencia) // BYTES_POR_AMOSTRA

    def referencia(self, amostras: bytes, *, device_id: str = "", taxa: int | None = None) -> None:
        """O que acabou de ir para o alto-falante. Chamado pela fila de playback (F1-03)."""
        if taxa is not None and taxa != self.taxa:
            self._falhar(MotivoDeFalha.TAXA_DIFERENTE)
            return
        if device_id and self.device_id_de_saida and device_id != self.device_id_de_saida:
            self.device_id_de_saida = device_id
            self._falhar(MotivoDeFalha.DISPOSITIVO_TROCADO)
            return
        if device_id and not self.device_id_de_saida:
            self.device_id_de_saida = device_id
        self._referencia.extend(amostras)
        self.amostras_de_referencia += len(amostras) // BYTES_POR_AMOSTRA
        if len(self._referencia) > self.limite_de_atraso:
            # Mais referência do que o filtro cobre: o alinhamento já se perdeu.
            del self._referencia[: len(self._referencia) - self.limite_de_atraso]
            self._falhar(MotivoDeFalha.REFERENCIA_ATRASADA)

    def processar(self, quadro: Quadro, *, tocando: bool = False) -> Processado:
        """Passa um quadro de 20 ms pela cadeia. `tocando` diz se há playback em curso."""
        if quadro.taxa != self.taxa:
            self._falhar(MotivoDeFalha.TAXA_DIFERENTE)
        referencia_bytes = bytes(self._referencia[:BYTES_POR_QUADRO])
        del self._referencia[: len(referencia_bytes)]
        if tocando and not referencia_bytes:
            self._falhar(MotivoDeFalha.REFERENCIA_AUSENTE)
        if not tocando and self.referencia_pendente == 0:
            # Nada para cancelar: a falha de referência não sobrevive ao fim do playback.
            self._limpar_falha()

        microfone = para_float(quadro.amostras)
        referencia = para_float(referencia_bytes.ljust(BYTES_POR_QUADRO, b"\x00"))
        residuo, _ = self.cancelador.processar(microfone, referencia)
        medida = erle_db(microfone, residuo)

        limpo = residuo
        if self.usar_nr:
            limpo = self.supressor.processar(limpo)
        if self.usar_agc:
            limpo = self.controle.processar(limpo)

        self.quadros_processados += 1
        return Processado(
            quadro=Quadro(
                indice=quadro.indice,
                amostras=para_bytes(limpo),
                ts_mono_ns=quadro.ts_mono_ns,
                taxa=quadro.taxa,
            ),
            erle_db=medida,
            aec_ok=self.aec_ok,
            motivo=self.motivo,
        )

    def energia_de_saida_db(self, processado: Processado) -> float:
        return energia_db_de(para_float(processado.quadro.amostras))

    def _falhar(self, motivo: MotivoDeFalha) -> None:
        self.aec_ok = False
        self.motivo = motivo
        if motivo in (MotivoDeFalha.DISPOSITIVO_TROCADO, MotivoDeFalha.TAXA_DIFERENTE):
            self.cancelador.zerar()  # outro caminho acústico: o que foi aprendido não serve

    def _limpar_falha(self) -> None:
        self.aec_ok = True
        self.motivo = None


def quadros_de(amostras: bytes, *, ts_inicial_ns: int = 0, taxa: int = TAXA_PADRAO) -> list[Quadro]:
    """Fatia um sinal em quadros de 20 ms (o que a cadeia consome), sem completar o último."""
    return [
        Quadro(
            indice=i,
            amostras=amostras[i * BYTES_POR_QUADRO : (i + 1) * BYTES_POR_QUADRO],
            ts_mono_ns=ts_inicial_ns + i * 20_000_000,
            taxa=taxa,
        )
        for i in range(len(amostras) // BYTES_POR_QUADRO)
    ]


__all__ = [
    "AMOSTRAS_POR_QUADRO",
    "MOTIVO_AEC_FAIL",
    "CadeiaDeAec",
    "MotivoDeFalha",
    "Processado",
    "quadros_de",
]
