"""Fechar a janela × encerrar o app (dono, 2026-10-21; ADR-0042).

As frases do dono: "fecha o discord" (a janela, como o X), "fecha o discord todo" (o app inteiro),
"fecha a janela" e "fecha esse aí" (a da frente), "encerra o steam inteiro" (o Steam e o jogo,
com o sim). Portas falsas — a lista de janelas, a tabela de processos (que "morre" com o sinal), o
relógio — e, no fim, processos descartáveis de verdade, criados pelo próprio teste numa sessão
nova, com executável de nome único: nenhum app do dono é tocado.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from jarvis.executor.fechar import (
    AlvoRecusado,
    Fechador,
    Jarvis,
    Processo,
    TabelaDoProc,
    protecao,
)
from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.executor.janelas import JanelaDoSistema
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.executor.nativas import Nativas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.metodo import ContextoDoMetodo, escolher_metodo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp

EU = 1000
OUTRO = 1001
JARVIS = Jarvis(pid=500, uid=EU, sessao=400, ancestrais=frozenset({400, 300}))


def _id(n: int) -> str:
    return f"{{00000000-0000-0000-0000-{n:012d}}}"


def _p(
    pid: int, pai: int, exe: str, *, uid: int = EU, sessao: int = 0, inicio: int = 1
) -> Processo:
    return Processo(pid, pai, uid, exe, inicio, sessao or pid)


def _app(id_: str, nome: str, exe: str, *categorias: str, esquemas: tuple[str, ...] = ()) -> App:
    return App(
        id=id_,
        nome=nome,
        nomes=(nome, exe),
        argv=(f"/usr/bin/{exe}",),
        arquivo=Path(f"/nao/existe/{id_}.desktop"),
        categorias=categorias,
        esquemas=esquemas,
        exec_nome=exe,
    )


CATALOGO = {
    a.id: a
    for a in (
        _app("discord", "Discord", "Discord", "Network", "InstantMessaging"),
        _app("steam", "Steam", "steam", "Network", "FileTransfer", "Game"),
        _app("org.kde.kate", "Kate", "kate", "Qt", "KDE", "Utility", "TextEditor"),
        _app("vlc", "VLC", "vlc", "AudioVideo", "Player", "Video"),
        _app("firefox", "Firefox", "firefox", "Network", "WebBrowser", esquemas=("https",)),
        _app("org.kde.konsole", "Konsole", "konsole", "Qt", "KDE", "System", "TerminalEmulator"),
        _app("claude", "Claude", "claude", "Development"),
    )
}


@dataclass
class TabelaFalsa:
    """Os processos da "máquina" do teste. SIGTERM leva o processo e os filhos (como um app que
    sai); quem está em `teimosos` ignora o SIGTERM; SIGKILL leva só aquele."""

    processos: dict[int, Processo]
    argv: dict[int, tuple[str, ...]] = field(default_factory=dict)
    teimosos: set[int] = field(default_factory=set)
    sinais: list[tuple[int, int]] = field(default_factory=list)

    def listar(self) -> list[Processo]:
        return list(self.processos.values())

    def ler(self, pid: int) -> Processo | None:
        return self.processos.get(pid)

    def argumentos(self, pid: int) -> tuple[str, ...]:
        return self.argv.get(pid, ())

    def sinalizar(self, pid: int, sinal: int) -> None:
        self.sinais.append((pid, sinal))
        if sinal == signal.SIGTERM and pid in self.teimosos:
            return
        mortos = {pid}
        if sinal == signal.SIGTERM:
            mudou = True
            while mudou:
                filhos = {p.pid for p in self.processos.values() if p.pai in mortos} - mortos
                mudou = bool(filhos)
                mortos |= filhos
        for morto in mortos:
            self.processos.pop(morto, None)


@dataclass
class JanelasFalsas:
    janelas: list[JanelaDoSistema]
    somem: bool = True
    fechadas: list[str] = field(default_factory=list)

    def listar(self) -> list[JanelaDoSistema]:
        return list(self.janelas)

    def ativar(self, janela_id: str) -> bool:
        return True

    def fechar(self, janela_id: str) -> bool:
        self.fechadas.append(janela_id)
        if self.somem:
            self.janelas = [j for j in self.janelas if j.id != janela_id]
        return True


@dataclass
class Relogio:
    agora: float = 0.0

    def __call__(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.agora += segundos


def _maquina() -> tuple[TabelaFalsa, JanelasFalsas]:
    processos = [
        _p(1, 0, "systemd", uid=0),
        _p(300, 1, "konsole"),  # o terminal em que o Jarvis roda
        _p(400, 300, "bash"),
        _p(500, 400, "python3", sessao=400),  # o Jarvis
        _p(510, 500, "claude", sessao=400),  # o claude -p do Jarvis
        _p(600, 1, "plasmashell"),
        _p(700, 1, "Discord"),
        _p(701, 700, "Discord"),
        _p(702, 700, "chrome_crashpad_handler"),
        _p(750, 1, "Discord", uid=OUTRO),  # o Discord de outro usuário da máquina
        _p(800, 1, "steam"),
        _p(801, 800, "steamwebhelper"),
        _p(802, 800, "reaper"),
        _p(803, 802, "Spacewar.x86_64"),
        _p(900, 1, "kate"),
        _p(950, 1, "vlc"),
        _p(951, 1, "vlc"),
        _p(990, 1, "firefox"),
        _p(991, 990, "firefox"),
    ]
    tabela = TabelaFalsa(
        {p.pid: p for p in processos},
        argv={802: ("/steam/reaper", "SteamLaunch", "AppId=480", "--", "/jogo")},
    )
    janelas = JanelasFalsas(
        [
            JanelaDoSistema(_id(1), "Área de trabalho", "plasmashell", 600),
            JanelaDoSistema(_id(2), "Discord", "discord", 700),
            JanelaDoSistema(_id(3), "notas.md — Kate", "org.kde.kate", 900),
            JanelaDoSistema(_id(4), "Steam", "steam", 800),
            JanelaDoSistema(_id(5), "Spacewar", "steam_app_480", 803),
            JanelaDoSistema(_id(6), "Wikipédia — Mozilla Firefox", "firefox", 990, ativa=True),
            JanelaDoSistema(_id(7), "Jarvis", "dev.sodredev.Jarvis", 500),
            JanelaDoSistema(_id(8), "bash — Konsole", "org.kde.konsole", 300),
        ]
    )
    return tabela, janelas


def _fechador(tabela: TabelaFalsa, janelas: JanelasFalsas | None) -> tuple[Fechador, Relogio]:
    relogio = Relogio()
    return (
        Fechador(
            janelas=janelas,
            tabela=tabela,
            catalogo=CATALOGO,
            navegadores=frozenset({"firefox"}),
            sinalizar=tabela.sinalizar,
            dormir=relogio.dormir,
            relogio=relogio,
            jarvis=JARVIS,
        ),
        relogio,
    )


# --- o que a fala pede (o roteador, ADR-0035) -------------------------------------------------
@pytest.mark.parametrize(
    ("fala", "motivo", "de_fora"),
    [
        ("fecha o discord", "fecha_janela", "apps.quit"),
        ("fecha a janela", "fecha_janela", "apps.quit"),
        ("fecha esse aí", "fecha_janela", "apps.quit"),
        ("fecha o discord todo", "encerra_app", "window.close"),
        ("encerra o steam inteiro", "encerra_app", "window.close"),
        ("mata o discord", "encerra_app", "window.close"),
        ("fecha o Discord de vez", "encerra_app", "window.close"),
    ],
)
def test_a_fala_decide_janela_ou_app_e_tira_a_outra_ferramenta(
    fala: str, motivo: str, de_fora: str
) -> None:
    escolha = escolher_metodo(fala, ContextoDoMetodo(apps=frozenset({"discord", "steam"})))
    assert escolha.motivo == motivo
    assert de_fora in escolha.evitar


def test_aba_nao_e_janela_e_encerrar_o_jarvis_e_outra_coisa() -> None:
    contexto = ContextoDoMetodo()
    assert escolher_metodo("fecha a aba do youtube", contexto).motivo not in (
        "fecha_janela",
        "encerra_app",
    )
    assert escolher_metodo("encerra o sistema", contexto).motivo == "encerra_o_jarvis"


# --- fechar a janela ------------------------------------------------------------------------------
def test_fecha_o_discord_fecha_so_a_janela_dele() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)

    alvo = fechador.janela("discord")
    dados = fechador.fechar_janela(alvo)

    assert janelas.fechadas == [_id(2)]
    assert dados["fechada"] is True and alvo.exige_o_sim == ""
    assert not tabela.sinais, "fechar a janela nunca manda sinal a processo"


def test_fecha_a_janela_e_fecha_esse_ai_sao_a_da_frente() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)

    alvo = fechador.janela(fala="fecha essa janela")  # sem nome: "fecha esse aí"

    assert alvo.janela.id == _id(6) and alvo.nome == "Firefox"
    assert alvo.exige_o_sim == "", "a ordem explícita do dono vale sem o sim (ADR-0046)"


def test_a_janela_do_navegador_que_o_dono_nao_citou_pede_o_sim() -> None:
    """O modelo (ou um texto lido) quer fechar o navegador num pedido que não fala dele: aí sim."""
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)

    alvo = fechador.janela("firefox", fala="lê a página e me resume")

    assert "ficou de fora do que você pediu" in alvo.exige_o_sim
    assert "navegador" in alvo.exige_o_sim


@pytest.mark.parametrize("fala", ["fecha meu firefox", "fecha o navegador", "fecha o Firefox."])
def test_fechar_o_navegador_a_pedido_nao_pergunta(fala: str) -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    pedido = "navegador" if "navegador" in fala else "meu firefox"

    alvo = fechador.janela(pedido, fala=fala)

    assert alvo.janela.id == _id(6) and alvo.exige_o_sim == ""


def test_o_navegador_sem_nome_e_o_da_frente_o_unico_ou_pergunta() -> None:
    """«Fecha o navegador» (dono, 2026-10-25): o que está em foco; senão o único aberto; senão o
    da frente de um monitor; dois igualmente plausíveis é pergunta."""
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    assert fechador.janela("navegador").nome == "Firefox", "o único aberto, e em foco"

    # Dois navegadores, nenhum em foco: o da frente de um monitor decide; sem ele, pergunta.
    tabela.processos[1200] = _p(1200, 1, "brave")
    janelas.janelas = [
        replace(j, ativa=False) if j.classe == "firefox" else j for j in janelas.janelas
    ] + [JanelaDoSistema(_id(12), "YouTube — Brave", "brave-browser", 1200, na_frente=True)]
    assert fechador.janela("o navegador").janela.id == _id(12)
    janelas.janelas = [replace(j, na_frente=False) for j in janelas.janelas]
    with pytest.raises(AlvoRecusado) as erro:
        fechador.janela("navegador")
    assert erro.value.causa == "alvo_ambiguo" and "Qual deles?" in str(erro.value)


def test_sem_navegador_aberto_diz_isso() -> None:
    tabela, janelas = _maquina()
    janelas.janelas = [j for j in janelas.janelas if j.classe != "firefox"]
    fechador, _ = _fechador(tabela, janelas)
    with pytest.raises(AlvoRecusado) as erro:
        fechador.janela("navegador")
    assert erro.value.causa == "alvo_ausente" and "nenhum navegador" in str(erro.value)


def test_varias_janelas_e_nenhuma_na_frente_pergunta_qual() -> None:
    tabela, janelas = _maquina()
    janelas.janelas.append(JanelaDoSistema(_id(9), "outro.md — Kate", "org.kde.kate", 900))
    fechador, _ = _fechador(tabela, janelas)

    with pytest.raises(AlvoRecusado) as erro:
        fechador.janela("kate")
    assert erro.value.causa == "alvo_ambiguo" and "Qual?" in str(erro.value)
    assert "notas.md" in str(erro.value) and "outro.md" in str(erro.value)


def test_a_janela_do_proprio_jarvis_nao_se_fecha_por_aqui() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    with pytest.raises(AlvoRecusado) as erro:
        fechador.janela("jarvis")
    assert erro.value.causa == "alvo_protegido" and "encerrar o Jarvis" in str(erro.value)


def test_janela_que_nao_some_diz_que_o_app_pode_estar_perguntando() -> None:
    tabela, janelas = _maquina()
    janelas.somem = False  # o Kate perguntou se salva
    fechador, _ = _fechador(tabela, janelas)

    dados = fechador.fechar_janela(fechador.janela("kate"))

    assert dados["fechada"] is False and "perguntando se salva" in str(dados["nota"])


def test_ambiguidade_de_nome_e_pergunta_nunca_palpite() -> None:
    tabela, janelas = _maquina()
    janelas.janelas += [
        JanelaDoSistema(_id(10), "Notas — rápidas", "notas-rapidas", None),
        JanelaDoSistema(_id(11), "Notas — da escola", "notas-escola", None),
    ]
    fechador, _ = _fechador(tabela, janelas)
    with pytest.raises(AlvoRecusado) as erro:
        fechador.janela("notas")
    assert erro.value.causa == "alvo_ambiguo"


# --- encerrar o app -------------------------------------------------------------------------------
def test_fecha_o_discord_todo_encerra_os_processos_dele_pelo_pid() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)

    alvo = fechador.app("discord")
    dados = fechador.encerrar_app(alvo)

    assert {p.pid for p in alvo.raizes} == {700}
    assert {p.pid for p in alvo.processos} == {700, 701, 702}
    assert 750 not in {p.pid for p in alvo.processos}, "o Discord de outro usuário não é dele"
    assert tabela.sinais == [(700, signal.SIGTERM)], "só a instância recebe o pedido de sair"
    assert dados["conferido"] is True and dados["sigkill"] == 0
    assert alvo.exige_o_sim == "", "um mensageiro sem nada a perder não pergunta"
    assert 750 in tabela.processos and 500 in tabela.processos


def test_quem_ignora_o_sigterm_leva_sigkill_so_depois_do_prazo() -> None:
    tabela, janelas = _maquina()
    tabela.teimosos.add(700)
    fechador, relogio = _fechador(tabela, janelas)

    dados = fechador.encerrar_app(fechador.app("discord"))

    assert tabela.sinais[0] == (700, signal.SIGTERM)
    assert (700, signal.SIGKILL) in tabela.sinais
    assert relogio.agora >= fechador.prazo_do_term_s, "forçou antes do prazo"
    assert dados["sigkill"] >= 1 and dados["conferido"] is True


def test_encerra_o_steam_inteiro_com_jogo_aberto_pede_o_sim_e_leva_o_jogo() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)

    alvo = fechador.app("steam")

    assert {801, 802, 803} <= {p.pid for p in alvo.processos}
    assert "jogo" in alvo.exige_o_sim and "progresso" in alvo.exige_o_sim


def test_steam_sem_jogo_aberto_nao_pergunta_por_ser_da_categoria_jogo() -> None:
    tabela, janelas = _maquina()
    for pid in (802, 803):
        tabela.processos.pop(pid)
    tabela.argv.clear()
    janelas.janelas = [j for j in janelas.janelas if not j.classe.startswith("steam_app")]
    fechador, _ = _fechador(tabela, janelas)
    assert fechador.app("steam").exige_o_sim == ""


def test_trabalho_nao_salvo_detectado_no_titulo_pede_o_sim_e_o_salvo_nao() -> None:
    """O sim é para o trabalho não salvo **detectado** (a marca do título), não para todo editor
    (dono, 2026-10-25; ADR-0046)."""
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    assert fechador.app("kate", fala="fecha o kate todo").exige_o_sim == ""
    janelas.janelas = [
        replace(j, titulo="notas.md * — Kate") if j.classe == "org.kde.kate" else j
        for j in janelas.janelas
    ]
    motivo = fechador.app("kate", fala="fecha o kate todo").exige_o_sim
    assert "trabalho por salvar" in motivo and "notas.md" in motivo


@pytest.mark.parametrize("pedido", ["firefox", "vlc"])
def test_encerrar_navegador_ou_varias_instancias_a_pedido_nao_pergunta(pedido: str) -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    assert fechador.app(pedido, fala=f"fecha o {pedido} todo").exige_o_sim == ""


def test_app_fora_da_lista_liberada_pede_o_sim() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    fechador.liberados = frozenset({"discord", "kate", "steam"})
    assert fechador.app("discord", fala="mata o discord").exige_o_sim == ""
    motivo = fechador.app("vlc", fala="mata o vlc").exige_o_sim
    assert "fora da sua lista" in motivo


def test_o_que_o_dono_nao_citou_pede_o_sim() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    motivo = fechador.app("discord", fala="libera memória do computador").exige_o_sim
    assert "o Discord ficou de fora do que você pediu" in motivo


def test_as_frases_do_sim_nao_soam_como_resposta() -> None:
    """A pergunta falada passa pelo eco do alto-falante: nenhuma frase do motivo traz "sim",
    "pode" ou "não", que o ouvido tomaria por resposta (ADR-0046, item da confirmação)."""
    tabela, janelas = _maquina()
    janelas.janelas = [
        replace(j, titulo="notas.md * — Kate") if j.classe == "org.kde.kate" else j
        for j in janelas.janelas
    ]
    fechador, _ = _fechador(tabela, janelas)
    fechador.liberados = frozenset()
    motivos = [
        fechador.app("steam", fala="x").exige_o_sim,
        fechador.app("kate", fala="x").exige_o_sim,
        fechador.janela("firefox", fala="x").exige_o_sim,
    ]
    for motivo in motivos:
        palavras = set(motivo.casefold().replace(",", " ").split())
        assert motivo and not palavras & {"sim", "pode", "não", "nao"}, motivo


@pytest.mark.parametrize(
    ("pedido", "por_que"),
    [
        ("konsole", "o Jarvis está rodando dentro dele"),
        ("claude", "é o próprio Jarvis"),
        ("plasmashell", "sessão do desktop"),
    ],
)
def test_o_que_nunca_e_encerrado(pedido: str, por_que: str) -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    with pytest.raises(AlvoRecusado) as erro:
        fechador.app(pedido)
    assert erro.value.causa == "alvo_protegido" and por_que in str(erro.value)
    assert not tabela.sinais


def test_o_app_da_janela_da_frente_e_o_que_se_encerra_sem_nome() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    alvo = fechador.app()  # "encerra esse aí"
    assert alvo.nome == "Firefox" and {p.pid for p in alvo.processos} == {990, 991}


def test_pid_reaproveitado_nao_leva_sinal() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    alvo = fechador.app("discord")
    # Entre a pergunta e o sinal, o Discord saiu e outro processo nasceu com o mesmo PID.
    tabela.processos[700] = replace(tabela.processos[700], executavel="outro", inicio=99)
    tabela.processos.pop(701)
    tabela.processos.pop(702)

    fechador.encerrar_app(alvo)

    assert not [s for s in tabela.sinais if s[0] == 700], "mandou sinal ao processo errado"


def test_sem_porta_de_janelas_encerra_pelo_nome_mas_nao_fecha_janela() -> None:
    tabela, _janelas = _maquina()
    fechador, _ = _fechador(tabela, None)

    assert {p.pid for p in fechador.app("discord").processos} == {700, 701, 702}
    with pytest.raises(AlvoRecusado) as erro:
        fechador.janela("discord")
    assert erro.value.causa == "sem_janelas" and "kdotool" in str(erro.value)
    with pytest.raises(AlvoRecusado):
        fechador.app()  # sem janelas, não há "o da frente"


def test_app_que_nao_esta_aberto_diz_isso() -> None:
    tabela, janelas = _maquina()
    fechador, _ = _fechador(tabela, janelas)
    with pytest.raises(AlvoRecusado) as erro:
        fechador.app("gimp")
    assert erro.value.causa == "alvo_ausente"


# --- pelo executor, com o PDP --------------------------------------------------------------------
LIBERADOS = ("discord", "steam", "org.kde.kate", "vlc")
"""Os apps que o dono liberou nestes testes: encerrar fora deles pede o sim (ADR-0046)."""


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            registro_de_apps=RegistroDeApps(
                autorizados={i: CATALOGO[i] for i in LIBERADOS},
                instalados=frozenset(CATALOGO),
                catalogo=CATALOGO,
            ),
        )
        executor.preparar()
        yield executor


def _ligar(executor: ExecutorDeFerramentas) -> tuple[TabelaFalsa, JanelasFalsas]:
    tabela, janelas = _maquina()
    relogio = Relogio()
    executor.nativas = Nativas(
        lar=executor.lar,
        janelas=janelas,
        processos=tabela,
        sinalizar=tabela.sinalizar,
        dormir=relogio.dormir,
        relogio=relogio,
        jarvis=JARVIS,
    )
    return tabela, janelas


def test_executor_fecha_a_janela_sem_perguntar(executor: ExecutorDeFerramentas) -> None:
    _tabela, janelas = _ligar(executor)
    perguntas: list[Confirmacao] = []

    def nao(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return False

    resultado = executor.executar(
        "window.close", {"app": "Discord"}, cancelado=lambda: False, confirmar=nao
    )

    assert resultado.status == "ok" and not perguntas
    assert janelas.fechadas == [_id(2)] and resultado.dados["fechada"] is True


def test_executor_encerra_o_discord_e_avisa_em_voz(executor: ExecutorDeFerramentas) -> None:
    tabela, _janelas = _ligar(executor)

    resultado = executor.executar("apps.quit", {"app": "Discord"}, cancelado=lambda: False)

    assert resultado.status == "ok", resultado.motivo
    assert resultado.aviso == "Encerrei o Discord."
    assert tabela.sinais == [(700, signal.SIGTERM)]


def test_executor_pergunta_antes_de_encerrar_o_editor(executor: ExecutorDeFerramentas) -> None:
    tabela, janelas = _ligar(executor)
    janelas.janelas = [
        replace(j, titulo="notas.md * — Kate") if j.classe == "org.kde.kate" else j
        for j in janelas.janelas
    ]
    perguntas: list[Confirmacao] = []

    def nao(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return False

    negado = executor.executar("apps.quit", {"app": "Kate"}, cancelado=lambda: False, confirmar=nao)

    assert negado.status == "negado" and not tabela.sinais, "sem o sim, nada recebe sinal"
    assert perguntas and "trabalho por salvar" in perguntas[0].razao_falada
    assert "encerrar o «Kate»" in perguntas[0].pergunta_falada

    sim = executor.executar(
        "apps.quit", {"app": "Kate"}, cancelado=lambda: False, confirmar=lambda _p: True
    )
    assert sim.status == "ok" and (900, signal.SIGTERM) in tabela.sinais


def test_executor_recusa_o_protegido_sem_chegar_ao_pdp(executor: ExecutorDeFerramentas) -> None:
    tabela, _janelas = _ligar(executor)
    resultado = executor.executar("apps.quit", {"app": "Konsole"}, cancelado=lambda: False)
    assert resultado.status == "negado" and resultado.causa == "alvo_protegido"
    assert not tabela.sinais


# --- processos de verdade, criados pelo teste -----------------------------------------------
so_no_linux = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="lê o /proc e manda sinal por PID (Linux)"
)


def _descartavel(pasta: Path, nome: str, programa: str, *args: str) -> subprocess.Popen[bytes]:
    """Um programa do sistema copiado com nome único, aberto numa sessão nova (como o Jarvis abre
    os apps): o executável dele não casa com nada do dono."""
    origem = shutil.which(programa)
    assert origem is not None, f"{programa} não está no PATH"
    copia = pasta / nome
    shutil.copy2(origem, copia)
    return subprocess.Popen(
        [str(copia), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _fechador_de_verdade(nome: str, exe: str, pasta: Path) -> Fechador:
    app = App(
        id=f"teste.{exe}",
        nome=nome,
        nomes=(nome,),
        argv=(str(pasta / exe),),
        arquivo=pasta / f"{exe}.desktop",
        exec_nome=exe,
    )
    return Fechador(
        janelas=None, tabela=TabelaDoProc(), catalogo={app.id: app}, prazo_do_term_s=1.0
    )


def _esperar_aparecer(pid: int) -> None:
    fim = time.monotonic() + 5.0
    while time.monotonic() < fim:
        if TabelaDoProc().ler(pid) is not None:
            return
        time.sleep(0.02)


@so_no_linux
def test_encerra_de_verdade_um_processo_descartavel(tmp_path: Path) -> None:
    processo = _descartavel(tmp_path, "jarvis-teste-dorminhoco", "sleep", "60")
    try:
        _esperar_aparecer(processo.pid)
        fechador = _fechador_de_verdade("Dorminhoco de Teste", "jarvis-teste-dorminhoco", tmp_path)

        alvo = fechador.app("Dorminhoco de Teste")
        assert [p.pid for p in alvo.raizes] == [processo.pid]
        dados = fechador.encerrar_app(alvo)

        assert processo.wait(timeout=5) == -signal.SIGTERM, "saiu pelo SIGTERM"
        assert dados["conferido"] is True and dados["sigkill"] == 0
    finally:
        if processo.poll() is None:
            processo.kill()  # o processo é do teste: o Popen dele, pelo PID dele
            processo.wait(timeout=5)


@so_no_linux
def test_o_teimoso_de_verdade_leva_sigkill_depois_do_prazo(tmp_path: Path) -> None:
    roteiro = "trap '' TERM; while :; do sleep 0.2; done"
    processo = _descartavel(tmp_path, "jarvis-teste-teimoso", "bash", "-c", roteiro)
    try:
        _esperar_aparecer(processo.pid)
        time.sleep(0.2)  # o trap já armado
        fechador = _fechador_de_verdade("Teimoso de Teste", "jarvis-teste-teimoso", tmp_path)

        comeco = time.monotonic()
        dados = fechador.encerrar_app(fechador.app("Teimoso de Teste"))

        assert processo.wait(timeout=5) == -signal.SIGKILL, "só o SIGKILL o levou"
        assert time.monotonic() - comeco >= fechador.prazo_do_term_s
        assert dados["sigterm"] == 1 and dados["sigkill"] >= 1 and dados["conferido"] is True
    finally:
        if processo.poll() is None:
            processo.kill()
            processo.wait(timeout=5)


@so_no_linux
def test_o_proprio_processo_e_quem_o_abriu_nunca_sao_alvo() -> None:
    """Quem roda o Fechador (aqui, o pytest) é o "Jarvis": ele e quem o abriu nunca recebem sinal,
    pela identidade lida do /proc de verdade."""
    tabela = TabelaDoProc()
    jarvis = Jarvis.deste_processo(tabela)
    eu = tabela.ler(os.getpid())
    pai = tabela.ler(os.getppid())
    assert eu is not None and pai is not None
    assert jarvis.pid == os.getpid() and jarvis.uid == os.getuid()
    assert "próprio Jarvis" in protecao(eu, jarvis, frozenset())
    assert pai.pid in jarvis.ancestrais
    assert "rodando dentro dele" in protecao(pai, jarvis, frozenset()) or pai.uid != jarvis.uid
    um = tabela.ler(1)
    if um is not None:
        assert protecao(um, jarvis, frozenset())
