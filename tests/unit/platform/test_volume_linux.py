"""K — contrato (F2-03): `jarvis.platform.linux.volume` (ainda não
existe — import dentro de cada teste). `xfail(strict=True, reason="F2-03")`.
Ferramentas falsas via `fake_tools` (`wpctl`/`pactl`), nunca o PipeWire
real do host.
"""
import pytest

pytestmark = [pytest.mark.linux_only]


# ── WpctlVolume ──


def test_wpctl_get_output_parses_volume(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    fake_tools({"wpctl": 'echo "Volume: 0.40"'})
    assert WpctlVolume().get_output() == 40


def test_wpctl_get_output_muted(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    fake_tools({"wpctl": 'echo "Volume: 0.40 [MUTED]"'})
    assert WpctlVolume().get_output() == 40


def test_wpctl_get_output_boost_above_100(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    fake_tools({"wpctl": 'echo "Volume: 1.20"'})
    assert WpctlVolume().get_output() == 120


def test_wpctl_set_output_calls_with_limit(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": "true"})
    WpctlVolume().set_output(40)
    assert "set-volume @DEFAULT_AUDIO_SINK@ 0.40 --limit 1.0" in calls["wpctl"].read_text()


def test_wpctl_set_input_targets_source(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": "true"})
    WpctlVolume().set_input(70)
    assert "@DEFAULT_AUDIO_SOURCE@ 0.70" in calls["wpctl"].read_text()


def test_wpctl_toggle_output_mute(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": "true"})
    WpctlVolume().toggle_output_mute()
    assert "set-mute @DEFAULT_AUDIO_SINK@ toggle" in calls["wpctl"].read_text()


def test_wpctl_step_output(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": "true"})
    WpctlVolume().step_output(2)
    assert "set-volume @DEFAULT_AUDIO_SINK@ 2%+" in calls["wpctl"].read_text()


def test_wpctl_step_output_negative(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": "true"})
    WpctlVolume().step_output(-2)
    assert "set-volume @DEFAULT_AUDIO_SINK@ 2%-" in calls["wpctl"].read_text()


def test_wpctl_unexpected_output_raises_handled(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    fake_tools({"wpctl": 'echo "lixo inesperado"'})
    try:
        WpctlVolume().get_output()
    except Exception:
        pass  # o adapter deve tratar; o system_ctrl é quem formata a mensagem
    else:
        raise AssertionError("esperava exceção tratável com saída inesperada")


# ── PactlVolume ──


def test_pactl_get_output_parses_first_percentage(fake_tools):
    from jarvis.platform.linux.volume import PactlVolume

    fake_tools(
        {
            "pactl": (
                'if [ "$1" = "get-sink-volume" ]; then '
                'echo "Volume: front-left: 26214 /  40% / -23.86 dB,   front-right: 26214 /  40% / -23.86 dB"; '
                "fi"
            )
        }
    )
    assert PactlVolume().get_output() == 40


def test_pactl_set_output(fake_tools):
    from jarvis.platform.linux.volume import PactlVolume

    calls = fake_tools({"pactl": "true"})
    PactlVolume().set_output(55)
    assert "set-sink-volume @DEFAULT_SINK@ 55%" in calls["pactl"].read_text()


def test_pactl_get_input_source(fake_tools):
    from jarvis.platform.linux.volume import PactlVolume

    fake_tools({"pactl": 'echo "Volume: front-left: 13107 /  20% / -35.00 dB"'})
    assert PactlVolume().get_input() == 20


def test_pactl_toggle_mute(fake_tools):
    from jarvis.platform.linux.volume import PactlVolume

    calls = fake_tools({"pactl": "true"})
    PactlVolume().toggle_output_mute()
    assert "set-sink-mute @DEFAULT_SINK@ toggle" in calls["pactl"].read_text()
