"""Prova que a suíte unitária ignora a configuração real do dono (conftest da pasta)."""

from __future__ import annotations

import os
import pwd
from pathlib import Path


def test_home_e_xdg_apontam_para_o_tmp(ambiente_do_dono_isolado: Path, tmp_path: Path) -> None:
    assert Path(os.environ["HOME"]).is_relative_to(ambiente_do_dono_isolado)
    assert Path(os.environ["XDG_CONFIG_HOME"]).is_relative_to(ambiente_do_dono_isolado)
    assert Path.home() == ambiente_do_dono_isolado
    assert ambiente_do_dono_isolado != Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert not ambiente_do_dono_isolado.is_relative_to(tmp_path)


def test_um_presets_toml_no_tmp_nao_vaza_para_outro_teste(ambiente_do_dono_isolado: Path) -> None:
    pasta = ambiente_do_dono_isolado / "config" / "jarvis"
    pasta.mkdir(parents=True)
    (pasta / "presets.toml").write_text("# arquivo falso, só no tmp\n")
    assert (Path(os.environ["XDG_CONFIG_HOME"]) / "jarvis" / "presets.toml").exists()
