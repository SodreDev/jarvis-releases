"""Volume e microfone no Windows (F2-03): pycaw, cópia literal do system_ctrl.

W1/W2:
- ``_get_audio_volume``/``_get_mic_volume`` = corpos literais de
  comandos/system_ctrl.py (CoInitialize, wrapper ``_dev`` do pycaw, mensagens).
  As dependências COM podem ser injetadas (``com``) para os testes no Linux.
- ``get_output``/``get_input`` = ``int(GetMasterVolumeLevelScalar() * 100)``;
  ``set_output``/``set_input`` = ``SetMasterVolumeLevelScalar(pct / 100.0, None)``.
  O clamp 0-100 e as mensagens continuam no system_ctrl.
- ``toggle_*_mute`` (SetMute/GetMute) e ``step_output`` (VolumeStepUp/Down) são
  novos e ainda sem uso no Windows (D-F2-10: teclas virtuais até depois do N4).
"""
from __future__ import annotations

from ..common.base import BackendBase


def _com_deps(com):
    if com is None:
        import comtypes
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        return comtypes, cast, POINTER, CLSCTX_ALL, AudioUtilities, IAudioEndpointVolume
    return (
        com["comtypes_mod"], com["cast_fn"], com["pointer_fn"], com["clsctx_all"],
        com["audio_utilities"], com["iaudio_endpoint_volume"],
    )


def _get_audio_volume(com=None):
    """Obtém a interface de volume do sistema (robusta para diferentes versões pycaw)."""
    comtypes, cast, POINTER, CLSCTX_ALL, AudioUtilities, IAudioEndpointVolume = _com_deps(com)

    # Garante COM inicializado nesta thread (essencial quando chamado de threads)
    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # Já inicializado

    speakers = AudioUtilities.GetSpeakers()

    # Compatibilidade: pycaw pode retornar IMMDevice (COM) ou AudioDevice wrapper
    if not hasattr(speakers, 'Activate'):
        dev = getattr(speakers, '_dev', None)
        if dev is not None and hasattr(dev, 'Activate'):
            speakers = dev
        else:
            raise RuntimeError(
                f"Dispositivo de áudio incompatível: {type(speakers).__name__}"
            )

    interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _get_mic_volume(com=None):
    """Obtém a interface de volume do microfone padrão (input device)."""
    comtypes, cast, POINTER, CLSCTX_ALL, AudioUtilities, IAudioEndpointVolume = _com_deps(com)

    try:
        comtypes.CoInitialize()
    except OSError:
        pass

    mic = AudioUtilities.GetMicrophone()
    if mic is None:
        raise RuntimeError("Nenhum microfone encontrado no sistema.")

    if not hasattr(mic, 'Activate'):
        dev = getattr(mic, '_dev', None)
        if dev is not None and hasattr(dev, 'Activate'):
            mic = dev
        else:
            raise RuntimeError(
                f"Dispositivo de microfone incompatível: {type(mic).__name__}"
            )

    interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


class PycawVolume(BackendBase):
    name = "windows.pycaw"

    def __init__(self, ctx=None, *, com=None, get_audio_fn=None, get_mic_fn=None):
        self.ctx = ctx
        self._get_audio = get_audio_fn or (lambda: _get_audio_volume(com))
        self._get_mic = get_mic_fn or (lambda: _get_mic_volume(com))

    def get_output(self) -> int:
        vol = self._get_audio()
        return int(vol.GetMasterVolumeLevelScalar() * 100)

    def set_output(self, pct: int) -> None:
        vol = self._get_audio()
        vol.SetMasterVolumeLevelScalar(pct / 100.0, None)

    def get_input(self) -> int:
        vol = self._get_mic()
        return int(vol.GetMasterVolumeLevelScalar() * 100)

    def set_input(self, pct: int) -> None:
        vol = self._get_mic()
        vol.SetMasterVolumeLevelScalar(pct / 100.0, None)

    def toggle_output_mute(self) -> None:
        vol = self._get_audio()
        vol.SetMute(not vol.GetMute(), None)

    def toggle_input_mute(self) -> None:
        vol = self._get_mic()
        vol.SetMute(not vol.GetMute(), None)

    def step_output(self, delta_pct: int) -> None:
        """Passo do dispositivo (normalmente 2%): |delta|/2 passos, pelo menos 1."""
        if not delta_pct:
            return
        vol = self._get_audio()
        passo = vol.VolumeStepUp if delta_pct > 0 else vol.VolumeStepDown
        for _ in range(max(1, abs(int(delta_pct)) // 2)):
            passo(None)
