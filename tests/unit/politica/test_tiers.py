"""Controle por voz sem pedir permissão para o simples (dono, 2026-10-18).

Três tiers no manifesto de cada tool, validados e impostos pelo PDP:

- **livre** — abrir app/site/navegador, listar/ler/buscar arquivo, memória (busca), hora e estado,
  mídia, volume: sem confirmação e sem aviso;
- **moderado** — rascunho, criar arquivo/pasta na área do Jarvis, mover/copiar dentro das raízes:
  sem confirmação, com **aviso falado**, registro na auditoria e **desfazer** quando dá;
- **perigoso** — apagar, sobrescrever, enviar, gastar, instalar, fora das raízes: **continua
  confirmando**, e a IA nunca confirma por ele.

Um teste por tool, sobre o catálogo real: errar o tier de uma tool nova derruba a suíte.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.manifesto.lint import lintar_manifesto
from jarvis.manifesto.validador import ManifestoInvalido, carregar_catalogo, validar_manifesto
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import RISCOS_QUE_SEMPRE_CONFIRMAM
from jarvis.politica.catalogo import carregar_catalogo as capacidades
from jarvis.politica.memoria import Proveniencia, TurnoCorrente
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp, Pedido, Veredito

MANIFESTOS = carregar_catalogo()

# O que o dono pediu, tool por tool. Mudar um tier aqui é decisão dele, não do código.
TIER_ESPERADO: dict[str, str] = {
    # livre
    "apps.launch": "livre",
    "browser.launch": "livre",
    "sites.open": "livre",
    "files.list_dir": "livre",
    "files.read_text": "livre",
    "files.search_in_roots": "livre",
    "memoria.buscar": "livre",
    "memoria.buscar_historico": "livre",
    "memoria.ler_mensagem": "livre",
    "system.read.status": "livre",
    "tarefa.cancelar": "livre",
    "tarefa.estado": "livre",
    # moderado
    "files.write_draft": "moderado",
    "calendar.create_draft_event": "moderado",
    "memoria.lembrar": "moderado",
    "memoria.criar_no": "moderado",
    "memoria.criar_aresta": "moderado",
    "acao.desfazer": "moderado",
    "tarefa.iniciar": "moderado",
    # perigoso
    "files.move_to_trash": "perigoso",
    "memoria.apagar": "perigoso",
    "memoria.atualizar": "perigoso",
    "memoria.retratar": "perigoso",
    "system.install_package": "perigoso",
    # item 4 do pedido do dono (tools nativas de assistente de voz)
    "system.clock.now": "livre",
    "system.machine.status": "livre",
    "system.volume.get": "livre",
    "system.volume.set": "livre",
    "system.brightness.set": "livre",
    "media.player.control": "livre",
    "media.player.status": "livre",
    "window.list": "livre",
    "window.focused": "livre",
    "window.focus_app": "livre",
    # Fechar a janela é como o X (livre); encerrar o app é moderado, com o sim decidido pelo alvo
    # (dono, 2026-10-21; ADR-0042). Era a window.close_app, perigosa.
    "window.close": "livre",
    "apps.quit": "moderado",
    # Encerrar o próprio Jarvis (dono, 2026-10-21; ADR-0041): moderado — o sim só com tarefa em
    # andamento ou pergunta esperando, decidido pelo código (`Pedido.exige_o_sim`).
    "jarvis.encerrar": "moderado",
    # Aprender um nome do dono (dono, 2026-10-21; ADR-0044): moderado — escreve no vocabulário dele,
    # avisa em voz e desfaz; o sim só quando o turno leu conteúdo de fora (`decidir_vocabulario`).
    "vocabulario.aprender": "moderado",
    # Trocar o preset de modelo (dono, 2026-10-29; ADR-0056): moderado — grava o arquivo de presets
    # dele, avisa e desfaz; o sim só quando o turno leu conteúdo de fora (`decidir_preset`).
    "modelo.preset": "moderado",
    "clipboard.text.read": "livre",
    "clipboard.text.write": "moderado",
    "notify.desktop.send": "livre",
    "timer.alarm.set": "moderado",
    "timer.alarm.list": "livre",
    "timer.alarm.cancel": "livre",
    "web.buscar": "livre",
    "web.canal_videos": "livre",
    "web.ler": "livre",
    "files.create_dir": "moderado",
    "files.copy": "moderado",
    "files.move": "moderado",
    "browser.estado": "livre",
    "browser.tabs": "livre",
    "browser.read": "livre",
    "browser.click": "moderado",
    "browser.type": "moderado",
    "browser.scroll": "moderado",
    "browser.navigate": "moderado",
    "browser.inspecionar": "livre",
    "browser.acionar": "moderado",
    "browser.tela": "livre",
    "browser.acao_sensivel": "perigoso",
    # Fechar uma aba (dono, 2026-10-29; ADR-0057): moderado; a do pedido (ou do site citado) fecha
    # direto, a do dono pede o sim pelo escopo do pedido.
    "browser.fechar_aba": "moderado",
    # Navegador por CDP (dono, 2026-10-29; ADR-0051): console e rede são leitura; avaliar JS e
    # gesto físico são moderado e passam pelo guarda de contexto (ADR-0049).
    "browser.console": "livre",
    "browser.rede": "livre",
    "browser.avaliar": "moderado",
    "browser.gesto": "moderado",
    # Executor de scripts isolado (dono, 2026-10-29; ADR-0050): roda numa caixa sem rede nem os
    # arquivos do dono; moderado, com o guarda julgando antes do PDP.
    "script.rodar": "moderado",
    # Delegar ao Claude Code do dono (dono, 2026-10-29; ADR-0054): moderado no tier, mas o sim é
    # pedido pelo código na 1ª (e única) delegação do pedido (`Pedido.exige_o_sim`) e o guarda
    # compara a tarefa com o objetivo.
    "delegar.claude_code": "moderado",
    # A tela do Jarvis (dono, 2026-10-29; ADR-0055): só mudam o que a janela mostra, sem efeito
    # persistente e sem rede — livres.
    "tela.mostrar": "livre",
    "tela.ler": "livre",
    "tela.fechar": "livre",
    "input.mouse.move": "moderado",
    "input.mouse.click": "moderado",
    "input.key.type": "moderado",
    "input.key.press": "moderado",
    "input.acao_sensivel": "perigoso",
}


def test_o_catalogo_tem_o_tier_que_o_dono_pediu_em_cada_tool() -> None:
    reais = {i: str(m["tier"]) for i, m in MANIFESTOS.items()}
    esperados = {i: t for i, t in TIER_ESPERADO.items()}
    assert reais.items() >= esperados.items(), {
        i: (reais.get(i), t) for i, t in esperados.items() if reais.get(i) != t
    }
    sem_decisao = sorted(set(reais) - set(TIER_ESPERADO))
    assert not sem_decisao, f"tool nova sem tier decidido neste teste: {sem_decisao}"


@pytest.mark.parametrize("tool_id", sorted(MANIFESTOS))
def test_o_manifesto_de_cada_tool_e_coerente_com_o_tier(tool_id: str) -> None:
    m = MANIFESTOS[tool_id]
    tier = m["tier"]
    if tier == "perigoso":
        assert m["confirmation"] != "never", "perigoso pergunta"
        return
    assert m["confirmation"] == "never", f"{tier} nunca pergunta"
    assert m["risk_class"] not in RISCOS_QUE_SEMPRE_CONFIRMAM, (
        "o que confirma em qualquer modo é perigoso"
    )
    assert not m["requires_elevation"]
    if tier == "livre":
        assert m["side_effect"] != "persistent", "escrita persistente é moderado"
    else:
        assert m["aviso_falado"], "moderado fala o que fez"
        assert m["data_egress"] in ("none", "local")
        if m["side_effect"] == "persistent":
            assert m["reversible"] and m.get("undo"), "moderado que escreve tem como desfazer"


@pytest.mark.parametrize("tool_id", sorted(MANIFESTOS))
def test_nenhuma_tool_deixa_o_modelo_se_autoconfirmar(tool_id: str) -> None:
    achados = [
        a
        for a in lintar_manifesto(MANIFESTOS[tool_id], f"{tool_id}.yaml")
        if a.regra == "autoconfirmacao"
    ]
    assert achados == []


def test_o_lint_pega_argumento_que_deixaria_a_ia_confirmar() -> None:
    manifesto = dict(MANIFESTOS["files.write_draft"])
    manifesto["input_schema"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"nome": {"type": "string"}, "confirmado_pelo_dono": {"type": "boolean"}},
    }

    achados = lintar_manifesto(manifesto, "x.yaml")

    assert any(a.regra == "autoconfirmacao" for a in achados)


# --- o validador recusa tier incoerente -----------------------------------------------------
def _com(base: str, **mudancas: Any) -> dict[str, Any]:
    manifesto = dict(MANIFESTOS[base]) | mudancas
    return {k: v for k, v in manifesto.items() if v != "(sem o campo)"}


@pytest.mark.parametrize(
    ("base", "mudancas", "trecho"),
    [
        ("files.move_to_trash", {"confirmation": "never"}, "perigoso e tem confirmation: never"),
        ("files.write_draft", {"confirmation": "per_action"}, "só o tier perigoso pergunta"),
        ("files.list_dir", {"risk_class": "apagar_permanente"}, "confirma em qualquer modo"),
        ("sites.open", {"risk_class": "egress"}, "confirma em qualquer modo"),
        (
            "files.read_text",
            {"side_effect": "persistent", "idempotency": "required", "reversible": False},
            "escreve de forma persistente",
        ),
        ("files.write_draft", {"aviso_falado": "(sem o campo)"}, "não tem `aviso_falado`"),
        ("files.write_draft", {"aviso_falado": "Gravei {segredo}."}, "cita"),
        ("files.write_draft", {"reversible": False}, "não é reversível"),
        (
            "files.write_draft",
            {"data_egress": "network:nuvem", "risk_class": "egress"},
            "confirma em qualquer modo",
        ),
        ("system.install_package", {"tier": "moderado"}, "só o tier perigoso pergunta"),
        ("files.write_draft", {"tier": "tanto-faz"}, "tier"),
        # Passo de navegação sem aviso falado (ADR-0031): nunca em escrita que fica, nem fora do
        # moderado, nem com valor que não seja booleano.
        ("files.write_draft", {"aviso_silencioso": True}, "o dono ouve"),
        ("sites.open", {"aviso_silencioso": True}, "o dono ouve"),
        ("browser.click", {"aviso_silencioso": "sim"}, "aviso_silencioso"),
    ],
)
def test_o_validador_recusa_tier_incoerente(
    base: str, mudancas: dict[str, Any], trecho: str
) -> None:
    with pytest.raises(ManifestoInvalido, match=trecho):
        validar_manifesto(_com(base, **mudancas), origem="teste")


def test_so_os_passos_de_navegacao_tem_o_aviso_silencioso() -> None:
    """Dono, 2026-10-20 (ADR-0031): clicar, digitar, rolar, navegar e acionar (que equivale a
    clicar, ADR-0032) não são narrados; o resto das moderadas (pasta, mover, memória, lembrete,
    teclado virtual…) o dono ouve."""
    silenciosos = {t for t, m in MANIFESTOS.items() if m.get("aviso_silencioso") is True}
    assert silenciosos == {
        "browser.acionar",
        "browser.avaliar",
        "browser.click",
        "browser.gesto",
        "browser.navigate",
        "browser.scroll",
        "browser.type",
    }


def test_manifesto_sem_tier_e_recusado() -> None:
    manifesto = _com("files.list_dir")
    del manifesto["tier"]
    with pytest.raises(ManifestoInvalido, match="tier"):
        validar_manifesto(manifesto, origem="teste")


# --- o PDP impõe, tool por tool ------------------------------------------------------------
@pytest.fixture
def pdp(tmp_path: Path) -> Iterator[Pdp]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=capacidades(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            apps_autorizados=frozenset({"calculadora"}),
            navegadores=frozenset({"firefox"}),
            navegador_principal="firefox",
        )
        (tmp_path / "area" / "rascunhos" / "agenda").mkdir(parents=True)
        yield pdp


TURNO = TurnoCorrente("ep-1", "lembra que a Ana faz aniversário em março", "user_voice")
PROVENIENCIA = Proveniencia(turno=TURNO, motor="teste")


def _pedido(pdp: Pdp, tool_id: str, args: dict[str, Any], caminho: str | None = None) -> Pedido:
    return Pedido(tool_id, args, caminho, proveniencia=PROVENIENCIA, call_id=f"c-{tool_id}")


def casos(pdp: Pdp) -> dict[str, Pedido]:
    lar, area = str(pdp.lar), str(pdp.pasta_do_jarvis)
    return {
        "apps.launch": _pedido(pdp, "apps.launch", {"nome": "Calculadora"}),
        "browser.launch": _pedido(pdp, "browser.launch", {}),
        "sites.open": _pedido(pdp, "sites.open", {"url": "https://pt.wikipedia.org/wiki/Jarvis"}),
        "files.list_dir": _pedido(pdp, "files.list_dir", {"path": "x"}, f"{lar}/Documentos"),
        "files.read_text": _pedido(pdp, "files.read_text", {"path": "x"}, f"{lar}/Documentos"),
        "files.search_in_roots": _pedido(pdp, "files.search_in_roots", {"consulta": "notas"}),
        "memoria.buscar": _pedido(pdp, "memoria.buscar", {"consulta": "Ana"}),
        "memoria.buscar_historico": _pedido(pdp, "memoria.buscar_historico", {"consulta": "Ana"}),
        "memoria.ler_mensagem": _pedido(pdp, "memoria.ler_mensagem", {"episode_id": "ep-1"}),
        "system.read.status": _pedido(pdp, "system.read.status", {}),
        "files.write_draft": _pedido(
            pdp, "files.write_draft", {"nome": "a", "texto": "b"}, f"{area}/rascunhos"
        ),
        "calendar.create_draft_event": _pedido(
            pdp,
            "calendar.create_draft_event",
            {"titulo": "x", "inicio": "2026-10-20T10:00"},
            f"{area}/rascunhos/agenda",
        ),
        "memoria.lembrar": _pedido(
            pdp, "memoria.lembrar", {"texto": "a Ana faz aniversário em março"}
        ),
        "memoria.criar_no": _pedido(pdp, "memoria.criar_no", {"tipo": "pessoa", "nome": "Ana"}),
        "memoria.criar_aresta": _pedido(
            pdp,
            "memoria.criar_aresta",
            {"origem": "Ana", "relacao": "faz aniversário em", "destino": "março"},
        ),
        "acao.desfazer": _pedido(pdp, "acao.desfazer", {}, area),
        "tarefa.iniciar": _pedido(
            pdp, "tarefa.iniciar", {"descricao": "achar notas", "tool": "files.search_in_roots"}
        ),
        "tarefa.cancelar": _pedido(pdp, "tarefa.cancelar", {"tarefa_id": "t-1"}),
        "tarefa.estado": _pedido(pdp, "tarefa.estado", {}),
        "files.move_to_trash": _pedido(
            pdp, "files.move_to_trash", {"path": "x"}, f"{area}/rascunhos"
        ),
        "memoria.apagar": _pedido(pdp, "memoria.apagar", {"alvo_id": "ast-1", "escopo": "memoria"}),
        "memoria.atualizar": _pedido(
            pdp,
            "memoria.atualizar",
            {"assertion_id": "ast-1", "texto": "novo texto aqui", "motivo": "mudou"},
        ),
        "memoria.retratar": _pedido(pdp, "memoria.retratar", {"alvo_id": "ast-1"}),
        "system.install_package": _pedido(pdp, "system.install_package", {"pacote": "vlc"}),
        "system.clock.now": _pedido(pdp, "system.clock.now", {}),
        "system.machine.status": _pedido(pdp, "system.machine.status", {}),
        "system.volume.get": _pedido(pdp, "system.volume.get", {}),
        "system.volume.set": _pedido(pdp, "system.volume.set", {"nivel": 30}),
        "system.brightness.set": _pedido(pdp, "system.brightness.set", {"nivel": 50}),
        "media.player.control": _pedido(pdp, "media.player.control", {"acao": "pausar"}),
        "media.player.status": _pedido(pdp, "media.player.status", {}),
        "window.list": _pedido(pdp, "window.list", {}),
        "window.focused": _pedido(pdp, "window.focused", {}),
        "window.focus_app": _pedido(pdp, "window.focus_app", {"app": "firefox"}),
        "window.close": _pedido(pdp, "window.close", {"app": "firefox"}),
        "apps.quit": _pedido(pdp, "apps.quit", {"app": "discord"}),
        "jarvis.encerrar": _pedido(pdp, "jarvis.encerrar", {}),
        "vocabulario.aprender": _pedido(
            pdp, "vocabulario.aprender", {"escrita": "Discord", "ouvido": ["discorde"]}
        ),
        "modelo.preset": _pedido(pdp, "modelo.preset", {"nome": "rápido"}),
        "clipboard.text.read": _pedido(pdp, "clipboard.text.read", {}),
        "clipboard.text.write": _pedido(pdp, "clipboard.text.write", {"texto": "x"}),
        "notify.desktop.send": _pedido(pdp, "notify.desktop.send", {"titulo": "a", "texto": "b"}),
        "timer.alarm.set": _pedido(pdp, "timer.alarm.set", {"mensagem": "bolo", "em_segundos": 60}),
        "timer.alarm.list": _pedido(pdp, "timer.alarm.list", {}),
        "timer.alarm.cancel": _pedido(pdp, "timer.alarm.cancel", {"alarme_id": "al-1"}),
        "web.buscar": _pedido(pdp, "web.buscar", {"consulta": "capital da França"}),
        "web.canal_videos": _pedido(
            pdp, "web.canal_videos", {"canal": "https://www.youtube.com/@exemplo"}
        ),
        "web.ler": _pedido(pdp, "web.ler", {"url": "https://pt.wikipedia.org/wiki/Paris"}),
        "browser.fechar_aba": _pedido(pdp, "browser.fechar_aba", {"tab_id": 3}),
        "tela.mostrar": _pedido(
            pdp, "tela.mostrar", {"html": "<h1>Compras</h1><ul><li>pão</li></ul>"}
        ),
        "tela.ler": _pedido(pdp, "tela.ler", {}),
        "tela.fechar": _pedido(pdp, "tela.fechar", {"todas": True}),
        "files.create_dir": _pedido(
            pdp, "files.create_dir", {"path": "x"}, f"{lar}/Documentos/nova"
        ),
        "files.copy": _pedido(
            pdp, "files.copy", {"origem": "a", "destino": "b"}, f"{lar}/Documentos/b.txt"
        ),
        "files.move": _pedido(
            pdp, "files.move", {"origem": "a", "destino": "b"}, f"{lar}/Documentos/b.txt"
        ),
        "browser.estado": _pedido(pdp, "browser.estado", {}),
        "browser.tabs": _pedido(pdp, "browser.tabs", {}),
        "browser.read": _pedido(pdp, "browser.read", {}),
        "browser.click": _pedido(pdp, "browser.click", {"alvo": "Próxima"}),
        "browser.type": _pedido(pdp, "browser.type", {"alvo": "Busca", "texto": "gatos"}),
        "browser.scroll": _pedido(pdp, "browser.scroll", {"pixels": 600}),
        "browser.navigate": _pedido(pdp, "browser.navigate", {"url": "https://exemplo.org/"}),
        "browser.inspecionar": _pedido(pdp, "browser.inspecionar", {"tipo": "campos"}),
        "browser.tela": _pedido(pdp, "browser.tela", {}),
        "browser.acionar": _pedido(
            pdp, "browser.acionar", {"ref": "ab1.1", "acao": "tecla", "tecla": "Enter"}
        ),
        "browser.console": _pedido(pdp, "browser.console", {}),
        "browser.rede": _pedido(pdp, "browser.rede", {}),
        "browser.avaliar": _pedido(
            pdp, "browser.avaliar", {"codigo": "document.title", "mundo": "isolado"}
        ),
        "browser.gesto": _pedido(pdp, "browser.gesto", {"gesto": "rolar", "pixels": 300}),
        "script.rodar": _pedido(pdp, "script.rodar", {"linguagem": "python", "codigo": "print(1)"}),
        "delegar.claude_code": _pedido(
            pdp, "delegar.claude_code", {"tarefa": "traga o horário da página de agenda"}
        ),
        "browser.acao_sensivel": _pedido(
            pdp, "browser.acao_sensivel", {"acao": "browser.click", "detalhe": "Enviar"}
        ),
        "input.mouse.move": _pedido(pdp, "input.mouse.move", {"dx": 10, "dy": 0}),
        "input.mouse.click": _pedido(pdp, "input.mouse.click", {"botao": "esquerdo"}),
        "input.key.type": _pedido(pdp, "input.key.type", {"texto": "oi"}),
        "input.key.press": _pedido(pdp, "input.key.press", {"tecla": "ctrl+l"}),
        "input.acao_sensivel": _pedido(
            pdp, "input.acao_sensivel", {"acao": "input.key.press", "detalhe": "enter"}
        ),
    }


@pytest.mark.parametrize("tool_id", sorted(TIER_ESPERADO))
def test_o_pdp_decide_pelo_tier_de_cada_tool(pdp: Pdp, tool_id: str) -> None:
    tier = TIER_ESPERADO[tool_id]
    if tool_id == "system.install_package":
        pdp.modo = Modo.TOTAL
        pdp.ligar_elevacao(dono_presente=True)
    pedido = casos(pdp)[tool_id]

    decisao = pdp.decidir(pedido)

    if tier == "perigoso":
        assert decisao.veredito is Veredito.CONFIRM, (tool_id, decisao)
        # O "sim" do dono (e só ele, passado pelo executor) solta; nada no pedido o imita.
        assert pdp.decidir(pedido, confirmado_pelo_dono=True).veredito is Veredito.ALLOW
    else:
        assert decisao.veredito is Veredito.ALLOW, (tool_id, decisao)


@pytest.mark.parametrize(
    "tool_id", [t for t, tier in sorted(TIER_ESPERADO.items()) if tier == "perigoso"]
)
def test_perigoso_nao_e_confirmavel_por_argumento_do_modelo(pdp: Pdp, tool_id: str) -> None:
    """Nenhum argumento, por mais que o modelo o invente, vira confirmação (P1)."""
    if tool_id == "system.install_package":
        pdp.modo = Modo.TOTAL
        pdp.ligar_elevacao(dono_presente=True)
    base = casos(pdp)[tool_id]
    for extra in ({"confirmado": True}, {"confirmado_pelo_dono": True}, {"forcar": True}):
        pedido = Pedido(
            tool_id,
            {**base.args, **extra},
            base.caminho,
            proveniencia=PROVENIENCIA,
            call_id="c-x",
        )
        assert pdp.decidir(pedido).veredito is Veredito.CONFIRM


def test_deny_nunca_vira_allow_com_o_sim_do_dono(pdp: Pdp) -> None:
    """A lista de negação vence o tier e o "sim": ~/.ssh é negado, não confirmável."""
    pedido = Pedido("files.read_text", {"path": "x"}, f"{pdp.lar}/.ssh/id_rsa")

    assert pdp.decidir(pedido).veredito is Veredito.DENY
    assert pdp.decidir(pedido, confirmado_pelo_dono=True).veredito is Veredito.DENY


def test_fora_das_raizes_continua_negado_mesmo_sendo_livre(pdp: Pdp, tmp_path: Path) -> None:
    fora = Pedido("files.list_dir", {"path": "x"}, str(tmp_path / "fora"))

    decisao = pdp.decidir(fora)

    assert decisao.veredito is Veredito.DENY and "fora das raízes" in decisao.motivo


def test_site_livre_vira_confirmacao_depois_de_ler_conteudo_de_terceiros(pdp: Pdp) -> None:
    """Abrir site é livre, mas o endereço leva dado: se um texto de fora pode tê-lo escolhido, o
    dono confirma — e site que ele mesmo liberou segue livre."""
    url = {"url": "https://exemplo.com/?q=dado"}
    pdp.sites_sem_confirmar = frozenset({"wikipedia.org"})

    limpo = pdp.decidir(Pedido("sites.open", url))
    contaminado = pdp.decidir(Pedido("sites.open", url, contaminado=True))
    liberado = pdp.decidir(
        Pedido("sites.open", {"url": "https://pt.wikipedia.org/wiki/X"}, contaminado=True)
    )
    solto = pdp.decidir(Pedido("sites.open", url, contaminado=True), confirmado_pelo_dono=True)

    assert limpo.veredito is Veredito.ALLOW
    assert contaminado.veredito is Veredito.CONFIRM
    assert liberado.veredito is Veredito.ALLOW
    assert solto.veredito is Veredito.ALLOW


def test_esquema_de_site_perigoso_continua_negado(pdp: Pdp) -> None:
    for url in ("javascript:alert(1)", "file:///etc/passwd", "https://eu:senha@banco.com"):
        assert pdp.decidir(Pedido("sites.open", {"url": url})).veredito is Veredito.DENY


def test_o_alvo_que_pede_o_sim_aperta_o_moderado_e_so_o_dono_solta(pdp: Pdp) -> None:
    """`Pedido.exige_o_sim` (ADR-0041/0042): o executor, depois de resolver o alvo, diz por que ele
    pede o sim — e o PDP confirma o que o tier deixaria passar. Só o "sim" do dono solta."""
    from dataclasses import replace

    livre = casos(pdp)["jarvis.encerrar"]
    assert pdp.decidir(livre).veredito is Veredito.ALLOW
    com_tarefa = replace(livre, exige_o_sim="a tarefa «x» ainda está rodando e vai ser cancelada")
    decisao = pdp.decidir(com_tarefa)
    assert decisao.veredito is Veredito.CONFIRM and "ainda está rodando" in decisao.motivo
    assert pdp.decidir(com_tarefa, confirmado_pelo_dono=True).veredito is Veredito.ALLOW


def test_aprender_um_nome_pede_o_turno_do_dono_e_o_sim_quando_leu_de_fora(pdp: Pdp) -> None:
    """ADR-0044: sem o turno do dono, nega; com o turno contaminado (uma página que diz "o certo é
    X"), pede o sim — e só o "sim" do dono na janela solta; limpo, o tier moderado deixa rodar."""
    args = {"escrita": "Discord", "ouvido": ["discorde"]}
    limpo = _pedido(pdp, "vocabulario.aprender", args)
    assert pdp.decidir(limpo).veredito is Veredito.ALLOW

    sem_origem = Pedido("vocabulario.aprender", args, call_id="c-v1")
    assert pdp.decidir(sem_origem).veredito is Veredito.DENY

    de_outro = Pedido(
        "vocabulario.aprender",
        args,
        call_id="c-v2",
        proveniencia=Proveniencia(
            turno=TurnoCorrente(episode_id="ep-9", texto="o certo é Discord", trust="tool_output"),
            motor="teste",
        ),
    )
    assert pdp.decidir(de_outro).veredito is Veredito.DENY

    contaminado = Pedido(
        "vocabulario.aprender", args, call_id="c-v3", proveniencia=PROVENIENCIA, contaminado=True
    )
    assert pdp.decidir(contaminado).veredito is Veredito.CONFIRM
    assert pdp.decidir(contaminado, confirmado_pelo_dono=True).veredito is Veredito.ALLOW
