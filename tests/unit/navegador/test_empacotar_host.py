"""O empacotamento da extensão e do host nativo: só as funções puras, sem montar AppDir nem
rodar nfpm/appimagetool (isso é a prova da fatia 5, feita à mão num diretório temporário)."""

from __future__ import annotations

import json
from pathlib import Path

from tools import empacotar
from tools.empacotar import Lugares


def test_a_extensao_e_os_modelos_do_host_vao_em_todo_pacote() -> None:
    assert "extensao" in empacotar.DADOS
    raiz = empacotar.RAIZ / "extensao"
    for arquivo in (
        "manifest.json",
        "background.js",
        "content.js",
        "host/br.com.granafacil.jarvis.chrome.json",
    ):
        assert (raiz / arquivo).is_file(), arquivo


def test_o_lancador_do_host_isola_o_python_e_o_apprun_tem_o_modo_host() -> None:
    assert '-I -m jarvis.navegador.host "$@"' in empacotar.HOST_NATIVO
    assert "lib/jarvis/python/bin/python3" in empacotar.HOST_NATIVO
    assert "JARVIS_DADOS" in empacotar.HOST_NATIVO
    assert '"${1:-}" = "--native-host"' in empacotar.APPRUN
    assert "usr/bin/jarvis-native-host" in empacotar.APPRUN
    assert empacotar.APPRUN.rstrip().endswith('exec "$AQUI/usr/bin/jarvis" "$@"')  # o resto igual


def test_deb_leva_tres_manifestos_e_rpm_leva_quatro_todos_com_path_absoluto(tmp_path: Path) -> None:
    deb = empacotar.manifestos_do_host(Lugares(tmp_path / "deb"), "deb")
    rpm = empacotar.manifestos_do_host(Lugares(tmp_path / "rpm"), "rpm")
    assert sorted(d for _, d in deb) == [
        "/etc/chromium/native-messaging-hosts/br.com.granafacil.jarvis.json",
        "/etc/opt/chrome/native-messaging-hosts/br.com.granafacil.jarvis.json",
        "/usr/lib/mozilla/native-messaging-hosts/br.com.granafacil.jarvis.json",
    ]
    assert "/usr/lib64/mozilla/native-messaging-hosts/br.com.granafacil.jarvis.json" in [
        d for _, d in rpm
    ]
    assert len(rpm) == 4
    for arquivo, _ in deb + rpm:
        manifesto = json.loads(arquivo.read_text("utf-8"))
        assert manifesto["path"] == "/usr/bin/jarvis-native-host"
        assert manifesto["type"] == "stdio"


def test_a_receita_do_nfpm_inclui_host_extensao_e_manifestos(tmp_path: Path) -> None:
    lugares = Lugares(tmp_path)
    lugares.trabalho.mkdir(parents=True)
    texto = empacotar.receita(lugares, "rpm").read_text("utf-8")
    assert 'dst: "/usr/bin/jarvis-native-host"' in texto
    assert f'src: "{lugares.usr}/bin/jarvis-native-host"' in texto
    assert (
        'dst: "/usr/share/jarvis"' in texto
    )  # a extensão vai dentro (DADOS → share/jarvis/extensao)
    assert texto.count("native-messaging-hosts") >= 4 * 2  # src e dst de cada manifesto
    assert "/usr/lib64/mozilla" in texto

    deb = empacotar.receita(lugares, "deb").read_text("utf-8")
    assert "/usr/lib64/mozilla" not in deb and "/usr/lib/mozilla" in deb


def test_a_verificacao_em_conteiner_confere_o_host_sem_navegador() -> None:
    texto = empacotar.VERIFICAR_HOST
    assert "test -x /usr/bin/jarvis-native-host" in texto
    assert "/etc/chromium/native-messaging-hosts/br.com.granafacil.jarvis.json" in texto
    assert "test $? -eq 2" in texto  # origem errada → código 2
