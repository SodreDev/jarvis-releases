"""K F2-01 (AST, sem importar main.py): PTT e atalhos pelo backend de hotkeys.

- _ptt_iniciar/_ptt_finalizar têm, depois do guard de smoke, EXATAMENTE as
  instruções que viviam nos ramos PTT de _on_key_press/_on_key_release (31bc0ce);
- os ramos PTT agora só chamam _ptt_iniciar()/_ptt_finalizar();
- _start_keyboard_listener: portão → hk.listen_keys(...) → (senão) hk.bind com o PTT;
- gancho de smoke: JARVIS_SMOKE_HOTKEYS e JARVIS_SMOKE_PTT press/release.
"""
import ast
import textwrap
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"

# Ramos PTT de 31bc0ce, copiados do main.py antes da extração.
ORIGINAL_INICIAR = """
self.recording = True
self._notify_recording(True)
self._mic_frames.clear()
print("[PTT] Gravando...")
self._set_status("▤  OUVINDO...  (Solte G para enviar)", _RED)
self.root.after(0, lambda: self._lbl_mic_state.config(text="● REC", fg=_RED))
self._stop_tts()
threading.Thread(target=self._gravar_audio, daemon=True).start()
"""

ORIGINAL_FINALIZAR = """
self.recording = False
self._notify_recording(False)
print("[PTT] Parou. Enviando...")
self._set_status("⟳  Processando áudio...", _CYAN)
self.root.after(0, lambda: self._lbl_mic_state.config(text="MIC PRONTO", fg=_GREEN))
frames = list(self._mic_frames)
if frames:
    threading.Thread(target=self._processar_audio, args=(frames,), daemon=True).start()
else:
    self._set_status("PRONTO  |  Segure Shift+G para falar", _TEXT_DIM)
"""


def _tree():
    return ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))


def _func(tree, nome):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"{nome} não encontrada")


def _sem_docstring(corpo):
    if corpo and isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant):
        return corpo[1:]
    return corpo


def _unparse(stmts):
    return [ast.unparse(s) for s in stmts]


def _checa_extracao(nome, original, marcador):
    corpo = _sem_docstring(_func(_tree(), nome).body)
    guard = corpo[0]
    assert isinstance(guard, ast.If) and "_smoke_seconds" in ast.unparse(guard.test)
    assert marcador in ast.unparse(guard) and isinstance(guard.body[-1], ast.Return)
    assert _unparse(corpo[1:]) == _unparse(ast.parse(textwrap.dedent(original)).body)


def test_ptt_iniciar_e_o_ramo_antigo_literal():
    _checa_extracao("_ptt_iniciar", ORIGINAL_INICIAR, "JARVIS_SMOKE_PTT press")


def test_ptt_finalizar_e_o_ramo_antigo_literal():
    _checa_extracao("_ptt_finalizar", ORIGINAL_FINALIZAR, "JARVIS_SMOKE_PTT release")


def _ramo_ptt(nome_func, teste_esperado):
    func = _func(_tree(), nome_func)
    for node in ast.walk(func):
        if isinstance(node, ast.If) and ast.unparse(node.test) == teste_esperado:
            return node
    raise AssertionError(f"ramo PTT não encontrado em {nome_func}")


def test_ramos_ptt_so_chamam_as_funcoes_extraidas():
    press = _ramo_ptt("_on_key_press", "_is_g_key(key) and self._shift_held and (not self.recording)")
    release = _ramo_ptt("_on_key_release", "_is_g_key(key) and self.recording")
    assert _unparse(press.body) == ["self._ptt_iniciar()"]
    assert _unparse(release.body) == ["self._ptt_finalizar()"]


def test_start_keyboard_listener_listen_keys_antes_do_bind_do_ptt():
    func = _func(_tree(), "_start_keyboard_listener")
    chamadas = {}
    for n in ast.walk(func):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("listen_keys", "bind"):
            chamadas.setdefault(n.func.attr, n)
    assert chamadas["listen_keys"].lineno < chamadas["bind"].lineno
    fonte_bind = ast.unparse(chamadas["bind"])
    assert "HotkeyBinding('ptt'" in fonte_bind and "_ptt_trigger()" in fonte_bind
    assert "self._ptt_global_press" in fonte_bind and "self._ptt_global_release" in fonte_bind


def test_bind_do_ptt_roda_em_thread_daemon_portal_hotkeys():
    fonte = ast.unparse(_func(_tree(), "_start_keyboard_listener"))
    assert "threading.Thread(target=_bind_ptt, daemon=True, name='PortalHotkeys').start()" in fonte


def test_ptt_global_mesmas_condicoes_do_shift_g_via_root_after():
    press = ast.unparse(_func(_tree(), "_ptt_global_press"))
    release = ast.unparse(_func(_tree(), "_ptt_global_release"))
    assert "self._activation_mode == 'ptt' and (not self.recording)" in press and "self._ptt_iniciar()" in press
    assert "self._activation_mode == 'ptt' and self.recording" in release and "self._ptt_finalizar()" in release
    assert "self.root.after(0, _press)" in press and "self.root.after(0, _release)" in release


def test_smoke_ptt_press_so_no_smoke():
    fonte = ast.unparse(_func(_tree(), "_bind_ptt"))
    assert "_smoke_seconds() is not None and os.environ.get('JARVIS_SMOKE_PTT', '').strip() == 'press'" in fonte
    assert "invoke_shortcut" in fonte


def test_hotkeys_do_config_nao_viram_atalho_exclusivo():
    func = _func(_tree(), "_start_global_hotkeys")
    pulo = next(n for n in ast.walk(func)
                if isinstance(n, ast.If) and "_hotkeys_exclusivos" in ast.unparse(n.test))
    bind = next(n for n in ast.walk(func)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "bind")
    assert pulo.lineno < bind.lineno and isinstance(pulo.body[-1], ast.Return)


def test_gancho_de_smoke_de_hotkeys():
    fonte = ast.unparse(_func(_tree(), "_smoke_boot_finish"))
    assert "JARVIS_SMOKE_HOTKEYS" in fonte and "backend=" in fonte and "ptt=" in fonte
