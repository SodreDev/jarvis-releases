"""K F2-02 (AST, sem importar main.py): tray pelo backend de plataforma.

- _criar_tray_icon não importa pystray; gera a imagem em _make_img, monta os TrayItem
  na ordem legada (Restaurar padrão, Briefing, separador, Encerrar) e chama
  _plat_get(Cap.TRAY).setup("J.A.R.V.I.S.", _make_img, items);
- o X só é interceptado depois de `if not ok: return`;
- _minimizar_para_tray/_restaurar_da_tray usam set_visible; _encerrar_de_tray usa stop;
- portão do boot: sem a feature tray, aviso único (print) no else, sem criar nada.
"""
import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _tree():
    return ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))


def _func(nome):
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"{nome} não encontrada")


def test_criar_tray_icon_sem_pystray_e_com_setup():
    func = _func("_criar_tray_icon")
    fonte = ast.unparse(func)
    usos_pystray = [n for n in ast.walk(func)
                    if (isinstance(n, ast.Name) and n.id == "pystray")
                    or (isinstance(n, ast.Import) and any(a.name.startswith("pystray") for a in n.names))
                    or (isinstance(n, ast.ImportFrom) and (n.module or "").startswith("pystray"))]
    assert not usos_pystray, "pystray vive no backend windows, não no main.py"
    assert "tray = _plat_get(Cap.TRAY)" in fonte
    assert "ok = tray.setup('J.A.R.V.I.S.', _make_img, items)" in fonte
    assert "self._tray_icon = tray if ok else None" in fonte


def test_itens_do_menu_na_ordem_legada():
    func = _func("_criar_tray_icon")
    lista = next(n.value for n in ast.walk(func)
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "items" for t in n.targets))
    itens = [ast.unparse(e) for e in lista.elts]
    assert itens == [
        "TrayItem('Restaurar JARVIS', self._restaurar_da_tray, default=True)",
        "TrayItem('Briefing', lambda: self.root.after(0, self._fazer_briefing_tray))",
        "TrayItem('', None, separator=True)",
        "TrayItem('Encerrar', self._encerrar_de_tray)",
    ]


def test_x_so_interceptado_se_setup_ok():
    func = _func("_criar_tray_icon")
    retorno = next(n for n in ast.walk(func)
                   if isinstance(n, ast.If) and ast.unparse(n.test) == "not ok")
    closing = next(n for n in ast.walk(func)
                   if isinstance(n, ast.AugAssign) and "events.closing" in ast.unparse(n.target))
    assert isinstance(retorno.body[-1], ast.Return) and retorno.lineno < closing.lineno


def test_minimizar_restaurar_encerrar_pelo_backend():
    assert "self._tray_icon.set_visible(True)" in ast.unparse(_func("_minimizar_para_tray"))
    assert "self._tray_icon.set_visible(False)" in ast.unparse(_func("_restaurar_da_tray"))
    assert "self._tray_icon.stop()" in ast.unparse(_func("_encerrar_de_tray"))
    for nome in ("_minimizar_para_tray", "_restaurar_da_tray"):
        assert ".visible =" not in ast.unparse(_func(nome))


def test_portao_do_tray_tem_aviso_sem_criar():
    portao = next(n for n in ast.walk(_func("_on_webview_ready"))
                  if isinstance(n, ast.If) and ast.unparse(n.test) == "_has_feature('tray')")
    assert ast.unparse(portao.body) == "self._criar_tray_icon()"
    senao = ast.unparse(portao.orelse)
    assert senao.startswith("print(") and "_criar_tray_icon" not in senao
