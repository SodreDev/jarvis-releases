"""O estado verdadeiro da ponte (`browser.estado`): desligado, sem conexão ou conectado.

Tudo em pastas temporárias: sockets de mentira, manifestos escritos aqui, nenhum navegador.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.navegador import estado as est
from jarvis.navegador import instalar as inst
from jarvis.navegador.cliente import TransporteUnix


@pytest.fixture
def pasta(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A pasta dos sockets do host (caminho curto: socket Unix tem teto de ~100 caracteres)."""
    alvo = tmp_path_factory.mktemp("e") / "jarvis" / "navegador"
    alvo.mkdir(parents=True, mode=0o700)
    alvo.chmod(0o700)
    return alvo


@pytest.fixture
def escutando(pasta: Path) -> Iterator[list[socket.socket]]:
    abertos: list[socket.socket] = []
    yield abertos
    for s in abertos:
        s.close()


def _host_vivo(pasta: Path, nome: str, abertos: list[socket.socket]) -> None:
    servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    servidor.bind(str(pasta / nome))
    servidor.listen(4)
    abertos.append(servidor)


def _host_morto(pasta: Path, nome: str) -> None:
    """O arquivo que um host derrubado deixa: existe, é socket, e recusa conexão."""
    sobra = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sobra.bind(str(pasta / nome))
    sobra.close()


def _manifesto(casa: Path, navegador: str, executavel: str) -> Path:
    destino = next(d for d in inst.destinos_do_usuario(casa) if d.navegador == navegador)
    inst.instalar([destino], executavel)
    return destino.arquivo


def _executavel(tmp_path: Path) -> str:
    programa = tmp_path / "bin" / "host"
    programa.parent.mkdir(parents=True, exist_ok=True)
    programa.write_text("#!/bin/sh\n", "utf-8")
    programa.chmod(0o755)
    return str(programa)


def _sondar(pasta: Path, casa: Path, **campos: object) -> est.EstadoDaPonte:
    return est.sondar(
        transporte=TransporteUnix(pasta),
        home=casa,
        raiz_do_sistema=casa / "sistema",
        **campos,  # type: ignore[arg-type]
    )


def test_so_conta_host_que_aceita_conexao(pasta: Path, escutando: list[socket.socket]) -> None:
    _host_vivo(pasta, "chromium-10.sock", escutando)
    _host_morto(pasta, "firefox-11.sock")
    assert TransporteUnix(pasta).vivos() == ("chromium",)
    assert TransporteUnix(pasta / "nao-existe").vivos() == ()


def test_desligado_sem_manifesto_do_brave_diz_ligar_e_instalar(pasta: Path, tmp_path: Path) -> None:
    """O caso do dono em 2026-10-19: controle desligado e o Brave sem o manifesto do host."""
    casa = tmp_path / "casa"
    _manifesto(casa, "chrome", _executavel(tmp_path))  # só o do Chrome, como antes

    estado = _sondar(pasta, casa, ligado=False, principal="brave")

    assert estado.situacao == "desligado"
    passos = estado.o_que_fazer()
    assert passos[0] == est.COMO_LIGAR
    assert any("falta o manifesto do host nativo para o brave" in p for p in passos)
    modelo = estado.para_o_modelo()
    assert modelo["controle_ligado"] is False and modelo["extensao_conectada"] is False
    assert "desligado" in modelo["frase"]


def test_ligado_com_host_instalado_e_navegador_fechado_e_sem_conexao(
    pasta: Path, tmp_path: Path
) -> None:
    casa = tmp_path / "casa"
    _manifesto(casa, "brave", _executavel(tmp_path))

    estado = _sondar(pasta, casa, ligado=True, principal="brave")

    assert estado.situacao == "sem_conexao"
    assert not any("manifesto" in p for p in estado.o_que_fazer())
    assert "abrir o brave com a extensão" in estado.o_que_fazer()[-1]


def test_conectado_no_principal_nao_tem_o_que_fazer(
    pasta: Path, tmp_path: Path, escutando: list[socket.socket]
) -> None:
    _host_vivo(pasta, "chromium-20.sock", escutando)
    estado = _sondar(pasta, tmp_path / "casa", ligado=True, principal="brave")
    assert estado.situacao == "conectado"
    assert estado.o_que_fazer() == ()
    assert estado.para_o_modelo()["navegadores_conectados"] == ["chromium"]


def test_desligado_com_extensao_conectada_conta_as_duas_coisas(
    pasta: Path, tmp_path: Path, escutando: list[socket.socket]
) -> None:
    _host_vivo(pasta, "chromium-21.sock", escutando)
    estado = _sondar(pasta, tmp_path / "casa", ligado=False, principal="brave")
    assert estado.situacao == "desligado"
    assert "está conectada no brave" in estado.frase()
    assert estado.o_que_fazer() == (est.COMO_LIGAR,)


def test_extensao_conectada_em_outro_navegador_nao_e_a_do_principal(
    pasta: Path, tmp_path: Path, escutando: list[socket.socket]
) -> None:
    casa = tmp_path / "casa"
    _manifesto(casa, "brave", _executavel(tmp_path))
    _host_vivo(pasta, "firefox-22.sock", escutando)

    estado = _sondar(pasta, casa, ligado=True, principal="brave")

    assert estado.situacao == "sem_conexao"
    assert any("conectada no firefox" in p for p in estado.o_que_fazer())


def test_stub_que_chama_appimage_apagado_e_host_quebrado(pasta: Path, tmp_path: Path) -> None:
    casa = tmp_path / "casa"
    stub = inst.escrever_stub_do_appimage(casa, str(tmp_path / "sumiu" / "Jarvis.AppImage"))
    _manifesto(casa, "brave", str(stub))

    estado = _sondar(pasta, casa, ligado=True, principal="brave")

    manifesto = estado.manifesto_do_principal()
    assert manifesto is not None and not manifesto.pronto
    assert any("não existe ou não executa" in p for p in estado.o_que_fazer())
    assert est.alvo_do_stub(stub) == str(tmp_path / "sumiu" / "Jarvis.AppImage")


def test_manifesto_de_outro_host_ou_torto_nao_conta(pasta: Path, tmp_path: Path) -> None:
    casa = tmp_path / "casa"
    arquivo = _manifesto(casa, "firefox", _executavel(tmp_path))
    dados = json.loads(arquivo.read_text("utf-8"))
    arquivo.write_text(json.dumps({**dados, "name": "outro.host"}), "utf-8")
    torto = _manifesto(casa, "chromium", _executavel(tmp_path))
    torto.write_text("{", "utf-8")

    prontos = [m for m in est.manifestos(casa, casa / "sistema") if m.pronto]
    assert prontos == []


def test_principal_em_flatpak_avisa_que_a_ponte_nao_sai_da_caixa_de_areia(
    pasta: Path, tmp_path: Path
) -> None:
    estado = _sondar(
        pasta,
        tmp_path / "casa",
        ligado=True,
        principal="firefox",
        navegadores={
            "firefox": "/var/lib/flatpak/exports/share/applications/org.mozilla.firefox.desktop"
        },
    )
    assert estado.em_flatpak
    assert any("Flatpak" in p for p in estado.o_que_fazer())


def test_as_linhas_do_diagnostico_dizem_situacao_e_passos(pasta: Path, tmp_path: Path) -> None:
    linhas = "\n".join(_sondar(pasta, tmp_path / "casa", ligado=False, principal="brave").linhas())
    assert "situação: desligado" in linhas
    assert "host nativo instalado para: nenhum navegador" in linhas
    assert "o que fazer:" in linhas
