"""Instalar o manifesto do host nos caminhos de Firefox e Chromium — só em pastas temporárias."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from jarvis.navegador import instalar as inst
from jarvis.navegador.protocolo import ID_FIREFOX, ORIGEM_CHROMIUM


def test_o_modelo_do_release_e_o_que_o_instalador_espera() -> None:
    chrome = json.loads(inst.modelo_do_release("chrome"))
    firefox = json.loads(inst.modelo_do_release("firefox"))
    assert chrome["path"] == firefox["path"] == inst.MARCADOR
    assert chrome["allowed_origins"] == [ORIGEM_CHROMIUM]
    assert firefox["allowed_extensions"] == [ID_FIREFOX]


def test_so_o_marcador_vira_o_executavel_e_o_resto_fica_igual() -> None:
    modelo = inst.modelo_do_release("firefox")
    pronto = json.loads(inst.manifesto_pronto(modelo, "/usr/bin/jarvis-native-host"))
    original = json.loads(modelo)
    assert pronto.pop("path") == "/usr/bin/jarvis-native-host"
    original.pop("path")
    assert pronto == original


@pytest.mark.parametrize("ruim", ["jarvis-native-host", "./host", "~/host", ""])
def test_caminho_relativo_e_recusado(ruim: str) -> None:
    with pytest.raises(inst.InstalacaoRecusada, match="absoluto"):
        inst.manifesto_pronto(inst.modelo_do_release("chrome"), ruim)


def test_modelo_sem_marcador_ou_de_outro_host_e_recusado() -> None:
    with pytest.raises(inst.InstalacaoRecusada, match="marcador"):
        inst.manifesto_pronto(json.dumps({"name": "x", "path": "/bin/sh", "type": "stdio"}), "/a")
    with pytest.raises(inst.InstalacaoRecusada, match="stdio"):
        inst.manifesto_pronto(
            json.dumps({"name": "outro", "path": inst.MARCADOR, "type": "stdio"}), "/a"
        )
    with pytest.raises(inst.InstalacaoRecusada, match="JSON"):
        inst.manifesto_pronto("{", "/a")


def test_caminhos_de_usuario_e_de_sistema_sao_os_da_documentacao(tmp_path: Path) -> None:
    usuario = {
        d.navegador: d.pasta.relative_to(tmp_path) for d in inst.destinos_do_usuario(tmp_path)
    }
    assert usuario == {
        "firefox": Path(".mozilla/native-messaging-hosts"),
        "chrome": Path(".config/google-chrome/NativeMessagingHosts"),
        "chromium": Path(".config/chromium/NativeMessagingHosts"),
    }
    sistema = {
        d.navegador: d.pasta.relative_to(tmp_path) for d in inst.destinos_do_sistema(tmp_path)
    }
    assert sistema == {
        "chrome": Path("etc/opt/chrome/native-messaging-hosts"),
        "chromium": Path("etc/chromium/native-messaging-hosts"),
        "firefox": Path("usr/lib/mozilla/native-messaging-hosts"),
        "firefox64": Path("usr/lib64/mozilla/native-messaging-hosts"),
    }


def test_instalar_grava_o_modelo_certo_em_cada_navegador_e_remover_so_apaga_o_nosso(
    tmp_path: Path,
) -> None:
    destinos = inst.destinos_do_usuario(tmp_path)
    vizinho = tmp_path / ".mozilla/native-messaging-hosts/outro.host.json"
    vizinho.parent.mkdir(parents=True)
    vizinho.write_text("{}", encoding="utf-8")

    escritos = inst.instalar(destinos, "/usr/bin/jarvis-native-host")
    assert len(escritos) == 3
    por_nome = {d.navegador: json.loads(d.arquivo.read_text("utf-8")) for d in destinos}
    assert "allowed_extensions" in por_nome["firefox"]
    assert por_nome["chromium"]["allowed_origins"] == [ORIGEM_CHROMIUM]
    assert all(m["path"] == "/usr/bin/jarvis-native-host" for m in por_nome.values())
    assert stat.S_IMODE(destinos[0].arquivo.stat().st_mode) == 0o644

    assert len(inst.remover(destinos)) == 3
    assert inst.remover(destinos) == []  # idempotente
    assert vizinho.read_text("utf-8") == "{}"  # nada que não seja nosso é tocado


def test_stub_do_appimage_chama_o_modo_host_nativo_com_o_caminho_citado(tmp_path: Path) -> None:
    stub = inst.escrever_stub_do_appimage(tmp_path, "/home/x/Meus Apps/Jarvis.AppImage")
    texto = stub.read_text("utf-8")
    assert "exec '/home/x/Meus Apps/Jarvis.AppImage' --native-host \"$@\"" in texto
    assert stub.stat().st_mode & 0o111  # executável
    with pytest.raises(inst.InstalacaoRecusada):
        inst.escrever_stub_do_appimage(tmp_path, "Jarvis.AppImage")


def test_copiar_extensao_leva_so_o_que_o_navegador_carrega(tmp_path: Path) -> None:
    origem = tmp_path / "ext"
    (origem / "host").mkdir(parents=True)
    (origem / "manifest.json").write_text("{}", "utf-8")
    destino = inst.copiar_extensao(tmp_path / "casa", origem)
    assert (destino / "manifest.json").is_file()
    assert destino == tmp_path / "casa" / inst.EXTENSAO_NO_USUARIO


def test_cli_instalar_pelo_executavel_do_pacote_e_remover(tmp_path: Path) -> None:
    falas: list[str] = []
    codigo = inst.principal(
        ["--instalar"],
        {},
        tmp_path,
        onde_esta_o_executavel=lambda _n: "/usr/bin/jarvis-native-host",
        saida=falas.append,
    )
    assert codigo == 0
    assert (tmp_path / ".mozilla/native-messaging-hosts" / inst.ARQUIVO).is_file()
    assert any("extensão para carregar" in f for f in falas)
    assert inst.principal(["--remover"], {}, tmp_path, saida=falas.append) == 0
    assert not (tmp_path / ".mozilla/native-messaging-hosts" / inst.ARQUIVO).exists()


def test_cli_pelo_appimage_cria_o_stub_e_a_copia_da_extensao(tmp_path: Path) -> None:
    falas: list[str] = []
    codigo = inst.principal(
        ["--instalar"], {"APPIMAGE": "/opt/Jarvis.AppImage"}, tmp_path, saida=falas.append
    )
    assert codigo == 0
    stub = tmp_path / inst.STUB_NO_USUARIO
    manifesto = json.loads(
        (tmp_path / ".config/chromium/NativeMessagingHosts" / inst.ARQUIVO).read_text("utf-8")
    )
    assert manifesto["path"] == str(stub) and os.access(stub, os.X_OK)
    assert (tmp_path / inst.EXTENSAO_NO_USUARIO / "manifest.json").is_file()


def test_cli_sem_executavel_nem_appimage_explica_e_nao_grava(tmp_path: Path) -> None:
    falas: list[str] = []
    codigo = inst.principal(
        ["--instalar"], {}, tmp_path, onde_esta_o_executavel=lambda _n: None, saida=falas.append
    )
    assert codigo == 1 and "não está no PATH" in falas[0]
    assert not (tmp_path / ".mozilla").exists()


def test_cli_com_argumento_desconhecido_mostra_o_uso(tmp_path: Path) -> None:
    falas: list[str] = []
    assert inst.principal(["--tudo"], {}, tmp_path, saida=falas.append) == 2
    assert "uso:" in falas[0]
