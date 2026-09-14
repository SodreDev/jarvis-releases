"""K — contrato (F2-08): `jarvis.platform.linux.media` (ainda não existe —
import dentro de cada teste). `xfail(strict=True, reason="F2-08")`.

MPRIS: DOIS players D-Bus falsos no barramento privado
(`private_session_bus` + `tests/fakes/dbus_services.fake_dbus_service`).
"""
import pytest

from tests.fakes.dbus_services import fake_dbus_service

pytestmark = [pytest.mark.linux_only, pytest.mark.xfail(strict=True, reason="F2-08")]


def _spawn_player(exit_stack, suffix: str, *, status: str, title: str, artist: str):
    ctx = fake_dbus_service(
        f"org.mpris.MediaPlayer2.{suffix}",
        "/org/mpris/MediaPlayer2",
        "org.mpris.MediaPlayer2.Player",
    )
    mock, real = exit_stack.enter_context(ctx)
    mock.AddProperty("org.mpris.MediaPlayer2.Player", "PlaybackStatus", status)
    mock.AddProperty(
        "org.mpris.MediaPlayer2.Player",
        "Metadata",
        {"xesam:title": title, "xesam:artist": [artist]},
    )
    mock.AddMethod("org.mpris.MediaPlayer2.Player", "PlayPause", "", "", "")
    mock.AddMethod("org.mpris.MediaPlayer2.Player", "Next", "", "", "")
    mock.AddMethod("org.mpris.MediaPlayer2.Player", "Previous", "", "", "")
    return mock, real


def test_picks_the_playing_player_over_paused(private_session_bus):
    from contextlib import ExitStack

    from jarvis.platform.linux.media import MprisMedia

    with ExitStack() as stack:
        _spawn_player(stack, "vlc", status="Paused", title="Pausada", artist="X")
        mock_playing, real_playing = _spawn_player(
            stack, "spotify", status="Playing", title="Tocando", artist="Y"
        )

        info = MprisMedia().now_playing()
        assert info["title"] == "Tocando"

        MprisMedia().play_pause()
        # a chamada deve ter ido pro player QUE ESTAVA tocando, não pro pausado
        assert mock_playing.GetCalls()


def test_next_and_previous_go_to_active_player(private_session_bus):
    from contextlib import ExitStack

    from jarvis.platform.linux.media import MprisMedia

    with ExitStack() as stack:
        mock, _real = _spawn_player(stack, "spotify", status="Playing", title="A", artist="B")
        MprisMedia().next_track()
        MprisMedia().previous_track()
        calls = [c[1] for c in mock.GetCalls()]
        assert "Next" in calls
        assert "Previous" in calls


def test_no_player_raises_capability_unavailable(private_session_bus):
    from jarvis.platform.common.errors import CapabilityUnavailable
    from jarvis.platform.linux.media import MprisMedia

    try:
        MprisMedia().now_playing()
    except CapabilityUnavailable as e:
        assert "nenhum player MPRIS" in str(e)
    else:
        raise AssertionError("esperava CapabilityUnavailable sem nenhum player no barramento")


def test_playerctl_fallback_play_pause(fake_tools):
    from jarvis.platform.linux.media import PlayerctlMedia

    calls = fake_tools({"playerctl": "true"})
    PlayerctlMedia().play_pause()
    assert "play-pause" in calls["playerctl"].read_text()


def test_playerctl_fallback_metadata_format(fake_tools):
    from jarvis.platform.linux.media import PlayerctlMedia

    fake_tools({"playerctl": 'echo "Musica\tArtista\tspotify\tPlaying"'})
    info = PlayerctlMedia().now_playing()
    assert info["title"] == "Musica"
    assert info["artist"] == "Artista"
