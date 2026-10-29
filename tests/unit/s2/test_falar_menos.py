"""Falar curto do jeito certo (dono, 2026-10-21; emenda de 2026-10-29 à ADR-0031).

Quem faz a resposta curta é a persona; o código não conta frases. Só um teto **alto** de segurança
(`PALAVRAS_NA_VOZ`, ~45 s de fala) segura o monólogo quando o modelo não obedece: passou dele, a voz
para numa frase inteira e **pergunta** se monta o resto na tela. Sem teto quando o dono pede
detalhe. Vale para a resposta do turno e para a de uma tarefa (ADR-0038), e nunca para uma pergunta.
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
"""Seis frases curtas (~40 palavras): antes eram cortadas em quatro; agora vão inteiras."""
FRASE = "Esta é uma frase de exemplo com quinze palavras para encher o monólogo do modelo agora."
MONOLOGO = " ".join(f"{FRASE[:-1]} número {i}." for i in range(12))
"""Doze frases de 18 palavras (216): o modelo que ignorou a persona e engatou um monólogo."""
POR_FRASE = len(f"{FRASE[:-1]} número 0.".split())
CABEM = " ".join(f"{FRASE[:-1]} número {i}." for i in range(PALAVRAS_NA_VOZ // POR_FRASE))


def _frases(texto: str) -> int:
    return len([f for f in re.split(r"(?<=[.!?…])\s+", texto.strip()) if f])


# --- o orçamento -------------------------------------------------------------------------------
def test_resposta_curta_ou_de_varias_frases_vai_inteira_para_a_voz() -> None:
    """O corte mecânico de quatro frases saiu (dono, 2026-10-29: «corta coisas que não
    precisavam»): seis frases curtas vão inteiras."""
    assert orcar(SEIS) == (SEIS, "")
    assert orcar("Pronto.") == ("Pronto.", "")
    assert _frases(orcar(SEIS)[0]) == 6


def test_o_monologo_para_numa_frase_inteira_e_pergunta_se_monta_o_resto_na_tela() -> None:
    falado, na_tela = orcar(MONOLOGO)

    assert falado == f"{CABEM} {FECHO}"
    assert FECHO.endswith("?"), "o fecho é uma pergunta, não um aviso"
    assert len(falado.removesuffix(FECHO).split()) <= PALAVRAS_NA_VOZ
    assert na_tela.startswith(f"{FRASE[:-1]} número {PALAVRAS_NA_VOZ // POR_FRASE}.")
    assert na_tela.endswith("número 11.")


@pytest.mark.parametrize("tamanho", [1, 2, 3, 7])
def test_em_stream_o_resultado_e_o_mesmo_de_uma_vez(tamanho: int) -> None:
    orcamento = OrcamentoDaFala()
    falado = "".join(
        orcamento.passar(MONOLOGO[i : i + tamanho]) for i in range(0, len(MONOLOGO), tamanho)
    )
    falado += orcamento.fechar()

    assert " ".join(falado.split()) == orcar(MONOLOGO)[0]
    assert orcamento.cortou and orcamento.so_na_tela == orcar(MONOLOGO)[1]


def test_cada_frase_sai_assim_que_fecha() -> None:
    """Sem a espera da «quarta frase»: o teto não atrasa a voz."""
    orcamento = OrcamentoDaFala()
    dito = orcamento.passar("Um. Dois. Três. Quatro. ")
    assert " ".join(dito.split()) == "Um. Dois. Três. Quatro."
    assert orcamento.fechar() == ""


def test_uma_frase_comprida_demais_e_cortada_na_virgula_dentro_do_teto() -> None:
    palavras = [f"item{i}" + ("," if i % 10 == 9 else "") for i in range(200)]
    falado, na_tela = orcar(" ".join(palavras) + ".")

    ditas = falado.removesuffix(FECHO).split()
    assert len(ditas) <= PALAVRAS_NA_VOZ
    assert falado.endswith(f"item119… {FECHO}")
    assert na_tela.startswith("item120")


def test_abreviacao_inicial_e_decimal_nao_fecham_frase() -> None:
    texto = "O Sr. Silva chegou às 3.5 horas. Ele trouxe o livro do J. R. R. Tolkien. Fim."
    assert orcar(texto) == (texto, "")


def test_uma_lista_comprida_para_numa_linha_inteira() -> None:
    itens = [f"item {i} com algumas palavras de descrição" for i in range(30)]
    falado, na_tela = orcar("Achei:\n" + "\n".join(itens))
    assert falado.endswith(FECHO) and "item 0 com" in falado
    assert len(falado.removesuffix(FECHO).split()) <= PALAVRAS_NA_VOZ
    assert na_tela.startswith("item ") and na_tela.endswith(
        "item 29 com algumas palavras de descrição"
    )


def test_com_o_dono_pedindo_detalhe_nao_ha_teto() -> None:
    assert orcar(MONOLOGO, livre=True) == (MONOLOGO, "")


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


def test_o_cerebro_fala_a_resposta_normal_inteira() -> None:
    _cerebro, publicados, telas, resposta = _responder("e aí, o que rolou?", SEIS)

    assert _voz(publicados) == " ".join(SEIS.split())
    assert telas[-1] == " ".join(SEIS.split())
    assert resposta.so_na_tela == ""


def test_o_cerebro_segura_o_monologo_pergunta_e_mostra_tudo() -> None:
    cerebro, publicados, telas, resposta = _responder("e aí, o que rolou?", MONOLOGO)

    assert _voz(publicados) == f"{CABEM} {FECHO}"
    assert telas[-1] == " ".join(MONOLOGO.split()), "a tela tem de mostrar a resposta inteira"
    assert resposta.so_na_tela.endswith("número 11.")
    assert publicados[-1]["last"] is True

    cerebro.ouvido(resposta.response_id, _voz(publicados), interrompida=False)
    lembrado = cerebro.conversa.turnos[-1].texto
    assert lembrado.startswith(CABEM) and "só na tela" in lembrado
    assert "número 11." in lembrado, "o modelo tem de saber o que o dono viu, para montar na tela"


def test_interrompido_o_que_ficou_na_tela_nao_entra_como_dito() -> None:
    cerebro, _publicados, _telas, resposta = _responder("e aí?", SEIS)
    cerebro.ouvido(resposta.response_id, "Abri o Spotify", interrompida=True)
    assert cerebro.conversa.turnos[-1].texto == "Abri o Spotify"


def test_pedindo_detalhe_o_cerebro_fala_a_resposta_inteira() -> None:
    _cerebro, publicados, _telas, resposta = _responder("me explica em detalhes", MONOLOGO)
    assert _voz(publicados) == " ".join(MONOLOGO.split())
    assert resposta.so_na_tela == ""


def test_a_persona_pede_a_resposta_curta_por_natureza() -> None:
    persona = prompt_de_sistema()  # v16: a seção VOZ E TELA
    assert "Responda curto e direto por natureza" in persona
    assert "uma a três frases" in persona
    assert "pergunte se ele quer o conteúdo completo montado na tela" in persona
    assert "Quando ele pedir detalhe" in persona
    assert "três ou quatro frases no máximo" not in persona, "o corte mecânico voltou à persona"


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


def test_a_resposta_de_uma_tarefa_segura_o_monologo_e_mostra_tudo(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)

    lembrado = _falar_a_resposta(app, _tarefa("abre o spotify e toca rock", MONOLOGO))

    assert f"Jarvis: {' '.join(MONOLOGO.split())}" in linhas, "a tela tem a resposta inteira"
    texto = lembrado()
    assert texto.startswith(f"{CABEM} {FECHO}"), texto
    assert "só na tela" in texto


def test_a_resposta_normal_de_uma_tarefa_vai_inteira(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)

    lembrado = _falar_a_resposta(app, _tarefa("abre o spotify e toca rock", SEIS))

    assert lembrado() == " ".join(SEIS.split())


def test_a_resposta_de_uma_tarefa_pedida_em_detalhe_vai_inteira_para_a_voz(
    tmp_path: Path,
) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)

    lembrado = _falar_a_resposta(app, _tarefa("me explica o que tem no spotify", MONOLOGO))

    assert lembrado() == " ".join(MONOLOGO.split())


def test_a_pergunta_de_uma_tarefa_nunca_e_cortada(tmp_path: Path) -> None:
    linhas: list[str] = []
    app = _app(tmp_path, linhas)
    pergunta = (
        "Preciso do seu sim para encerrar o Steam. Ele tem um jogo aberto. O jogo pode perder o "
        "progresso. A biblioteca também fecha. As downloads param. Posso?"
    )
    app._aviso_da_tarefa(_tarefa("x", ""), "pergunta-p1", "precisa_decisao", pergunta)

    assert app._falas_dos_avisos["pergunta-p1"] == pergunta
