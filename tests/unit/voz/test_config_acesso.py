"""A configuração de pastas, apps e navegadores: o que a janela grava e o laço lê (2026-10-17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler


def test_o_que_a_janela_grava_volta_igual(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    original = Configuracao(
        acesso="concedido",
        raizes=("/home/x/Projetos", "/home/x/Livros"),
        raizes_escrita=("/home/x/Projetos",),
        apps_autorizados=("org.kde.kate",),
        apps_extras=("/opt/meu/bin/meu-editor", "/home/x/.local/share/applications/avulso.desktop"),
        navegadores=("brave=/usr/bin/brave-browser-stable", "firefox=/usr/bin/firefox"),
        navegador_principal="brave",
    )
    escrever(original, arquivo)
    assert ler(arquivo) == original


def test_arquivo_de_antes_sem_os_campos_novos_continua_valendo(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text('acesso = "padrao"\nraizes = ["/home/x/Livros"]\n', "utf-8")
    lido = ler(arquivo)
    assert lido.raizes == ("/home/x/Livros",)
    assert lido.raizes_escrita == () and lido.navegadores == () and lido.navegador_principal == ""


@pytest.mark.parametrize(
    ("mudancas", "trecho"),
    [
        ({"raizes": ("/a",), "raizes_escrita": ("/b",)}, "não está em raizes"),
        ({"apps_extras": ("relativo/app",)}, "caminho inteiro"),
        ({"navegadores": ("firefox",)}, "família=caminho"),
        ({"navegadores": ("Fire Fox=/usr/bin/firefox",)}, "família=caminho"),
        ({"navegadores": ("firefox=firefox",)}, "família=caminho"),
        (
            {"navegadores": ("firefox=/usr/bin/firefox",), "navegador_principal": "brave"},
            "não está em navegadores",
        ),
    ],
)
def test_valor_sem_pe_nem_cabeca_e_recusado_dizendo_o_porque(
    tmp_path: Path, mudancas: dict[str, object], trecho: str
) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    escrever(Configuracao(**mudancas), arquivo)  # type: ignore[arg-type]
    with pytest.raises(ConfiguracaoInvalida, match=trecho):
        ler(arquivo)
