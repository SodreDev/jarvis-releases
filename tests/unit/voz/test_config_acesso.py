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


# --- motor das tarefas em segundo plano: escolha do dono (ADR-0022) -------------------------
def test_tarefa_motor_vai_e_volta_pelo_toml_e_valor_desconhecido_e_recusado(tmp_path: Path) -> None:
    from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler

    arquivo = tmp_path / "jarvis-voz.toml"
    assert Configuracao().tarefa_motor == "direto", "o padrão não manda a tarefa para modelo nenhum"

    escrever(Configuracao(tarefa_motor="agente"), arquivo)

    assert ler(arquivo).tarefa_motor == "agente"
    arquivo.write_text('tarefa_motor = "sub-gpt"\n', "utf-8")
    with pytest.raises(ConfiguracaoInvalida, match="tarefa_motor"):
        ler(arquivo)


# --- laço de ferramentas: teto de passos e prazo escolhidos pelo dono ------------------------
def test_teto_e_prazo_do_laco_vao_e_voltam_pelo_toml_e_valor_absurdo_e_recusado(
    tmp_path: Path,
) -> None:
    from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler

    arquivo = tmp_path / "jarvis-voz.toml"
    assert (Configuracao().laco_max_passos, Configuracao().laco_prazo_s) == (12, 90.0)

    escrever(Configuracao(laco_max_passos=5, laco_prazo_s=30.0), arquivo)

    lida = ler(arquivo)
    assert (lida.laco_max_passos, lida.laco_prazo_s) == (5, 30.0)
    for texto in ("laco_max_passos = 0\n", "laco_max_passos = 99\n", "laco_prazo_s = 1\n"):
        arquivo.write_text(texto, "utf-8")
        with pytest.raises(ConfiguracaoInvalida, match="laco_"):
            ler(arquivo)


# --- o prazo do foco de um app que abriu (ADR-0037) -----------------------------------------
def test_o_prazo_do_foco_vai_e_volta_pelo_toml_e_valor_absurdo_e_recusado(tmp_path: Path) -> None:
    from jarvis.executor.janelas import PRAZO_DO_FOCO_S
    from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler

    arquivo = tmp_path / "jarvis-voz.toml"
    assert Configuracao().prazo_do_foco_s == PRAZO_DO_FOCO_S, "o padrão é o do executor"

    escrever(Configuracao(prazo_do_foco_s=600.0), arquivo)

    assert ler(arquivo).prazo_do_foco_s == 600.0
    for texto in ("prazo_do_foco_s = 2\n", "prazo_do_foco_s = 99999\n"):
        arquivo.write_text(texto, "utf-8")
        with pytest.raises(ConfiguracaoInvalida, match="prazo_do_foco_s"):
            ler(arquivo)
