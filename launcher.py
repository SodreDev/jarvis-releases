"""JARVIS — launcher entry point do executável compilado (PyInstaller).

Macete anti-recompilação:
  O exe carrega as deps nativas do bundle (_internal/) mas executa os .py
  diretamente da pasta do projeto se ela existir dois níveis acima do exe.

  dist/JARVIS/JARVIS.exe → dois níveis acima → B:\\...\\J.A.R.V.I.S\\main.py

  Resultado: qualquer mudança em .py entra em vigor no próximo restart
  do JARVIS, sem precisar recompilar.

Só é necessário recompilar quando:
  - Novos pacotes pip são instalados  (novas DLLs/extensões nativas)
  - Assets mudam  (ui/, gesture_data/, config/)
  - launcher.py muda  (este arquivo)

Variável de ambiente opcional:
  JARVIS_SOURCE=C:\\caminho\\outro  — aponta para fonte em outra pasta
"""
import sys
import os
import runpy

# ── Força PyInstaller a analisar main.py estaticamente ───────────────────────
# O bloco abaixo nunca executa, mas o scanner estático do PyInstaller VÊ os
# imports e inclui main.py + pacote jarvis/ + todas as suas dependências.
#
# IMPORTANTE: Sempre que você adicionar um NOVO subpacote em jarvis/ que use
# uma dep nativa nova (ex.: novo backend que precisa de outra wheel), inclua
# o import aqui — caso contrário a wheel não vai pro bundle e o exe quebra
# em "modo standalone" (sem source ao vivo).
if False:                                # pragma: no cover  # noqa: SIM108
    import main                          # noqa: F401, E402
    # Pacote modular novo — força o scanner a empacotar pydantic/playwright/cryptography/openai
    import jarvis                        # noqa: F401, E402
    import jarvis.config                 # noqa: F401, E402
    import jarvis.config.loader          # noqa: F401, E402
    import jarvis.config.schema          # noqa: F401, E402
    import jarvis.credentials.vault      # noqa: F401, E402
    import jarvis.browser                # noqa: F401, E402
    import jarvis.browser.pool           # noqa: F401, E402
    import jarvis.browser.human          # noqa: F401, E402
    import jarvis.browser.launcher       # noqa: F401, E402
    import jarvis.messaging              # noqa: F401, E402
    import jarvis.messaging.router       # noqa: F401, E402
    import jarvis.messaging.stubs        # noqa: F401, E402
    import jarvis.intents                # noqa: F401, E402
    import jarvis.intents.spotify        # noqa: F401, E402
    import jarvis.llm                    # noqa: F401, E402
    import jarvis.llm.client             # noqa: F401, E402


# ── Detecção do source ao vivo ────────────────────────────────────────────────
def _find_source() -> "str | None":
    """Retorna o caminho do projeto se main.py estiver acessível, senão None."""
    if not getattr(sys, "frozen", False):
        return None                                # rodando como .py normal

    exe_dir = os.path.dirname(sys.executable)     # …/dist/JARVIS/

    # 1. Dois níveis acima do exe (layout padrão dist/JARVIS/)
    candidate = os.path.normpath(os.path.join(exe_dir, "..", ".."))
    if os.path.isfile(os.path.join(candidate, "main.py")):
        return candidate

    # 2. Variável de ambiente JARVIS_SOURCE
    env = os.environ.get("JARVIS_SOURCE", "").strip()
    if env and os.path.isfile(os.path.join(env, "main.py")):
        return env

    return None


_src = _find_source()

if _src:
    # ── Modo live-source ──────────────────────────────────────────────────────
    # Injeta o source no início do sys.path.
    # Python usará os .py do projeto; mediapipe/cv2/torch/etc. vêm do bundle.
    if _src not in sys.path:
        sys.path.insert(0, _src)
    runpy.run_path(os.path.join(_src, "main.py"), run_name="__main__")
else:
    # ── Modo standalone (sem source acessível) ────────────────────────────────
    # Executa o main.py embutido no bundle normalmente.
    runpy.run_module("main", run_name="__main__", alter_sys=True)
