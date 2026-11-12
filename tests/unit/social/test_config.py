"""`redes.toml` (ADR-0060): tudo desligado por padrão, 0600, recusa o que não cabe."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jarvis.social.arquivo import anexar_privado, escrever_privado, texto_toml
from jarvis.social.config import (
    AjusteDaRede,
    ConfiguracaoSocial,
    ConfiguracaoSocialInvalida,
    gravar,
    ler,
)
from jarvis.social.redes import IDS, rede, rede_da_url

POSIX = pytest.mark.skipif(os.name == "nt", reason="permissão 0600 é do POSIX")


def test_sem_arquivo_tudo_desligado(tmp_path: Path) -> None:
    configuracao = ler(tmp_path / "redes.toml")
    assert configuracao.navegador_preferido == ""
    assert configuracao.monitoradas() == ()
    assert all(configuracao.ajuste(r) == AjusteDaRede(monitorar=False) for r in IDS)


@POSIX
def test_gravar_volta_igual_e_nasce_0600_em_pasta_0700(tmp_path: Path) -> None:
    caminho = tmp_path / "nova" / "redes.toml"
    configuracao = (
        ConfiguracaoSocial()
        .com_rede("whatsapp", monitorar=True)
        .com_rede("discord", monitorar=True, notificar=False)
        .com_navegador("Brave")
    )
    gravar(configuracao, caminho)
    assert ler(caminho) == configuracao
    assert ler(caminho).navegador_preferido == "brave"
    assert ler(caminho).monitoradas() == ("whatsapp", "discord")
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600
    assert stat.S_IMODE(caminho.parent.stat().st_mode) == 0o700
    assert not list(caminho.parent.glob(".*.tmp")), "o temporário não fica para trás"


@POSIX
def test_regravar_aperta_um_arquivo_que_estava_aberto_a_todos(tmp_path: Path) -> None:
    caminho = tmp_path / "redes.toml"
    caminho.write_text('navegador_preferido = ""\n', "utf-8")
    caminho.chmod(0o644)
    gravar(ConfiguracaoSocial().com_rede("tiktok", monitorar=True), caminho)
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600


@POSIX
def test_log_privado_acrescenta_com_0600(tmp_path: Path) -> None:
    log = tmp_path / "envios.jsonl"
    anexar_privado(log, '{"a": 1}')
    anexar_privado(log, '{"a": 2}\n')
    assert log.read_text("utf-8") == '{"a": 1}\n{"a": 2}\n'
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("texto", "trecho"),
    [
        ("senha = 1\n", "chave desconhecida"),
        ("[redes.orkut]\nmonitorar = true\n", "rede desconhecida"),
        ("[redes.whatsapp]\nmonitorar = 'sim'\n", "true ou false"),
        ("[redes.whatsapp]\nenviar = true\n", "chave desconhecida"),
        ('navegador_preferido = "brave --no-sandbox"\n', "família"),
        ("redes = 3\n", "tabela"),
        ("isto não é toml", "TOML inválido"),
    ],
)
def test_arquivo_que_nao_cabe_e_recusado_inteiro(tmp_path: Path, texto: str, trecho: str) -> None:
    caminho = tmp_path / "redes.toml"
    caminho.write_text(texto, "utf-8")
    with pytest.raises(ConfiguracaoSocialInvalida, match=trecho):
        ler(caminho)


def test_ajuste_de_rede_inexistente_e_recusado() -> None:
    with pytest.raises(KeyError, match="rede desconhecida"):
        ConfiguracaoSocial().com_rede("orkut", monitorar=True)
    with pytest.raises(ConfiguracaoSocialInvalida, match="desconhecido"):
        ConfiguracaoSocial().com_rede("whatsapp", enviar=True)


def test_texto_toml_escapa_o_que_o_toml_proibe(tmp_path: Path) -> None:
    import tomllib

    valor = 'aspas " barra \\ linha\nDEL\x7f tab\t fim'
    assert tomllib.loads(f"x = {texto_toml(valor)}")["x"] == valor


def test_escrever_privado_nao_deixa_temporario_quando_falha(tmp_path: Path) -> None:
    pasta = tmp_path / "ocupada"
    (pasta / "redes.toml").mkdir(parents=True)  # o destino é uma pasta: o replace falha
    with pytest.raises(OSError):
        escrever_privado(pasta / "redes.toml", "x")
    assert [p.name for p in pasta.iterdir()] == ["redes.toml"]


def test_rede_pela_url_so_pelo_host_exato_e_https() -> None:
    assert rede_da_url("https://web.whatsapp.com/") == rede("whatsapp")
    assert rede_da_url("https://discord.com/channels/@me") == rede("discord")
    assert rede_da_url("http://web.whatsapp.com/") is None
    assert rede_da_url("https://web.whatsapp.com.golpe.example/") is None
    assert rede_da_url("https://exemplo.com/?u=web.whatsapp.com") is None
    assert [r for r in IDS if rede(r).responde] == ["whatsapp"]


def test_envio_desligado_por_padrao_e_volta_igual_do_arquivo(tmp_path: Path) -> None:
    from jarvis.social.envio import Permitido

    assert ConfiguracaoSocial().envio.automatico is False
    assert ConfiguracaoSocial().envio.ausente is False
    caminho = tmp_path / "redes.toml"
    configuracao = ConfiguracaoSocial().com_envio(
        automatico=True,
        por_hora=2,
        permitidos=(Permitido("Ana Souza", "+55 11 98888-7777"),),
    )
    gravar(configuracao, caminho)
    assert ler(caminho) == configuracao


@pytest.mark.parametrize(
    ("bloco", "trecho"),
    [
        ("[envio]\npor_hora = 50\n", "teto"),
        ("[envio]\npor_dia = 31\n", "teto"),
        ("[envio]\nautomatico = 1\n", "true ou false"),
        ("[envio]\nsilencio = [0, 30]\n", "silencio"),
        ("[envio]\nlimite = 3\n", "desconhecida"),
        ('[[envio.permitido]]\nnome = "Ana"\ntelefone = "ligue já"\n', "telefone"),
        ('[[envio.permitido]]\nnome = "Ana"\n', "nome e telefone"),
        (
            '[[envio.permitido]]\nnome = "Ana"\ntelefone = "11 98888-7777"\n'
            '[[envio.permitido]]\nnome = "ana"\ntelefone = "1198888-7777"\n',
            "repetido",
        ),
    ],
)
def test_envio_que_nao_cabe_e_recusado(tmp_path: Path, bloco: str, trecho: str) -> None:
    caminho = tmp_path / "redes.toml"
    caminho.write_text(bloco, "utf-8")
    with pytest.raises(ConfiguracaoSocialInvalida, match=trecho):
        ler(caminho)
