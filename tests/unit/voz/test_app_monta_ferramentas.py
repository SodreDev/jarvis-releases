"""O app monta o executor com a caixa de scripts (ADR-0050), o guarda de contexto (ADR-0049) e o
cliente MCP (ADR-0052) ligados. Sem `mcp.toml`, o MCP é vazio/desligado e não abre nada; com um
servidor ligado, as tools dele entram no catálogo do turno (ADR-0047) sem estourar o orçamento."""

from __future__ import annotations

import sys
from pathlib import Path

from jarvis.s2.motor_claude_cli import sistema_com_ferramentas
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

SERVIDOR_FALSO = Path(__file__).resolve().parents[1] / "mcp" / "servidor_falso.py"


def _app(tmp_path: Path, config_dir: Path) -> Aplicativo:
    casa = tmp_path / "casa"
    casa.mkdir(exist_ok=True)
    (tmp_path / "sessao").mkdir(exist_ok=True)  # a raiz da sessão guarda a auditoria.sqlite
    return Aplicativo(
        configuracao=Configuracao(
            asr="asr-whisper-local", tts="tts-parametrico", s2="eco", acesso="padrao"
        ),
        raiz=tmp_path / "sessao",
        lar=casa,
        escrever_na_tela=lambda _m: None,
        # XDG_CONFIG_HOME isola a configuração: o teste nunca lê o ~/.config real do dono.
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "XDG_CONFIG_HOME": str(config_dir)},
    )


def test_monta_com_caixa_guarda_e_mcp_vazio_sem_efeito(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()  # sem mcp.toml: MCP vazio/desligado
    app = _app(tmp_path, config)

    ferramentas = app._montar_ferramentas()

    assert ferramentas.caixa is not None, "a caixa de scripts entra montada"
    assert ferramentas.guarda is not None, "o guarda de contexto entra montado"
    assert ferramentas.mcp is not None, "o gestor MCP entra montado (mesmo vazio)"
    # Sem config, nenhum servidor foi aberto e nenhuma tool mcp.* existe: sem efeito colateral.
    assert ferramentas.mcp.manifestos == {}
    assert not any(t.startswith("mcp.") for t in ferramentas.manifestos)
    # O guarda sem classificador (o dono não ligou o endereçamento): a zona cinza pergunta a ele.
    assert ferramentas.guarda.classificador is None


def test_mcp_desligado_no_arquivo_nao_abre(tmp_path: Path) -> None:
    config = tmp_path / "config" / "jarvis"
    config.mkdir(parents=True)
    (config / "mcp.toml").write_text(
        f'[servidor.devtools]\ncomando = ["{sys.executable}", "-I", "{SERVIDOR_FALSO}"]\n'
        "ligado = false\n",  # o dono não ligou: nada abre
        encoding="utf-8",
    )
    app = _app(tmp_path, tmp_path / "config")

    ferramentas = app._montar_ferramentas()

    assert ferramentas.mcp is not None and ferramentas.mcp.manifestos == {}


def test_mcp_ligado_entra_no_catalogo_do_turno_sem_estourar_o_orcamento(tmp_path: Path) -> None:
    config = tmp_path / "config" / "jarvis"
    config.mkdir(parents=True)
    (config / "mcp.toml").write_text(
        f'[servidor.devtools]\ncomando = ["{sys.executable}", "-I", "{SERVIDOR_FALSO}"]\n'
        'ligado = true\ntier_padrao = "moderado"\n'
        '[servidor.devtools.tools]\nlist_console_messages = "leitura"\n',
        encoding="utf-8",
    )
    app = _app(tmp_path, tmp_path / "config")
    ferramentas = app._montar_ferramentas()
    gestor = ferramentas.mcp
    assert gestor is not None, "o gestor MCP entra montado"
    try:
        catalogo = ferramentas.catalogo_para_o_modelo()
        ids = {t["id"] for t in catalogo}
        assert "mcp.devtools.evaluate_script" in ids, "a tool do servidor entra no catálogo"
        assert "mcp.devtools.list_console_messages" in ids
        assert "mcp.devtools.shell_exec" not in ids, "a proibida nunca entra (ADR-0010)"

        prompt = sistema_com_ferramentas("Você é o Jarvis.", catalogo)
        linhas_mcp = [ln for ln in prompt.splitlines() if "mcp.devtools.evaluate_script" in ln]
        assert len(linhas_mcp) == 1, "a tool MCP é uma linha do catálogo"
        assert len(linhas_mcp[0]) < 300, "a linha é compacta (ADR-0047)"
        # ADR-0047: o catálogo do turno é compacto (~14,5 mil car. com tudo). Uma tool MCP a mais
        # não estoura o orçamento — o prompt inteiro fica bem abaixo do teto.
        assert len(prompt) < 20_000, f"o prompt cresceu demais: {len(prompt)} car."
    finally:
        gestor.fechar()
