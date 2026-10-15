"""Aceite F0-06 (g), (h) e (i), mais modos, lista de negação e auditoria (SPEC §5.5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.politica.auditoria import CadeiaDeAuditoriaRompida, LogDeAuditoria
from jarvis.politica.canonicalizacao import Sistema, canonicalizar
from jarvis.politica.catalogo import (
    PALAVRAS_DE_CONTROLE_DE_ACESSO,
    ManifestoInvalido,
    carregar,
    carregar_catalogo,
)
from jarvis.politica.modos import Modo, Raiz, motivo_de_negacao, raizes_do_modo
from jarvis.politica.pdp import Pdp, Pedido, Veredito

LAR = Path("/casa/sodre")


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


@pytest.fixture
def pdp(auditoria: LogDeAuditoria) -> Pdp:
    return Pdp(
        catalogo=carregar_catalogo(),
        lar=LAR,
        auditoria=auditoria,
        modo=Modo.PADRAO,
        session_id="01a14079-bebc-7e23-8521-d6ad00000000",
    )


# --- modos e raízes ---------------------------------------------------------------
def test_amplitude_cresce_de_jarvis_a_total() -> None:
    """A numeração do dono não é crescente; a amplitude é (§5.5)."""
    assert [m.amplitude for m in (Modo.JARVIS, Modo.PADRAO, Modo.CONCEDIDO, Modo.TOTAL)] == [
        0,
        1,
        2,
        3,
    ]
    assert "nível 2" in Modo.JARVIS.nome_do_dono
    assert "nível 1" in Modo.PADRAO.nome_do_dono


def test_cada_modo_materializa_as_raizes_da_spec() -> None:
    concedida = Raiz(
        nome="projetos",
        caminho=canonicalizar("/casa/sodre/código", Sistema.POSIX),
        pode_escrever=True,
    )
    nomes = {
        modo: {r.nome for r in raizes_do_modo(modo, lar=LAR, concedidas=(concedida,))}
        for modo in Modo
    }

    assert nomes[Modo.JARVIS] == {"jarvis_root"}
    assert "Documentos" in nomes[Modo.PADRAO] and "projetos" not in nomes[Modo.PADRAO]
    assert "projetos" in nomes[Modo.CONCEDIDO]
    assert {"arvore_do_dono", "sistema"} <= nomes[Modo.TOTAL]


def test_raiz_de_sistema_no_total_e_so_leitura() -> None:
    raizes = {r.nome: r for r in raizes_do_modo(Modo.TOTAL, lar=LAR)}

    assert raizes["sistema"].pode_ler
    assert not raizes["sistema"].pode_escrever


# --- lista de negação -------------------------------------------------------------
@pytest.mark.parametrize(
    "caminho",
    [
        "/casa/sodre/.ssh/id_rsa",
        "/casa/sodre/.gnupg/secring.gpg",
        "/casa/sodre/.mozilla/perfil/logins.json",
        "/casa/sodre/.config/google-chrome/Default/Login Data",
        "/casa/sodre/.password-store/banco.gpg",
        "/casa/sodre/.local/share/jarvis/cofre/chave",
        "/casa/sodre/projeto/.env",
        "/etc/shadow",
        "/etc/ssh/sshd_config",
    ],
)
def test_lista_de_negacao_pega_segredo_em_qualquer_modo(caminho: str) -> None:
    canonico = canonicalizar(caminho, Sistema.POSIX)

    assert motivo_de_negacao(canonico, LAR, Sistema.POSIX) is not None


def test_negacao_nao_e_burlada_por_grafia(pdp: Pdp) -> None:
    """`..` e unicode não abrem caminho para o que a negação fecha."""
    for tentativa in (
        "/casa/sodre/Documentos/../.ssh/id_rsa",
        "/casa/sodre/./.ssh/./id_rsa",
    ):
        decisao = pdp.decidir(Pedido(tool_id="files.move_to_trash", args={}, caminho=tentativa))
        assert decisao.veredito is Veredito.DENY
        assert "negação" in decisao.motivo


def test_negacao_vence_no_total_e_nao_e_confirmavel(pdp: Pdp) -> None:
    """P13: mais alcance não é menos rigor; segredo é `deny`, nunca `confirm`."""
    pdp.modo = Modo.TOTAL

    decisao = pdp.decidir(
        Pedido(tool_id="files.move_to_trash", args={}, caminho="/casa/sodre/.ssh/id_rsa")
    )

    assert decisao.veredito is Veredito.DENY
    assert decisao.grant is None


def test_caminho_fora_das_raizes_do_modo_e_negado(pdp: Pdp) -> None:
    pdp.modo = Modo.PADRAO

    decisao = pdp.decidir(
        Pedido(tool_id="files.move_to_trash", args={}, caminho="/casa/sodre/código/x.py")
    )

    assert decisao.veredito is Veredito.DENY
    assert "fora das raízes" in decisao.motivo


def test_mesmo_pedido_dentro_da_raiz_pede_confirmacao_em_qualquer_modo(pdp: Pdp) -> None:
    """P13 em forma de teste: o veredito do `total` é o mesmo do `padrao`."""
    pedido = Pedido(
        tool_id="files.move_to_trash",
        args={"path": "nota.txt"},
        caminho="/casa/sodre/Documentos/nota.txt",
    )

    no_padrao = pdp.decidir(pedido)
    pdp.modo = Modo.TOTAL
    no_total = pdp.decidir(pedido)

    assert no_padrao.veredito is Veredito.CONFIRM
    assert no_total.veredito is no_padrao.veredito


# --- (i) elevação -----------------------------------------------------------------
def test_capacidade_que_exige_elevacao_nao_aparece_com_o_interruptor_desligado(pdp: Pdp) -> None:
    """Aceite (i): filtrada **antes** de o modelo ver o catálogo, não negada depois."""
    pdp.modo = Modo.TOTAL
    pdp.elevacao_ligada = False

    assert "system.install_package" not in pdp.allowlist()

    decisao = pdp.decidir(Pedido(tool_id="system.install_package", args={"package_id": "htop"}))
    assert decisao.veredito is Veredito.DENY
    assert "elevação" in decisao.motivo

    pdp.ligar_elevacao(dono_presente=True)
    assert "system.install_package" in pdp.allowlist()


def test_elevacao_so_liga_com_o_dono_presente(pdp: Pdp) -> None:
    with pytest.raises(PermissionError, match="dono presente"):
        pdp.ligar_elevacao(dono_presente=False)
    assert not pdp.elevacao_ligada


def test_total_nao_implica_elevacao(pdp: Pdp) -> None:
    pdp.modo = Modo.TOTAL

    assert not pdp.elevacao_ligada
    assert "system.install_package" not in pdp.allowlist()


def test_capacidade_de_modo_mais_amplo_nao_aparece_no_modo_estreito(pdp: Pdp) -> None:
    pdp.modo = Modo.JARVIS

    assert pdp.allowlist() == ("system.read.status",)


# --- (h) nenhuma capacidade mexe no controle de acesso ----------------------------
def test_nenhuma_capacidade_do_catalogo_muda_nivel_ou_elevacao() -> None:
    """Aceite (h): varredura do catálogo (P12)."""
    catalogo = carregar_catalogo()

    assert catalogo, "catálogo vazio: a varredura não provaria nada"
    culpadas = [c.id for c in catalogo.values() if c.muda_controle_de_acesso]
    assert culpadas == []


def test_a_varredura_pega_uma_capacidade_plantada_que_mexe_no_nivel(tmp_path: Path) -> None:
    """Se a varredura não acusar isto, ela não serve para o aceite (h)."""
    manifesto = tmp_path / "config.set_access_level.yaml"
    manifesto.write_text(
        "id: config.set_access_level\n"
        "title: Mudar o nivel_de_acesso do Jarvis\n"
        "description: Troca o access_level do assistente por voz.\n"
        "capability: config.write.access_level\n"
        "risk_class: mudanca_de_sistema\n"
        "confirmation: per_action\n"
        "access_level_min: jarvis\n"
        "requires_elevation: false\n"
        "side_effect: persistent\n"
        "roots: []\n",
        encoding="utf-8",
    )

    capacidade = carregar(manifesto)

    assert capacidade.muda_controle_de_acesso
    assert any(p in capacidade.id.casefold() for p in PALAVRAS_DE_CONTROLE_DE_ACESSO)


def test_manifesto_sem_campo_de_politica_e_recusado(tmp_path: Path) -> None:
    manifesto = tmp_path / "x.yaml"
    manifesto.write_text("id: files.read\ncapability: files.read\n", encoding="utf-8")

    with pytest.raises(ManifestoInvalido, match="access_level_min"):
        carregar(manifesto)


def test_capacidade_canivete_suico_e_recusada(tmp_path: Path) -> None:
    manifesto = tmp_path / "y.yaml"
    manifesto.write_text(
        "id: system.run_command\ncapability: system.exec\nrisk_class: leitura\n"
        "confirmation: never\naccess_level_min: jarvis\nrequires_elevation: false\nroots: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestoInvalido, match="canivete suíço"):
        carregar(manifesto)


# --- (g) mudança de nível ---------------------------------------------------------
def test_reduzir_nivel_vale_na_hora_e_cancela_chamada_em_voo(pdp: Pdp) -> None:
    """Aceite (g), primeira metade."""
    pdp.modo = Modo.TOTAL
    decisao = pdp.decidir(Pedido(tool_id="system.read.status", args={}, call_id="c-1"))
    assert decisao.veredito is Veredito.ALLOW
    grant = decisao.grant
    assert grant is not None
    epoch_antes = pdp.policy_epoch

    cancelados = pdp.reduzir(Modo.JARVIS)

    assert cancelados == ["c-1"]
    assert pdp.policy_epoch == epoch_antes + 1
    assert not grant.valido(policy_epoch=pdp.policy_epoch)  # grant de amplitude maior morre


def test_ampliar_nivel_so_vale_depois_da_confirmacao_do_dono(pdp: Pdp) -> None:
    """Aceite (g), segunda metade."""
    pdp.modo = Modo.PADRAO

    pdp.pedir_ampliacao(Modo.TOTAL)
    assert pdp.modo is Modo.PADRAO  # pedir não amplia

    with pytest.raises(PermissionError, match="dono presente"):
        pdp.confirmar_ampliacao(dono_presente=False)
    assert pdp.modo is Modo.PADRAO

    assert pdp.confirmar_ampliacao(dono_presente=True) is Modo.TOTAL


def test_reduzir_para_modo_mais_amplo_e_erro(pdp: Pdp) -> None:
    pdp.modo = Modo.JARVIS

    with pytest.raises(ValueError, match="não é mais estreito"):
        pdp.reduzir(Modo.TOTAL)


# --- auditoria --------------------------------------------------------------------
def test_decisao_e_registrada_antes_do_efeito(pdp: Pdp, auditoria: LogDeAuditoria) -> None:
    pdp.modo = Modo.TOTAL
    decisao = pdp.decidir(Pedido(tool_id="system.read.status", args={}, call_id="c-9"))

    registros = list(auditoria.decisoes())

    assert [r.veredito for r in registros] == ["allow"]
    assert registros[0].decision_id == decisao.decision_id
    # O resultado chega depois, em cadeia própria: a decisão não é reescrita.
    auditoria.anexar_resultado(decisao.decision_id, "ok", "status devolvido")
    assert auditoria.verificar_cadeia() == 2


def test_negacao_tambem_e_auditada(pdp: Pdp, auditoria: LogDeAuditoria) -> None:
    pdp.decidir(Pedido(tool_id="files.move_to_trash", args={}, caminho="/casa/sodre/.ssh/id_rsa"))

    registros = list(auditoria.decisoes())

    assert [r.veredito for r in registros] == ["deny"]
    assert "negação" in registros[0].motivo


def test_adulterar_a_auditoria_quebra_a_cadeia(pdp: Pdp, auditoria: LogDeAuditoria) -> None:
    pdp.modo = Modo.TOTAL
    for i in range(3):
        pdp.decidir(Pedido(tool_id="system.read.status", args={}, call_id=f"c-{i}"))
    assert auditoria.verificar_cadeia() == 3

    con = sqlite3.connect(auditoria.caminho, isolation_level=None)
    con.execute("DROP TRIGGER audit_log_sem_update")
    con.execute("UPDATE audit_log SET veredito = 'allow', motivo = 'nada a ver' WHERE seq = 2")
    con.close()

    with pytest.raises(CadeiaDeAuditoriaRompida, match="adulterado no seq 2"):
        auditoria.verificar_cadeia()


def test_banco_de_auditoria_recusa_update_e_delete(pdp: Pdp, auditoria: LogDeAuditoria) -> None:
    pdp.decidir(Pedido(tool_id="system.read.status", args={}))  # gatilho precisa de linha
    con = sqlite3.connect(auditoria.caminho, isolation_level=None)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE audit_log SET motivo = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM audit_log")
    con.close()


def test_tool_fora_do_catalogo_e_negada(pdp: Pdp) -> None:
    decisao = pdp.decidir(Pedido(tool_id="files.rm_rf", args={}))

    assert decisao.veredito is Veredito.DENY
    assert "fora do catálogo" in decisao.motivo


def test_grant_expira_e_nao_atravessa_policy_epoch(pdp: Pdp) -> None:
    decisao = pdp.decidir(Pedido(tool_id="system.read.status", args={}))
    grant = decisao.grant
    assert grant is not None

    assert grant.valido(policy_epoch=pdp.policy_epoch)
    assert not grant.valido(policy_epoch=pdp.policy_epoch + 1)
    assert not grant.valido(policy_epoch=pdp.policy_epoch, agora=grant.expira_em + 1)
