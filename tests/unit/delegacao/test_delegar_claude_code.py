"""Delegar ao Claude Code (ADR-0054), sempre com um `claude` FALSO (`claude_falso.py`): o Claude
Code de verdade e o navegador do dono nunca são chamados aqui.

Cobre: a chave desligada por padrão; o argv fixo e documentado (sem bypass, sem tool embutida,
a tarefa pela entrada padrão e nunca na linha de comando); o ambiente mínimo (nenhuma chave do
Jarvis passa); a pasta de trabalho temporária; prazo, cancelamento e saída cortada; a degradação
clara (sem `claude`, sem login, login por chave, sem a integração do Chrome); e a ligação com o
executor, o PDP e o guarda — o sim na 1ª vez, a frase do que vai ser delegado, a recusa de
re-delegar, o resultado como dado (turno contaminado) e a trilha só com códigos.
"""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import RespostaEscolha
from jarvis.delegacao import (
    Codigo,
    ConfiguracaoDaDelegacao,
    ConfiguracaoDaDelegacaoInvalida,
    DelegadorClaudeCode,
    carregar_delegacao,
)
from jarvis.delegacao.claude_code import (
    FERRAMENTAS_DO_CHROME,
    HOST_NATIVO,
    PROIBIDOS_NO_ARGV,
    ambiente_minimo,
)
from jarvis.executor.ferramentas import (
    FERRAMENTA_DE_DELEGAR,
    Avaliacao,
    Confirmacao,
    ExecutorDeFerramentas,
)
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.guarda import Acao, GuardaDeContexto, Saida, Tipo
from jarvis.politica.modos import Modo
from jarvis.politica.objetivo import Objetivo
from jarvis.politica.pdp import Pdp, Veredito
from jarvis.trilha import TrilhaDeDiagnostico

NUNCA = lambda: False  # noqa: E731
FALSO = Path(__file__).with_name("claude_falso.py")
TAREFA = "abra a página de horários da clinica.example e traga o horário de amanhã"
AMBIENTE_DO_JARVIS = {
    "HOME": "/casa/do/dono",
    "USER": "dono",
    "LANG": "pt_BR.UTF-8",
    "PATH": "/usr/bin:/bin",
    "XDG_RUNTIME_DIR": "/run/user/1000",
    "ANTHROPIC_API_KEY": "sk-ant-nao-pode-passar",
    "OPENROUTER_API_KEY": "sk-or-nao-pode-passar",
    "JARVIS_JEV_CHAVE": "nao-pode-passar",
    "GITHUB_TOKEN": "ghp_nao_pode_passar",
}


def _claude_falso(pasta: Path, modo: str = "ok") -> Path:
    """Copia o `claude` falso para `pasta`, executável, com o modo de resposta ao lado."""
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / "claude"
    alvo.write_text(f"#!{sys.executable} -I\n" + FALSO.read_text(encoding="utf-8"), "utf-8")
    alvo.chmod(alvo.stat().st_mode | stat.S_IXUSR)
    (pasta / "modo.txt").write_text(modo, encoding="utf-8")
    return alvo


def _casa_com_chrome(raiz: Path) -> Path:
    casa = raiz / "casa"
    host = casa / ".config" / "google-chrome" / "NativeMessagingHosts"
    host.mkdir(parents=True)
    (host / HOST_NATIVO).write_text("{}", encoding="utf-8")
    return casa


def _registros(pasta: Path) -> list[dict[str, Any]]:
    arquivos = sorted(pasta.glob("registro-*.json"), key=lambda p: int(p.stem.split("-")[1]))
    return [json.loads(a.read_text(encoding="utf-8")) for a in arquivos]


def _delegador(
    tmp_path: Path, modo: str = "ok", *, prazo_s: float = 30.0, chrome: bool = True
) -> tuple[DelegadorClaudeCode, Path, list[str]]:
    executavel = _claude_falso(tmp_path / "bin", modo)
    casa = _casa_com_chrome(tmp_path) if chrome else tmp_path / "casa-sem-chrome"
    ditos: list[str] = []
    delegador = DelegadorClaudeCode(
        configuracao=ConfiguracaoDaDelegacao(
            ligado=True, executavel=str(executavel), prazo_s=prazo_s
        ),
        ambiente=AMBIENTE_DO_JARVIS,
        lar=casa,
        avisar=ditos.append,
    )
    return delegador, executavel.parent, ditos


# --- a chave na configuração do dono ------------------------------------------------------


def test_sem_arquivo_a_delegacao_fica_desligada(tmp_path: Path) -> None:
    assert carregar_delegacao(tmp_path / "delegar.toml").ligado is False


def test_le_a_chave_e_aperta_os_limites(tmp_path: Path) -> None:
    alvo = tmp_path / "delegar.toml"
    alvo.write_text(
        '[claude_code]\nligado = true\nprazo_s = 99999\nmax_turnos = 0\nmodelo = "sonnet"\n',
        encoding="utf-8",
    )
    config = carregar_delegacao(alvo)
    assert config.ligado is True and config.executavel == "claude"
    assert config.prazo_s == 600.0  # o teto do manifesto
    assert config.max_turnos == 1
    assert config.modelo == "sonnet"
    assert config.delegacoes_por_objetivo == 10  # o padrão (emenda de 2026-10-29)


def test_o_teto_de_delegacoes_por_objetivo_vem_da_configuracao_e_tem_limite(
    tmp_path: Path,
) -> None:
    alvo = tmp_path / "delegar.toml"
    for valor, esperado in ((4, 4), (0, 1), (999, 50)):
        alvo.write_text(
            f"[claude_code]\nligado = true\ndelegacoes_por_objetivo = {valor}\n", encoding="utf-8"
        )
        assert carregar_delegacao(alvo).delegacoes_por_objetivo == esperado
    alvo.write_text('[claude_code]\ndelegacoes_por_objetivo = "dez"\n', encoding="utf-8")
    with pytest.raises(ConfiguracaoDaDelegacaoInvalida):
        carregar_delegacao(alvo)


@pytest.mark.parametrize(
    "texto",
    [
        '[claude_code]\nligado = true\napi_key = "sk-abc12345"\n',  # cara de segredo
        "[claude_code]\nligado = true\nbypass = true\n",  # chave desconhecida
        '[claude_code]\nexecutavel = "claude --dangerously-skip-permissions"\n',  # argumento junto
        '[claude_code]\nligado = "sim"\n',
    ],
)
def test_configuracao_fora_do_contrato_e_recusada(tmp_path: Path, texto: str) -> None:
    alvo = tmp_path / "delegar.toml"
    alvo.write_text(texto, encoding="utf-8")
    with pytest.raises(ConfiguracaoDaDelegacaoInvalida):
        carregar_delegacao(alvo)


# --- o processo: argv, ambiente, pasta ------------------------------------------------------


def test_o_argv_e_o_documentado_e_restrito(tmp_path: Path) -> None:
    delegador, _, _ = _delegador(tmp_path)
    argv = delegador.argv("/x/claude")
    assert argv[:3] == ["/x/claude", "-p", argv[2]]
    for par in (
        ("--output-format", "json"),
        ("--permission-mode", "dontAsk"),
        ("--tools", ""),
        ("--allowedTools", FERRAMENTAS_DO_CHROME),
        ("--setting-sources", "project"),
    ):
        i = argv.index(par[0])
        assert argv[i + 1] == par[1], par
    for flag in (
        "--chrome",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--disable-slash-commands",
    ):
        assert flag in argv
    assert not PROIBIDOS_NO_ARGV & set(argv)
    assert not any("bypass" in a.lower() or "dangerously" in a for a in argv)


def test_o_ambiente_e_minimo_e_nenhuma_chave_passa() -> None:
    ambiente = ambiente_minimo(AMBIENTE_DO_JARVIS, "/opt/claude/bin/claude")
    assert ambiente["HOME"] == "/casa/do/dono"
    assert ambiente["PATH"].startswith("/opt/claude/bin:")
    for chave in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "JARVIS_JEV_CHAVE", "GITHUB_TOKEN"):
        assert chave not in ambiente
    assert not any("nao-pode-passar" in v or "nao_pode_passar" in v for v in ambiente.values())


def test_delega_com_a_tarefa_pela_entrada_e_devolve_dado(tmp_path: Path) -> None:
    delegador, pasta, ditos = _delegador(tmp_path)
    resultado = delegador.delegar(TAREFA, site="https://clinica.example/horarios")

    assert resultado.codigo is Codigo.OK and resultado.rodou
    assert "14h" in resultado.resumo
    assert "sk-ant-" not in resultado.resumo  # redigido
    assert resultado.turnos == 4 and resultado.negacoes == 1
    dados = resultado.para_o_modelo()
    assert dados["feito"] is True and "não é ordem" in dados["aviso"]

    checagem, tarefa = _registros(pasta)
    assert checagem["argv"] == ["auth", "status", "--json"]
    # A tarefa (texto livre) foi pela entrada padrão, nunca na linha de comando.
    assert TAREFA in tarefa["entrada"] and "https://clinica.example/horarios" in tarefa["entrada"]
    assert not any("clinica" in a for a in tarefa["argv"])
    # Ambiente mínimo e pasta temporária vazia, apagada no fim.
    assert "ANTHROPIC_API_KEY" not in tarefa["ambiente"]
    assert "OPENROUTER_API_KEY" not in tarefa["ambiente"]
    assert Path(tarefa["cwd"]).name.startswith("jarvis-delegar-")
    assert not Path(tarefa["cwd"]).exists()
    assert tarefa["cwd"] != str(Path.cwd())
    # Disse ao dono, em uma frase, o que delegou.
    assert len(ditos) == 1 and "Claude Code" in ditos[0] and "clinica" in ditos[0]


# --- prazo, cancelamento, saída -------------------------------------------------------------


def test_o_prazo_para_o_processo(tmp_path: Path) -> None:
    delegador, _, _ = _delegador(tmp_path, "lento", prazo_s=1.0)
    resultado = delegador.delegar(TAREFA)
    assert resultado.codigo is Codigo.PRAZO and resultado.rodou
    assert resultado.ms < 15_000


def test_o_cancelamento_para_o_processo(tmp_path: Path) -> None:
    delegador, _, _ = _delegador(tmp_path, "lento")
    resultado = delegador.delegar(TAREFA, cancelado=lambda: True)
    assert resultado.codigo is Codigo.INTERROMPIDO


def test_saida_enorme_e_cortada_e_lixo_e_saida_invalida(tmp_path: Path) -> None:
    enorme, _, _ = _delegador(tmp_path / "a", "enorme")
    resultado = enorme.delegar(TAREFA)
    assert resultado.saida_cortada and resultado.codigo is Codigo.SAIDA_INVALIDA
    lixo, _, _ = _delegador(tmp_path / "b", "lixo")
    assert lixo.delegar(TAREFA).codigo is Codigo.SAIDA_INVALIDA


def test_erro_do_claude_code_volta_como_falha(tmp_path: Path) -> None:
    delegador, _, _ = _delegador(tmp_path, "erro")
    resultado = delegador.delegar(TAREFA)
    assert resultado.codigo is Codigo.FALHOU and "error_max_turns" in resultado.mensagem()


# --- a degradação clara ---------------------------------------------------------------------


def test_sem_o_claude_diz_o_que_falta(tmp_path: Path) -> None:
    delegador = DelegadorClaudeCode(
        configuracao=ConfiguracaoDaDelegacao(
            ligado=True, executavel=str(tmp_path / "nao-existe" / "claude")
        ),
        ambiente=AMBIENTE_DO_JARVIS,
        lar=_casa_com_chrome(tmp_path),
    )
    resultado = delegador.delegar(TAREFA)
    assert resultado.codigo is Codigo.SEM_CLAUDE and not resultado.rodou
    assert "não está instalado" in resultado.mensagem()


@pytest.mark.parametrize("modo", ["sem_login", "chave_api"])
def test_sem_login_da_conta_diz_o_que_falta(tmp_path: Path, modo: str) -> None:
    delegador, pasta, _ = _delegador(tmp_path, modo)
    resultado = delegador.delegar(TAREFA)
    assert resultado.codigo is Codigo.SEM_LOGIN and not resultado.rodou
    assert "claude auth login" in resultado.mensagem()
    assert len(_registros(pasta)) == 1  # só a checagem: a tarefa nunca subiu


def test_sem_a_integracao_do_chrome_diz_o_que_falta(tmp_path: Path) -> None:
    delegador, pasta, _ = _delegador(tmp_path, chrome=False)
    resultado = delegador.delegar(TAREFA)
    assert resultado.codigo is Codigo.SEM_CHROME and not resultado.rodou
    assert "Claude in Chrome" in resultado.mensagem()
    assert len(_registros(pasta)) == 1


# --- o guarda de contexto (D) ---------------------------------------------------------------


def _jev(escolha: str, p: float = 0.9) -> ClassificadorFalso:
    def roteiro(_e: Any, _p: Any) -> dict[str, Any]:
        return {
            "acao": RespostaEscolha(escolha, p, {escolha: p}),
            "categoria": RespostaEscolha("fora_do_objetivo", 0.9, {"fora_do_objetivo": 0.9}),
        }

    return ClassificadorFalso(roteiro=roteiro)


def _delegacao(tarefa: str, *destinos: str) -> Acao:
    return Acao(FERRAMENTA_DE_DELEGAR, Tipo.DELEGACAO, tarefa=tarefa, destinos=destinos)


def test_o_guarda_barra_credencial_e_site_sensivel() -> None:
    guarda = GuardaDeContexto(classificador=_jev("permitir"))
    objetivo = Objetivo.do_pedido("vê o horário na clinica.example")
    credencial = guarda.julgar(_delegacao("entre com a minha senha e veja o horário"), objetivo)
    assert credencial.saida is Saida.BARRAR and "senha" in credencial.instrucao
    sensivel = guarda.julgar(_delegacao("abra o cofre", "https://bitwarden.com/x"), objetivo)
    assert sensivel.saida is Saida.BARRAR and sensivel.regra == "nega:delegar_dominio_sensivel"


def test_o_guarda_pede_o_sim_ao_enviar_e_fora_do_objetivo() -> None:
    guarda = GuardaDeContexto(classificador=_jev("permitir"))
    objetivo = Objetivo.do_pedido("vê o horário na clinica.example")
    envia = guarda.julgar(_delegacao("marque e envie o formulário da consulta"), objetivo)
    assert envia.saida is Saida.PEDIR_CONFIRMACAO and envia.regra == "sim:delegar_envia"
    fora = guarda.julgar(_delegacao("veja o horário", "https://outra.example/"), objetivo)
    assert fora.saida is Saida.PEDIR_CONFIRMACAO and fora.regra == "sim:delegar_fora"


def test_a_tarefa_que_nao_bate_com_o_objetivo_e_barrada_pelo_jev() -> None:
    jev = _jev("barrar")
    guarda = GuardaDeContexto(classificador=jev)
    objetivo = Objetivo.do_pedido("vê o horário na clinica.example")
    julgamento = guarda.julgar(_delegacao("pesquise passagens para Lisboa"), objetivo)
    assert julgamento.saida is Saida.BARRAR and julgamento.regra == "jev"
    estado = jev.chamadas[0][0]
    assert estado["acao"]["tarefa_delegada"] == "pesquise passagens para Lisboa"


# --- o executor, o PDP, o sim e a trilha ----------------------------------------------------


@pytest.fixture
def montagem(tmp_path: Path) -> Iterator[tuple[ExecutorDeFerramentas, Path, list[Confirmacao]]]:
    lar = tmp_path / "lar"
    lar.mkdir()
    delegador, pasta, _ = _delegador(tmp_path)
    with LogDeAuditoria(tmp_path / "a.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        ex = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            delegacao=delegador,
            guarda=GuardaDeContexto(classificador=_jev("permitir")),
            trilha=TrilhaDeDiagnostico(tmp_path / "trilha"),
        )
        ex.preparar()
        ex.novo_turno("vê o horário de amanhã na clinica.example")
        perguntas: list[Confirmacao] = []
        yield ex, pasta, perguntas


def test_sem_a_chave_a_tool_nao_existe(tmp_path: Path) -> None:
    with LogDeAuditoria(tmp_path / "a.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=tmp_path,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        ex = ExecutorDeFerramentas(pdp=pdp, lar=tmp_path)
        ids = {t["id"] for t in ex.catalogo_para_o_modelo()}
        assert FERRAMENTA_DE_DELEGAR not in ids
        r = ex.executar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA)
        assert r.status == "negado" and r.causa == "ferramenta_desligada"


def test_pede_o_sim_dizendo_o_que_vai_delegar_e_o_resultado_e_dado(
    montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]],
) -> None:
    ex, pasta, perguntas = montagem
    assert FERRAMENTA_DE_DELEGAR in {t["id"] for t in ex.catalogo_para_o_modelo()}

    avaliacao = ex.avaliar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA})
    assert isinstance(avaliacao, Avaliacao)
    assert avaliacao.decisao.veredito is Veredito.CONFIRM  # moderado, mas a 1ª vez pergunta

    # O dono diz não: nada roda, e o `claude` falso nem é chamado.
    negado = ex.executar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA)
    assert negado.status == "negado" and _registros(pasta) == []

    def sim(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return True

    r = ex.executar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=sim)
    assert r.status == "ok", r
    assert r.dados["feito"] is True and "14h" in r.dados["resultado_do_claude_code"]
    assert r.aviso == "O Claude Code terminou a tarefa no navegador."
    # A pergunta diz em uma frase o que vai ser delegado, e o custo.
    (pergunta,) = perguntas
    assert pergunta.detalhe.startswith("pedir ao Claude Code") and "clinica.example" in (
        pergunta.detalhe
    )
    assert "cota" in pergunta.razao_falada
    # O resultado é dado de terceiros: o turno fica contaminado.
    assert ex.contaminado is True
    assert ex.objetivo is not None and ex.objetivo.delegacoes == 1


def test_varias_delegacoes_no_mesmo_objetivo_com_um_sim_so(
    montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]],
) -> None:
    """Dono, 2026-10-29: várias etapas da mesma tarefa (um mapa mental com várias pesquisas) — o sim
    da primeira vale para a delegação inteira: as seguintes do mesmo objetivo não perguntam."""
    ex, pasta, perguntas = montagem

    def anota(resposta: bool) -> Callable[[Confirmacao], bool]:
        def confirmar(pergunta: Confirmacao) -> bool:
            perguntas.append(pergunta)
            return resposta

        return confirmar

    primeira = ex.executar(
        FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=anota(True)
    )
    assert primeira.status == "ok" and len(perguntas) == 1
    for etapa in ("confira também o horário de sábado", "veja se há encaixe na sexta"):
        seguinte = ex.executar(
            FERRAMENTA_DE_DELEGAR,
            {"tarefa": f"{etapa} na clinica.example"},
            cancelado=NUNCA,
            confirmar=anota(False),  # se perguntasse, o "não" a barraria
        )
        assert seguinte.status == "ok", seguinte
    assert len(perguntas) == 1, "a delegação inteira pediu o sim mais de uma vez"
    assert ex.objetivo is not None and ex.objetivo.delegacoes == 3
    assert len(_registros(pasta)) == 6  # cada delegação: a checagem e a tarefa


def test_o_teto_por_objetivo_recusa_a_proxima(
    montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]],
) -> None:
    ex, pasta, _ = montagem
    assert ex.delegacao is not None
    ex.delegacao.configuracao = replace(ex.delegacao.configuracao, delegacoes_por_objetivo=2)
    for _ in range(2):
        feita = ex.executar(
            FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=lambda _p: True
        )
        assert feita.status == "ok"
    terceira = ex.executar(
        FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=lambda _p: True
    )
    assert terceira.status == "negado" and terceira.causa == "delegacoes_no_teto"
    assert (
        len(_registros(pasta)) == 4
    )  # duas delegações (checagem e tarefa); a terceira nunca subiu


def test_fora_do_eixo_o_guarda_pede_o_sim_de_novo_e_objetivo_novo_aprova_de_novo(
    montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]],
) -> None:
    ex, _pasta, perguntas = montagem

    def sim(pergunta: Confirmacao) -> bool:
        perguntas.append(pergunta)
        return True

    primeira = ex.executar(
        FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=sim
    )
    assert primeira.status == "ok"
    assert len(perguntas) == 1
    # A delegação que envia (fora do eixo de ver um horário) volta a pedir o sim — o guarda D.
    envio = ex.executar(
        FERRAMENTA_DE_DELEGAR,
        {"tarefa": "envie uma mensagem para a clínica confirmando a consulta"},
        cancelado=NUNCA,
        confirmar=sim,
    )
    assert envio.status == "ok" and len(perguntas) == 2, "fora do eixo, não pediu o sim de novo"
    # Outro pedido do dono é outro objetivo: aprova de novo.
    ex.novo_turno("vê o preço do exame na clinica.example")
    ex.executar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=sim)
    assert len(perguntas) == 3


def test_com_a_extensao_ligada_tenta_antes_pelo_navegador(
    montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]],
) -> None:
    ex, _, _ = montagem
    ex.navegador = cast(Any, object())  # a extensão do Jarvis ligada (só a presença importa aqui)
    cedo = ex.executar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA)
    assert cedo.status == "negado" and cedo.causa == "delegar_cedo"
    assert ex.objetivo is not None
    ex.objetivo.registrar("browser.click", "erro", leitura=False)  # tentou e não deu
    depois = ex.avaliar(FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA})
    assert isinstance(depois, Avaliacao) and depois.decisao.veredito is Veredito.CONFIRM


def test_a_degradacao_volta_ao_modelo_com_a_mensagem_e_o_codigo(
    tmp_path: Path, montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]]
) -> None:
    ex, _, _ = montagem
    assert ex.delegacao is not None
    ex.delegacao.lar = tmp_path / "sem-chrome"
    r = ex.executar(
        FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=lambda _p: True
    )
    assert r.status == "erro" and r.causa == "claude_code_sem_chrome"
    assert "Claude in Chrome" in r.motivo
    assert ex.objetivo is not None and ex.objetivo.delegacoes == 0  # não rodou: não conta


def test_a_trilha_so_tem_codigos(
    tmp_path: Path, montagem: tuple[ExecutorDeFerramentas, Path, list[Confirmacao]]
) -> None:
    ex, _, _ = montagem
    ex.executar(
        FERRAMENTA_DE_DELEGAR, {"tarefa": TAREFA}, cancelado=NUNCA, confirmar=lambda _p: True
    )
    assert ex.trilha is not None
    texto = ex.trilha.arquivo.read_text(encoding="utf-8")
    eventos = [json.loads(linha) for linha in texto.splitlines()]
    (delegacao,) = [e for e in eventos if e.get("evento") == "delegacao"]
    assert delegacao["status"] == "ok" and delegacao["turnos"] == 4
    assert "clinica" not in texto and "14h" not in texto  # nem a tarefa nem o resultado
