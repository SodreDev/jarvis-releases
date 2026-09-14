"""C — caracterização (F2-03): volume/mic (pycaw) no Windows continuam
idênticos depois da fachada `Cap.VOLUME` entrar.
"""
import types

from tests.golden.legacy_31bc0ce import (
    legacy_discover_audio_volume_interface,
    legacy_discover_mic_volume_interface,
    legacy_get_mic_volume,
    legacy_get_volume,
    legacy_set_mic_volume,
    legacy_set_volume,
)


class _FakeVolInterface:
    def __init__(self, scalar=0.5):
        self._scalar = scalar
        self.set_calls = []

    def SetMasterVolumeLevelScalar(self, value, _reserved):
        self.set_calls.append(value)
        self._scalar = value

    def GetMasterVolumeLevelScalar(self):
        return self._scalar


def test_set_volume_clamps_above_100():
    fake_vol = _FakeVolInterface()
    msg = legacy_set_volume(lambda: fake_vol, 150)
    assert fake_vol.set_calls == [1.0]
    assert msg == "Volume do sistema ajustado para 100%, Senhor."


def test_set_volume_clamps_below_0():
    fake_vol = _FakeVolInterface()
    msg = legacy_set_volume(lambda: fake_vol, -20)
    assert fake_vol.set_calls == [0.0]
    assert msg == "Volume do sistema ajustado para 0%, Senhor."


def test_set_volume_normal_value():
    fake_vol = _FakeVolInterface()
    msg = legacy_set_volume(lambda: fake_vol, 42)
    assert fake_vol.set_calls == [0.42]
    assert msg == "Volume do sistema ajustado para 42%, Senhor."


def test_get_volume_message():
    fake_vol = _FakeVolInterface(scalar=0.73)
    assert legacy_get_volume(lambda: fake_vol) == "Volume atual do sistema: 73%, Senhor."


def test_set_volume_error_message():
    def _boom():
        raise RuntimeError("sem dispositivo")

    assert legacy_set_volume(_boom, 50) == "Não foi possível ajustar o volume: sem dispositivo"


def test_get_mic_volume_message():
    fake_vol = _FakeVolInterface(scalar=0.8)
    assert legacy_get_mic_volume(lambda: fake_vol) == "Volume atual do microfone: 80%, Senhor."


def test_set_mic_volume_message():
    fake_vol = _FakeVolInterface()
    msg = legacy_set_mic_volume(lambda: fake_vol, 65)
    assert fake_vol.set_calls == [0.65]
    assert msg == "Volume do microfone ajustado para 65%, Senhor."


def test_get_mic_volume_error_message():
    def _boom():
        raise RuntimeError("nenhum microfone")

    assert legacy_get_mic_volume(_boom) == "Não foi possível obter o volume do microfone: nenhum microfone"


# ── discovery (_get_audio_volume / _get_mic_volume) ──


def _fake_com_env(*, speakers=None, mic=None, mic_is_none=False):
    class _Iface:
        pass

    class _AudioUtilities:
        def GetSpeakers(self):
            return speakers if speakers is not None else _DevWithActivate()

        def GetMicrophone(self):
            if mic_is_none:
                return None
            return mic if mic is not None else _DevWithActivate()

    class _DevWithActivate:
        def Activate(self, _iid, _clsctx, _reserved):
            return _Iface()

    class _IAudioEndpointVolume:
        _iid_ = "IID_IAudioEndpointVolume"

    comtypes_mod = types.SimpleNamespace(CoInitialize=lambda: None)
    cast_fn = lambda interface, _pointer_type: interface
    pointer_fn = lambda t: t

    return dict(
        audio_utilities=_AudioUtilities(),
        iaudio_endpoint_volume=_IAudioEndpointVolume(),
        comtypes_mod=comtypes_mod,
        cast_fn=cast_fn,
        pointer_fn=pointer_fn,
        clsctx_all=1,
    )


def test_discover_audio_volume_direct_device():
    kwargs = _fake_com_env()
    iface = legacy_discover_audio_volume_interface(**kwargs)
    assert iface is not None


def test_discover_audio_volume_wrapper_with_dev_attribute():
    class _Wrapper:
        def __init__(self):
            class _Real:
                def Activate(self, *_a):
                    return "iface"

            self._dev = _Real()

    kwargs = _fake_com_env(speakers=_Wrapper())
    assert legacy_discover_audio_volume_interface(**kwargs) == "iface"


def test_discover_audio_volume_incompatible_device_raises():
    class _Useless:
        pass

    kwargs = _fake_com_env(speakers=_Useless())
    try:
        legacy_discover_audio_volume_interface(**kwargs)
    except RuntimeError as e:
        assert "Dispositivo de áudio incompatível" in str(e)
    else:
        raise AssertionError("esperava RuntimeError")


def test_discover_mic_volume_none_raises():
    kwargs = _fake_com_env(mic_is_none=True)
    try:
        legacy_discover_mic_volume_interface(**kwargs)
    except RuntimeError as e:
        assert str(e) == "Nenhum microfone encontrado no sistema."
    else:
        raise AssertionError("esperava RuntimeError")
