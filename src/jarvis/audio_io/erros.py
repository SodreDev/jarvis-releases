"""Erros do caminho de áudio. Recusar é melhor do que entregar silêncio em silêncio."""

from __future__ import annotations


class ErroDeAudio(RuntimeError):
    """Base dos erros do `audio-io`."""


class FormatoNaoSuportado(ErroDeAudio):
    """WAV que não é PCM16 mono 16 kHz: recusado na abertura, não reamostrado por engano."""


class DispositivoIndisponivel(ErroDeAudio):
    """Pediram dispositivo real e não há backend instalado (ou não há dispositivo)."""


class DispositivoProibidoEmCI(ErroDeAudio):
    """Aceite (a) do F1-01: com `CI=1` ninguém abre placa de som, nem por acidente."""
