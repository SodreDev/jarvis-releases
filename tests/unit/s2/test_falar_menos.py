"""Falar menos (dono, 2026-10-21; emenda à ADR-0031): a voz cabe num orçamento, a tela recebe tudo.

O teto é verificável: no máximo quatro frases (e 60 palavras) vão para o TTS — três da resposta e o
fecho «O resto está na tela.» quando ela passa disso —, a menos que o dono peça detalhe. Vale para a
resposta do turno e para a resposta de uma tarefa (ADR-0038), e nunca para uma pergunta.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.orcamento_da_fala import (
    FECHO,
    FRASES_NA_VOZ,
    PALAVRAS_NA_VOZ,
    OrcamentoDaFala,
    orcar,
    quer_detalhe,
)
from jarvis.s2.persona import prompt_de_sistema
from jarvis.tarefas.gestor import EstadoDaTarefa, Tarefa
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

SEIS = (
    "Abri o Spotify e toquei a playlist de rock. O volume ficou em quarenta por cento. "
    "A próxima música é do Queen. Também achei um podcast novo de tecnologia. "
    "Ele tem doze episódios. O mais recente saiu ontem."
)
TRES_PRIMEIRAS = (
    "Abri o Spotify e toquei a playlist de rock. O volume ficou em quarenta por cento. "
    "A próxima música é do Queen."
)


def _frases(texto: str) -> int:
    return len([f for f in re.split(r"(?<=[.!?…])\s+", texto.strip()) if f])


# --- o orçamento -------------------------------------------------------------------------------
def test_ate_quatro_frases_vai_tudo_para_a_voz() -> None:
    quatro = "Abri o app. Toquei a música. O volume está bom. Mais alguma coisa?"
    assert orcar(quatro) == (quatro, "")
    assert orcar("Pronto.") == ("Pronto.", "")


def test_mais_de_quatro_a_voz_diz_tres_e_o_fecho_e_o_resto_fica_na_tela() -> None:
    falado, na_tela = orcar(SEIS)

    assert falado == f"{TRES_PRIMEIRAS} {FECHO}"
    assert _frases(falado) == FRASES_NA_VOZ, "o teto é quatro frases na voz, com o fecho"
    assert na_tela.startswith("Também achei um podcast") and na_tela.endswith("saiu ontem.")


@pytest.mark.parametrize("tamanho", [1, 2, 3, 7])
def test_em_stream_o_resultado_e_o_mesmo_de_uma_vez(tamanho: int) -> None:
    orcamento = OrcamentoDaFala()
    falado = "".join(orcamento.passar(SEIS[i : i + tamanho]) for i in range(0, len(SEIS), tamanho))
    falado += orcamento.fechar()

    assert " ".join(falado.split()) == orcar(SEIS)[0]
    assert orcamento.cortou and orcamento.so_na_tela == orcar(SEIS)[1]


def test_a_quarta_frase_espera_saber_se_vem_uma_quinta() -> None:
    orcamento = OrcamentoDaFala()
    dito = orcamento.passar("Um. Dois. Três. Quatro. ")
    assert "Quatro" not in dito, "a quarta saiu antes de saber se vinha a quinta"
    assert " ".join((dito + orcamento.fechar()).split()) == "Um. Dois. Três. Quatro."


def test_uma_frase_comprida_demais_e_cortada_na_virgula_dentro_do_teto() -> None:
    palavras = [f"item{i}" + ("," if i % 10 == 9 else "") for i in range(100)]
    falado, na_tela = orcar(" ".join(palavras) + ".")

    ditas = falado.removesuffix(FECHO).split()
    assert len(ditas) <= PALAVRAS_NA_VOZ
    assert falado.endswith(f"item59… {FECHO}")
    assert na_tela.startswith("item60")


def test_abreviacao_inicial_e_decimal_nao_fecham_frase() -> None:
    texto = "O Sr. Silva chegou às 3.5 horas. Ele trouxe o livro do J. R. R. Tolkien. Fim."
    assert orcar(texto) == (texto, "")


def test_linhas_de_uma_lista_contam_como_frases() -> None:
    lista = "Achei:\num\ndois\ntrês\nquatro\ncinco"
    falado, na_tela = orcar(lista)
    assert falado == f"Achei: um dois {FECHO}"
    assert na_tela == "três quatro cinco"


def test_com_o_dono_pedindo_detalhe_nao_ha_teto() -> None:
    assert orcar(SEIS, livre=True) == (SEIS, "")


@pytest.mark.parametrize(
    ("fala", "detalhe"),
    [
        ("me explica o que aconteceu", True),
        ("detalha o que você achou", True),
        ("o que você fez?", True),
        ("lê pra mim o artigo", True),
        ("me diz passo a passo", True),
        ("me conta uma história", True),
        ("conte uma história comprida", True),
        ("abre o spotify e toca rock", False),
        ("que horas são?", False),
        ("fecha o discord inteiro", False),
    ],
)
def test_quando_o_dono_pede_detalhe(fala: str, detalhe: bool) -> None:
    assert quer_detalhe(fala) is detalhe


# --- no cérebro --------------------------------------------------------------------------------
def _responder(
    texto_do_dono: str, roteiro: str
) -> tuple[Cerebro, list[dict[str, Any]], list[str], Any]:
    cerebro = Cerebro(motor=MotorRoteirizado(resposta=roteiro))
    publicados: list[dict[str, Any]] = []
    telas: list[str] = []
    resposta = cerebro.responder(
        texto_do_dono, epoch=1, publicar=publicados.append, mostrar=telas.append
    )
    return cerebro, publicados, telas, resposta


def _voz(publicados: list[dict[str, Any]]) -> str:
    return " ".join(" ".join(str(p["text"]) for p in publicados).split())


def test_o_cerebro_fala_o_que_cabe_e_mostra_tudo() -> None:
    cerebro, publicados, telas, resposta = _responder("e aí, o que rolou?", SEIS)

    assert _voz(publicados) == f"{TRES_PRIMEIRAS} {FECHO}"
    assert telas[-1] == " ".join(SEIS.split()), "a tela tem de mostrar a resposta inteira"
    assert resposta.so_na_tela.startswith("Também achei")
    assert publicados[-1]["last"] is True

    cerebro.ouvido(resposta.response_id, _voz(publicados), interrompida=False)
    lembrado = cerebro.conversa.turnos[-1].texto
    assert lembrado.startswith(TRES_PRIMEIRAS) and "só na tela" in lembrado
    assert "Também achei um podcast" in lembrado, "o modelo tem de saber o que o dono viu"


def test_interrompido_o_que_ficou_na_tela_nao_entra_como_dito() -> None:
    cerebro, _publicados, _telas, resposta = _responder("e aí?", SEIS)
    cerebro.ouvido(resposta.response_id, "Abri o Spotify", interrompida=True)
    assert cerebro.conversa.turnos[-1].texto == "Abri o Spotify"


def test_pedindo_detalhe_o_cerebro_fala_a_resposta_inteira() -> None:
    _cerebro, publicados, _telas, resposta = _responder("me explica em detalhes", SEIS)
    assert _voz(publicados) == " ".join(SEIS.split())
    assert resposta.so_na_tela == ""


def test_a_persona_pede_o_resumo_curto_da_execucao() -> None:
    persona = prompt_de_sistema()  # v15 (ADR-0047): a seção VOZ E TELA
    assert "três ou quatro frases no máximo" in persona
    assert "o resto aparece na tela" in persona
    assert "Detalhe só quando ele pedir" in persona


# --- a resposta de uma tarefa (ADR-0038) ---------------------------------------------------------
def _app(tmp_path: Path, linhas: list[str]) -> Aplicativo:
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=linhas.append,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=tmp_path,
    )
    app.abrir(com_asr=False)
    app.avisos.piso_livre_s = 0.0
    return app


def _tarefa(descricao: str, resposta: str) -> Tarefa:
    return Tarefa(
        id="t1",
        descricao=descricao,
        tool_id="apps.launch",
        parametros={},
        motor="objetivo",
        estado=EstadoDaTarefa.CONCLUIDA,
        de_objetivo=True,
        resposta=resposta,
    )


def _falar_a_resposta(app: Aplicativo, tarefa: Tarefa) -> Callable[[], str]:
    app._tarefa_concluida(tarefa)
    assert app.entregar_avisos(None), "a resposta da tarefa não foi à voz"
    assert app._cerebro is not None
    return lambda: app._cerebro.conversa.turnos[-1].texto if app._cerebro else ""


def test_a_resposta_de_uma_tarefa_fala_o_resumo_e_mostra_tudo(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)

    lembrado = _falar_a_resposta(app, _tarefa("abre o spotify e toca rock", SEIS))

    assert f"Jarvis: {' '.join(SEIS.split())}" in linhas, "a tela tem a resposta inteira"
    texto = lembrado()
    assert texto.startswith(f"{TRES_PRIMEIRAS} {FECHO}"), texto
    assert "só na tela" in texto


def test_a_resposta_de_uma_tarefa_pedida_em_detalhe_vai_inteira_para_a_voz(
    tmp_path: Path,
) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)

    lembrado = _falar_a_resposta(app, _tarefa("me explica o que tem no spotify", SEIS))

    assert lembrado() == " ".join(SEIS.split())


def test_a_pergunta_de_uma_tarefa_nunca_e_cortada(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)
    pergunta = (
        "Preciso do seu sim para encerrar o Steam. Ele tem um jogo aberto. O jogo pode perder o "
        "progresso. A biblioteca também fecha. As downloads param. Posso?"
    )
    app._aviso_da_tarefa(_tarefa("x", ""), "pergunta-p1", "precisa_decisao", pergunta)

    assert app._falas_dos_avisos["pergunta-p1"] == pergunta
