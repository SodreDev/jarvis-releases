"""Aceite F0-07: o manifesto é verificado por máquina (SPEC §4, ADR-0010)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from jarvis.manifesto import ManifestoInvalido, carregar_manifesto, gerar_stub, lintar_catalogo
from jarvis.manifesto.codegen import gerar_stub as gerar
from jarvis.manifesto.lint import lintar_manifesto
from jarvis.manifesto.validador import carregar_catalogo, validar_manifesto

RAIZ = Path(__file__).resolve().parents[3]
CATALOGO = RAIZ / "catalogo"
CLI = RAIZ / "tools" / "manifesto.py"

CAMPOS_QUE_O_CARTAO_COBRA = ("postcondition", "risk_class", "tests", "access_level_min")


def exemplo_da_spec() -> dict[str, Any]:
    """O `files.move_to_trash` da §4 — o manifesto que o cartão manda validar e gerar."""
    return dict(carregar_manifesto(CATALOGO / "files.move_to_trash.yaml"))


def rodar_cli(*argumentos: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *argumentos],
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )


# --- (a) manifesto incompleto é recusado ------------------------------------------
@pytest.mark.parametrize("campo", CAMPOS_QUE_O_CARTAO_COBRA)
def test_manifesto_sem_campo_obrigatorio_e_recusado(campo: str, tmp_path: Path) -> None:
    """Aceite (a): e é o CLI que o CI roda que recusa, não só a biblioteca."""
    manifesto = exemplo_da_spec()
    del manifesto[campo]

    with pytest.raises(ManifestoInvalido, match=campo):
        validar_manifesto(manifesto, origem="teste")

    (tmp_path / "files.move_to_trash.yaml").write_text(
        yaml.safe_dump(manifesto, allow_unicode=True), encoding="utf-8"
    )
    concluido = rodar_cli("validar", "--catalogo", str(tmp_path))

    assert concluido.returncode == 1, concluido.stdout
    assert "RECUSADO" in concluido.stdout


def test_catalogo_do_repositorio_passa_na_validacao() -> None:
    concluido = rodar_cli("validar")

    assert concluido.returncode == 0, concluido.stdout + concluido.stderr
    assert "3/3" in concluido.stdout or "manifestos válidos" in concluido.stdout


@pytest.mark.parametrize(
    ("campo", "valor", "erro"),
    [
        ("trust_input", "system", "trust_input"),
        ("platforms", ["linux-x11"], "Linux e Windows"),
        ("tests", ["contract"], "testes obrigatórios"),
        ("timeout_ms", 10, "timeout_ms"),
        ("id", "files.move_to_trash.extra.demais.niveis.aqui", None),
    ],
)
def test_campo_fora_do_contrato_e_recusado(campo: str, valor: Any, erro: str | None) -> None:
    manifesto = exemplo_da_spec()
    manifesto[campo] = valor

    with pytest.raises(ManifestoInvalido) as capturado:
        validar_manifesto(manifesto, origem="teste")
    if erro:
        assert erro in str(capturado.value)


def test_coerencia_entre_campos_e_cobrada() -> None:
    """§4: efeito exige idempotência e confirmação; leitura não tem efeito."""
    com_efeito_sem_chave = exemplo_da_spec() | {"idempotency": "not_required"}
    with pytest.raises(ManifestoInvalido, match="idempotency_key"):
        validar_manifesto(com_efeito_sem_chave, origem="teste")

    com_efeito_sem_confirmacao = exemplo_da_spec() | {"confirmation": "never"}
    with pytest.raises(ManifestoInvalido, match="confirmation: never"):
        validar_manifesto(com_efeito_sem_confirmacao, origem="teste")

    leitura_com_efeito = exemplo_da_spec() | {"risk_class": "leitura"}
    with pytest.raises(ManifestoInvalido, match="'leitura' mas tem efeito"):
        validar_manifesto(leitura_com_efeito, origem="teste")

    elevacao_sem_confirmacao = exemplo_da_spec() | {
        "requires_elevation": True,
        "confirmation": "once_per_batch",
    }
    with pytest.raises(ManifestoInvalido, match="per_action"):
        validar_manifesto(elevacao_sem_confirmacao, origem="teste")


def test_egress_de_rede_sem_classe_de_egress_e_recusado() -> None:
    manifesto = exemplo_da_spec() | {"data_egress": "network:api.exemplo.com"}

    with pytest.raises(ManifestoInvalido, match="egress"):
        validar_manifesto(manifesto, origem="teste")


# --- (b) lint recusa canivete suíço -----------------------------------------------
@pytest.mark.parametrize(
    "identificador",
    ["system.run_command", "tools.do_anything", "files.exec", "shell.open", "files.rm_rf"],
)
def test_lint_recusa_id_de_canivete_suico(identificador: str) -> None:
    """Aceite (b)."""
    manifesto = exemplo_da_spec() | {"id": identificador}

    achados = lintar_manifesto(manifesto, "teste.yaml")

    assert any(a.regra == "canivete-suico" for a in achados), achados


def test_lint_recusa_descricao_que_promete_shell() -> None:
    manifesto = exemplo_da_spec() | {
        "description": "Roda qualquer comando que o usuário pedir na linha de comando do "
        "sistema, com shell, para resolver o que for preciso no computador do dono."
    }

    achados = lintar_manifesto(manifesto, "teste.yaml")

    assert any(a.regra == "canivete-suico" for a in achados), achados


def test_lint_recusa_descricao_que_nao_passa_no_teste_do_estagiario() -> None:
    manifesto = exemplo_da_spec() | {"description": "Move arquivo para a lixeira do sistema."}

    achados = lintar_manifesto(manifesto, "teste.yaml")

    assert any(a.regra == "teste-do-estagiario" for a in achados), achados


def test_catalogo_do_repositorio_passa_no_lint() -> None:
    assert lintar_catalogo(CATALOGO) == []


def test_lint_recusa_capacidade_que_mexe_em_nivel_de_acesso(tmp_path: Path) -> None:
    """P12 no lint, além do teste do PDP (F0-06)."""
    manifesto = exemplo_da_spec() | {
        "id": "config.set_access_level",
        "capability": "config.write.access_level",
        "title": "Mudar o nível de acesso",
    }
    (tmp_path / "config.set_access_level.yaml").write_text(
        yaml.safe_dump(manifesto, allow_unicode=True), encoding="utf-8"
    )

    achados = lintar_catalogo(tmp_path)

    assert any(a.regra == "controle-de-acesso" for a in achados), achados


# --- (d) promoção de MCP ----------------------------------------------------------
def promovida(**mudancas: Any) -> dict[str, Any]:
    base = exemplo_da_spec() | {
        "id": "calendar.read_events",
        "capability": "calendar.read.events",
        "risk_class": "leitura",
        "side_effect": "none",
        "idempotency": "not_required",
        "confirmation": "never",
        "tier": "livre",
        "roots": [],
        "access_level_min": "jarvis",
        "mcp_origin": {
            "server_id": "calendario",
            "remote_tool": "list_events",
            "server_hash": "a" * 64,
            "tool_list_hash": "b" * 64,
            "promovido_por": "arquiteto",
        },
    }
    base.pop("undo", None)
    return base | mudancas


def test_promocao_de_mcp_valida_passa() -> None:
    manifesto = validar_manifesto(promovida(), origem="teste")

    assert lintar_manifesto(manifesto, "teste.yaml") == []


def test_promocao_sem_politica_nossa_e_recusada() -> None:
    """Aceite (d): `mcp_origin` sem os campos obrigatórios não valida (ADR-0010 item 5)."""
    manifesto = promovida()
    del manifesto["mcp_origin"]["server_hash"]

    with pytest.raises(ManifestoInvalido, match="server_hash"):
        validar_manifesto(manifesto, origem="teste")


def test_lint_recusa_promover_tool_proibida() -> None:
    """ADR-0010 item 8: a proibição de canivete suíço não se contorna por MCP."""
    for proibida in ("shell_exec", "ssh_exec", "cli_send"):
        manifesto = promovida()
        manifesto["mcp_origin"]["remote_tool"] = proibida

        achados = lintar_manifesto(manifesto, "teste.yaml")

        assert any(a.regra == "mcp-proibida" for a in achados), (proibida, achados)


def test_lint_recusa_politica_vinda_do_servidor() -> None:
    """A anotação do servidor é comentário, não política (ADR-0010 item 5)."""
    manifesto = promovida()
    manifesto["mcp_origin"]["anotacao_do_servidor"] = {
        "readOnlyHint": True,
        "risk_class": "leitura",
    }

    achados = lintar_manifesto(manifesto, "teste.yaml")

    assert any(a.regra == "mcp-politica-remota" for a in achados), achados


# --- (c) codegen ------------------------------------------------------------------
def test_stub_do_exemplo_da_spec_compila_e_carrega(tmp_path: Path) -> None:
    """Aceite (c): o manifesto da §4 gera stub que compila e roda a validação de entrada."""
    codigo = gerar_stub(exemplo_da_spec())
    arquivo = tmp_path / "files_move_to_trash.py"
    arquivo.write_text(codigo, encoding="utf-8")

    compilado = compile(codigo, str(arquivo), "exec")
    espaco: dict[str, Any] = {}
    exec(compilado, espaco)  # noqa: S102 - é exatamente o que o aceite pede provar

    assert espaco["ID"] == "files.move_to_trash"
    assert espaco["RISK_CLASS"] == "escrita_recuperavel"
    assert espaco["IDEMPOTENCY"] == "required"
    assert espaco["ROOTS"] == ("workspace_root",)

    entrada = espaco["validar_entrada"]({"path": "nota.txt"})
    assert entrada.path == "nota.txt"

    with pytest.raises(ValueError, match="fora do contrato"):
        espaco["validar_entrada"]({"path": "nota.txt", "forca": True})
    with pytest.raises(ValueError, match="obrigatório ausente"):
        espaco["validar_entrada"]({})
    with pytest.raises(NotImplementedError, match="executor"):
        espaco["executar"](entrada)


def test_stub_segue_o_manifesto_e_nao_a_memoria_de_quem_implementa() -> None:
    manifesto = exemplo_da_spec() | {"timeout_ms": 1234, "access_level_min": "total"}

    codigo = gerar(manifesto)

    assert "TIMEOUT_MS: Final = 1234" in codigo
    assert 'ACCESS_LEVEL_MIN: Final = "total"' in codigo


def test_stubs_do_repositorio_estao_em_dia() -> None:
    """Se alguém mudar o manifesto e não regenerar, o CI cai aqui."""
    concluido = rodar_cli("conferir")

    assert concluido.returncode == 0, concluido.stdout


def test_todo_manifesto_do_catalogo_tem_stub() -> None:
    catalogo = carregar_catalogo(CATALOGO)
    pasta = RAIZ / "src" / "jarvis" / "capacidades"

    for identificador in catalogo:
        assert (pasta / f"{identificador.replace('.', '_')}.py").exists(), identificador
