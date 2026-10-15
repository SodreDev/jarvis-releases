"""audio-io — captura e playback, perto do dispositivo (SPEC §2).

Responsabilidade: AEC, redução de ruído, AGC, VAD barato, captura em frames de
20 ms, playback cancelável, `PlaybackProgress` com `played_ms` real.

Proibições: não decide turno, não fala com LLM.
"""
