"""Criar pasta, copiar e mover dentro das raízes (item 4, grupo 4): moderadas, sem sobrescrever.

Sistema de arquivos de verdade em `tmp_path`, executor e PDP de verdade. O que se confere: efeito,
aviso falado, nunca sobrescreve, nunca sai das raízes (nem para a lista de negação), raiz só de
leitura não escreve, e o desfazer manda para a lixeira (nada é apagado).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.canonicalizacao import Sistema, canonicalizar
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo, Raiz
from jarvis.politica.pdp import Pdp

NUNCA = lambda: False  # noqa: E731


@pytest.fixture
def casa(tmp_path: Path) -> Path:
    lar = tmp_path / "casa"
    (lar / "Documentos" / "projetos").mkdir(parents=True)
    (lar / "Documentos" / "a.txt").write_text("conteúdo de a\n", "utf-8")
    (lar / "Documentos" / ".env").write_text("TOKEN=segredo\n", "utf-8")
    (lar / "Outro").mkdir()
    (lar / "Outro" / "fora.txt").write_text("fora das raízes\n", "utf-8")
    (lar / ".ssh").mkdir()
    (lar / ".ssh" / "id_rsa").write_text("CHAVE", "utf-8")
    return lar


def _executor(
    lar: Path, tmp_path: Path, auditoria: LogDeAuditoria, **pdp: Any
) -> ExecutorDeFerramentas:
    modo = pdp.pop("modo", Modo.PADRAO)
    pdp_ = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        modo=modo,
        pasta_do_jarvis=tmp_path / "area",
        **pdp,
    )
    executor = ExecutorDeFerramentas(pdp=pdp_, lar=lar)
    executor.preparar()
    return executor


@pytest.fixture
def executor(casa: Path, tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        yield _executor(casa, tmp_path, auditoria)


def _rodar(ex: ExecutorDeFerramentas, tool: str, args: dict[str, Any], **kw: Any) -> Any:
    return ex.executar(tool, args, cancelado=NUNCA, **kw)


# --- criar pasta ------------------------------------------------------------
def test_criar_pasta_avisa_nao_pergunta_e_o_desfazer_manda_para_a_lixeira(
    executor: ExecutorDeFerramentas, casa: Path
) -> None:
    perguntas: list[Confirmacao] = []

    def nao(p: Confirmacao) -> bool:
        perguntas.append(p)
        return False

    r = _rodar(executor, "files.create_dir", {"path": "~/Documentos/viagem"}, confirmar=nao)

    assert r.status == "ok" and perguntas == []
    assert r.aviso == "Criei a pasta viagem." and (casa / "Documentos" / "viagem").is_dir()

    d = _rodar(executor, "acao.desfazer", {})

    assert d.status == "ok" and d.aviso == "Desfiz a pasta viagem."
    assert not (casa / "Documentos" / "viagem").exists()
    guardado = list((casa / "Documentos" / ".lixeira-do-jarvis").iterdir())
    assert len(guardado) == 1 and guardado[0].name.endswith("-viagem"), "recolhida, não apagada"


@pytest.mark.parametrize(
    ("caminho", "trecho"),
    [
        ("~/Documentos/projetos", "já existe"),
        ("~/Documentos/nao-existe/filha", "não existe"),
        ("~/Documentos/.escondida", "nome"),
        ("~/Outro/nova", "fora das raízes"),
        ("~/.ssh/nova", "lista de negação"),
        ("Documentos/nova", "caminho relativo"),
    ],
)
def test_criar_pasta_recusa_o_que_nao_pode(
    executor: ExecutorDeFerramentas, caminho: str, trecho: str
) -> None:
    r = _rodar(executor, "files.create_dir", {"path": caminho})

    assert r.status in ("erro", "negado") and trecho in r.motivo, r.motivo


# --- copiar ------------------------------------------------------------
def test_copiar_cria_arquivo_novo_nunca_sobrescreve_e_a_origem_fica(
    executor: ExecutorDeFerramentas, casa: Path
) -> None:
    args = {"origem": "~/Documentos/a.txt", "destino": "~/Documentos/projetos/b.txt"}

    um = _rodar(executor, "files.copy", args)
    dois = _rodar(executor, "files.copy", args)

    assert um.aviso == "Copiei para b.txt." and dois.aviso == "Copiei para b-2.txt."
    assert (casa / "Documentos" / "projetos" / "b.txt").read_text("utf-8") == "conteúdo de a\n"
    assert (casa / "Documentos" / "projetos" / "b-2.txt").exists()
    assert (casa / "Documentos" / "a.txt").read_text("utf-8") == "conteúdo de a\n"


def test_copiar_de_uma_raiz_para_outra_e_desfazer_recolhe_a_copia(
    executor: ExecutorDeFerramentas, casa: Path, tmp_path: Path
) -> None:
    r = _rodar(
        executor,
        "files.copy",
        {"origem": "~/Documentos/a.txt", "destino": str(tmp_path / "area" / "rascunhos" / "a.txt")},
    )
    assert r.status == "ok", r.motivo
    copia = tmp_path / "area" / "rascunhos" / "a.txt"
    assert copia.read_text("utf-8") == "conteúdo de a\n"

    d = _rodar(executor, "acao.desfazer", {})

    assert d.status == "ok" and not copia.exists()
    assert list((tmp_path / "area" / "lixeira").glob("*a.txt")), "a lixeira do Jarvis"


@pytest.mark.parametrize(
    ("origem", "destino", "trecho"),
    [
        ("~/Documentos/.env", "~/Documentos/env-copia", "negada"),
        ("~/.ssh/id_rsa", "~/Documentos/chave", "negada"),
        ("~/Outro/fora.txt", "~/Documentos/x.txt", "negada"),
        ("~/Documentos/projetos", "~/Documentos/p2", "só copio arquivo comum"),
        ("~/Documentos/a.txt", "~/Outro/a.txt", "fora das raízes"),
        ("~/Documentos/a.txt", "~/Documentos/nao-existe/a.txt", "não existe"),
        ("~/Documentos/nada.txt", "~/Documentos/x.txt", "negada|não existe|erro"),
    ],
)
def test_copiar_recusa_origem_negada_destino_fora_e_o_que_nao_e_arquivo(
    executor: ExecutorDeFerramentas, casa: Path, origem: str, destino: str, trecho: str
) -> None:
    r = _rodar(executor, "files.copy", {"origem": origem, "destino": destino})

    assert r.status in ("erro", "negado")
    assert any(t in r.motivo for t in trecho.split("|")), r.motivo
    assert not (casa / "Documentos" / "env-copia").exists()
    assert not (casa / "Documentos" / "chave").exists()


def test_copiar_arquivo_grande_demais_e_recusado(
    executor: ExecutorDeFerramentas, casa: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.executor.organizar.LIMITE_DA_COPIA", 4)

    r = _rodar(
        executor, "files.copy", {"origem": "~/Documentos/a.txt", "destino": "~/Documentos/g.txt"}
    )

    assert r.status == "erro" and "grande demais" in r.motivo


# --- mover ------------------------------------------------------------
def test_mover_na_mesma_raiz_renomeia_sem_sobrescrever_e_o_desfazer_volta(
    executor: ExecutorDeFerramentas, casa: Path
) -> None:
    (casa / "Documentos" / "projetos" / "a.txt").write_text("já tinha um a", "utf-8")

    r = _rodar(
        executor,
        "files.move",
        {"origem": "~/Documentos/a.txt", "destino": "~/Documentos/projetos/a.txt"},
    )

    assert r.status == "ok" and r.aviso == "Movi para a-2.txt."
    assert (casa / "Documentos" / "projetos" / "a.txt").read_text("utf-8") == "já tinha um a"
    assert (casa / "Documentos" / "projetos" / "a-2.txt").read_text("utf-8") == "conteúdo de a\n"
    assert not (casa / "Documentos" / "a.txt").exists()

    d = _rodar(executor, "acao.desfazer", {})

    assert d.status == "ok"
    assert (casa / "Documentos" / "a.txt").read_text("utf-8") == "conteúdo de a\n"
    assert not (casa / "Documentos" / "projetos" / "a-2.txt").exists()


def test_desfazer_o_mover_nao_passa_por_cima_do_que_ocupou_o_lugar(
    executor: ExecutorDeFerramentas, casa: Path
) -> None:
    _rodar(
        executor, "files.move", {"origem": "~/Documentos/a.txt", "destino": "~/Documentos/z.txt"}
    )
    (casa / "Documentos" / "a.txt").write_text("outra coisa", "utf-8")

    d = _rodar(executor, "acao.desfazer", {})

    assert d.status == "erro" and "já foi ocupado" in d.motivo
    assert (casa / "Documentos" / "a.txt").read_text("utf-8") == "outra coisa"


@pytest.mark.parametrize(
    ("origem", "destino", "trecho"),
    [
        ("~/Documentos/a.txt", "~/Outro/a.txt", "fora das raízes"),
        ("~/Outro/fora.txt", "~/Documentos/x.txt", "negada"),
        ("~/Documentos/.env", "~/Documentos/env2", "negada"),
        ("~/Documentos/projetos", "~/Documentos/projetos/dentro", "dentro dela mesma"),
        ("~/Documentos/nada.txt", "~/Documentos/x.txt", "não existe"),
    ],
)
def test_mover_recusa_fora_da_raiz_negado_e_pasta_para_dentro_dela_mesma(
    executor: ExecutorDeFerramentas, casa: Path, origem: str, destino: str, trecho: str
) -> None:
    r = _rodar(executor, "files.move", {"origem": origem, "destino": destino})

    assert r.status in ("erro", "negado") and trecho in r.motivo, r.motivo
    assert (casa / "Documentos" / ".env").exists() and (casa / "Outro" / "fora.txt").exists()


def test_mover_de_uma_raiz_para_outra_e_recusado_e_manda_copiar(
    executor: ExecutorDeFerramentas, tmp_path: Path
) -> None:
    r = _rodar(
        executor,
        "files.move",
        {"origem": "~/Documentos/a.txt", "destino": str(tmp_path / "area" / "rascunhos" / "a.txt")},
    )

    assert r.status == "erro" and "mesma raiz" in r.motivo and "copie" in r.motivo


# --- raiz só de leitura ------------------------------------------------------------
def test_raiz_concedida_so_de_leitura_nao_recebe_pasta_nem_movimento(
    casa: Path, tmp_path: Path
) -> None:
    leitura = Raiz(
        nome="concedida",
        caminho=canonicalizar(str(casa / "Outro"), Sistema.POSIX),
        pode_ler=True,
        pode_escrever=False,
    )
    with LogDeAuditoria(tmp_path / "au2.sqlite") as auditoria:
        ex = _executor(casa, tmp_path, auditoria, modo=Modo.CONCEDIDO, concedidas=(leitura,))

        nova = _rodar(ex, "files.create_dir", {"path": "~/Outro/nova"})
        mover = _rodar(
            ex, "files.move", {"origem": "~/Outro/fora.txt", "destino": "~/Outro/dois.txt"}
        )
        copiar = _rodar(
            ex, "files.copy", {"origem": "~/Outro/fora.txt", "destino": "~/Documentos/c.txt"}
        )

    assert nova.status == "negado" and "só de leitura" in nova.motivo
    assert mover.status == "negado"
    assert copiar.status == "ok", "ler da raiz de leitura e escrever em outra é o que ela permite"
    assert (casa / "Outro" / "fora.txt").exists() and not (casa / "Outro" / "nova").exists()


def test_origem_e_destino_ficam_na_auditoria(executor: ExecutorDeFerramentas) -> None:
    _rodar(
        executor, "files.copy", {"origem": "~/Documentos/a.txt", "destino": "~/Documentos/c.txt"}
    )

    linhas = list(
        executor.pdp.auditoria._con.execute("SELECT tool_id, veredito FROM audit_log ORDER BY seq")
    )

    assert [(r["tool_id"], r["veredito"]) for r in linhas] == [
        ("files.copy", "allow"),
        ("files.read_text", "allow"),
    ], "o destino (escrita) e a origem (leitura) foram julgados"
