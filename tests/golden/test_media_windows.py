"""C — caracterização (F2-08): teclas virtuais de mídia e SMTC/PowerShell
no Windows continuam idênticos depois da fachada `Cap.MEDIA` entrar.
"""
from tests.golden.legacy_31bc0ce import (
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    VK_MEDIA_STOP,
    VK_VOLUME_DOWN,
    VK_VOLUME_MUTE,
    VK_VOLUME_UP,
    legacy_faixa_anterior,
    legacy_get_media_info_ps,
    legacy_mutar,
    legacy_o_que_esta_tocando,
    legacy_parar,
    legacy_play_pause,
    legacy_press_key,
    legacy_proxima_faixa,
    legacy_volume_down,
    legacy_volume_up,
)

KEYEVENTF_KEYUP = 0x0002


def _recorder():
    calls = []
    return calls, (lambda *a: calls.append(a))


def test_press_key_down_then_up_same_vk():
    calls, fake = _recorder()
    sleeps = []
    legacy_press_key(fake, VK_MEDIA_PLAY_PAUSE, sleep_fn=sleeps.append)
    assert calls == [
        (VK_MEDIA_PLAY_PAUSE, 0, 0, 0),
        (VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0),
    ]
    assert sleeps == [0.05]


def test_play_pause():
    calls, fake = _recorder()
    assert legacy_play_pause(fake, sleep_fn=lambda s: None) == "Play/Pause enviado, senhor."
    assert calls[0][0] == VK_MEDIA_PLAY_PAUSE


def test_parar():
    calls, fake = _recorder()
    assert legacy_parar(fake, sleep_fn=lambda s: None) == "Mídia parada, senhor."
    assert calls[0][0] == VK_MEDIA_STOP


def test_proxima_faixa():
    calls, fake = _recorder()
    assert legacy_proxima_faixa(fake, sleep_fn=lambda s: None) == "Próxima faixa, senhor."
    assert calls[0][0] == VK_MEDIA_NEXT_TRACK


def test_faixa_anterior():
    calls, fake = _recorder()
    assert legacy_faixa_anterior(fake, sleep_fn=lambda s: None) == "Faixa anterior, senhor."
    assert calls[0][0] == VK_MEDIA_PREV_TRACK


def test_mutar():
    calls, fake = _recorder()
    assert legacy_mutar(fake, sleep_fn=lambda s: None) == "Volume mutado/desmutado, senhor."
    assert calls[0][0] == VK_VOLUME_MUTE


def test_volume_up_default_3_steps():
    calls, fake = _recorder()
    msg = legacy_volume_up(fake, sleep_fn=lambda s: None)
    assert msg == "Volume aumentado 3 nível(is), senhor."
    assert [c[0] for c in calls].count(VK_VOLUME_UP) == 3 * 2  # down+up por passo


def test_volume_down_custom_steps():
    calls, fake = _recorder()
    msg = legacy_volume_down(fake, steps=5, sleep_fn=lambda s: None)
    assert msg == "Volume reduzido 5 nível(is), senhor."
    assert [c[0] for c in calls].count(VK_VOLUME_DOWN) == 5 * 2


class _FakeRun:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_get_media_info_ps_parses_pipe_separated():
    run_fn = lambda *a, **k: _FakeRun("Musica|Artista|Playing|App.exe!App")
    info = legacy_get_media_info_ps(run_fn)
    assert info == {"title": "Musica", "artist": "Artista", "status": "Playing", "app": "App.exe!App"}


def test_get_media_info_ps_null_session():
    run_fn = lambda *a, **k: _FakeRun("NULL")
    assert legacy_get_media_info_ps(run_fn) == {}


def test_get_media_info_ps_exception_returns_empty():
    def _boom(*a, **k):
        raise OSError("powershell não encontrado")

    assert legacy_get_media_info_ps(_boom) == {}


def test_o_que_esta_tocando_with_artist():
    run_fn = lambda *a, **k: _FakeRun("Musica|Artista|Playing|App.exe!Spotify")
    msg = legacy_o_que_esta_tocando(run_fn)
    assert msg == "Está tocando 'Musica' — Artista, via Spotify, senhor."


def test_o_que_esta_tocando_without_artist():
    run_fn = lambda *a, **k: _FakeRun("Musica||Paused|App.exe!Spotify")
    msg = legacy_o_que_esta_tocando(run_fn)
    assert msg == "Está pausado 'Musica' via Spotify, senhor."


def test_o_que_esta_tocando_nothing_playing():
    run_fn = lambda *a, **k: _FakeRun("NULL")
    assert legacy_o_que_esta_tocando(run_fn) == "Nenhuma mídia em reprodução detectada, senhor."
