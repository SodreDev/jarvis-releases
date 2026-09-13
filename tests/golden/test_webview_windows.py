"""C/K (F1-06): `EdgeChromiumEngine` (Windows) precisa ser um no-op total —
prova que o comportamento Windows não muda quando o boot passa a montar
`_wv_start_kwargs` via `jarvis.platform.webview_engine()`.

`xfail(strict=True, reason="F1-06")`: a classe ainda não existe (import
dentro do teste).
"""
def test_edge_chromium_engine_prepare_env_is_noop():
    from jarvis.platform.windows.webview_engine import EdgeChromiumEngine

    environ = {"WEBVIEW2_ADDITIONAL_FLAGS": "--disable-extensions --disk-cache-size=67108864"}
    before = dict(environ)
    EdgeChromiumEngine().prepare_env(environ)
    assert environ == before


def test_edge_chromium_engine_start_kwargs_is_empty():
    from jarvis.platform.windows.webview_engine import EdgeChromiumEngine

    assert EdgeChromiumEngine().start_kwargs() == {}


def test_edge_chromium_engine_sandbox_state_is_na():
    from jarvis.platform.windows.webview_engine import EdgeChromiumEngine

    assert EdgeChromiumEngine().sandbox_state() == "n/a"
