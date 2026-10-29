"""A chave de API não aparece: nem em `repr`, nem em log, nem em `argv`, nem na configuração.

O teste que importa aqui é o último (`test_a_chave_nao_aparece_em_nenhuma_saida`): ele roda um
processo **de verdade**, com uma chave conhecida no ambiente, exercita o caminho que usa a
chave e varre tudo o que o processo escreveu — stdout, stderr, log do barramento, arquivos da
pasta de sessão. "Procurei e não achei" é a única forma de afirmar isso sem fé.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from jarvis.voz.chaves import (
    MARCA,
    VARIAVEIS,
    VARIAVEL_ELEVENLABS,
    VARIAVEL_GROQ,
    Chave,
    SegredoAusente,
    SegredoNaConfiguracao,
    SegredoNaLinhaDeComando,
    proibir_segredo_em_argv,
    proibir_segredo_na_configuracao,
    redigir,
    redigir_do_ambiente,
)

RAIZ = Path(__file__).resolve().parents[3]
SEGREDO = "gsk_chave_de_teste_que_nao_pode_vazar_0123456789"
SEGREDO_11 = "sk_outra_chave_de_teste_abcdefghijklmnop"


@pytest.fixture
def chave() -> Chave:
    return Chave(variavel=VARIAVEL_GROQ, valor=SEGREDO)


def test_a_chave_vem_do_ambiente() -> None:
    lida = Chave.do_ambiente(VARIAVEL_GROQ, ambiente={VARIAVEL_GROQ: SEGREDO})
    assert lida.usar() == SEGREDO
    assert lida.caracteres == len(SEGREDO)


def test_variavel_ausente_diz_o_que_exportar() -> None:
    with pytest.raises(SegredoAusente) as erro:
        Chave.do_ambiente(VARIAVEL_ELEVENLABS, ambiente={})
    assert VARIAVEL_ELEVENLABS in str(erro.value)
    assert "export" in str(erro.value)


def test_variavel_vazia_nao_e_chave() -> None:
    with pytest.raises(SegredoAusente):
        Chave.do_ambiente(VARIAVEL_GROQ, ambiente={VARIAVEL_GROQ: "   "})


def test_chave_curta_e_recusada_antes_de_qualquer_chamada() -> None:
    with pytest.raises(SegredoAusente, match="menos de"):
        Chave(variavel=VARIAVEL_GROQ, valor="abc")


def test_a_recusa_de_chave_curta_nao_mostra_o_pedaco() -> None:
    try:
        Chave(variavel=VARIAVEL_GROQ, valor="abc")
    except SegredoAusente as erro:
        assert "abc" not in str(erro)


def test_presente_responde_sem_ler_o_valor() -> None:
    assert Chave.presente(VARIAVEL_GROQ, ambiente={VARIAVEL_GROQ: SEGREDO})
    assert not Chave.presente(VARIAVEL_GROQ, ambiente={VARIAVEL_GROQ: ""})
    assert not Chave.presente(VARIAVEL_GROQ, ambiente={})


@pytest.mark.parametrize(
    "formatar",
    [
        repr,
        str,
        lambda c: f"{c}",
        lambda c: f"{c!r}",
        lambda c: f"{c!s}",
        lambda c: f"{c:>60}",
        # Os dois caminhos antigos de formatação entram de propósito: é por eles que um
        # `str` de segredo vazava em código que ninguém revisita.
        lambda c: "%s" % (c,),  # noqa: UP031
        lambda c: "{}".format(c),  # noqa: UP032
        lambda c: str([c]),
        lambda c: str({"chave": c}),
    ],
)
def test_nenhuma_forma_de_imprimir_mostra_a_chave(chave: Chave, formatar: object) -> None:
    """Dez formas de transformar objeto em texto. A décima primeira é `json`, abaixo."""
    texto = formatar(chave)  # type: ignore[operator]
    assert SEGREDO not in texto
    assert VARIAVEL_GROQ in texto
    assert "não mostrada" in texto


def test_chave_dentro_de_outro_objeto_tambem_nao_vaza(chave: Chave) -> None:
    """`repr` de `dataclass` chama o `repr` dos campos: é o caminho de vazamento por acidente."""
    from dataclasses import dataclass

    @dataclass
    class Pedido:
        servico: str
        chave: Chave

    assert SEGREDO not in repr(Pedido(servico="groq", chave=chave))


def test_chave_nao_serializa_em_json(chave: Chave) -> None:
    """Payload de evento é JSON (§3.1). Um `str` passaria; a `Chave` levanta."""
    with pytest.raises(TypeError):
        json.dumps({"chave": chave})


def test_redigir_apaga_o_valor_do_que_vem_de_fora(chave: Chave) -> None:
    corpo = f'{{"error":"invalid api key: {SEGREDO}"}}'
    limpo = redigir(corpo, [chave])
    assert SEGREDO not in limpo
    assert MARCA.format(variavel=VARIAVEL_GROQ) in limpo


def test_redigir_do_ambiente_cobre_as_duas_chaves() -> None:
    ambiente = {VARIAVEL_GROQ: SEGREDO, VARIAVEL_ELEVENLABS: SEGREDO_11}
    texto = f"falhou com {SEGREDO} e com {SEGREDO_11}"
    limpo = redigir_do_ambiente(texto, ambiente=ambiente)
    assert SEGREDO not in limpo and SEGREDO_11 not in limpo
    assert VARIAVEL_GROQ in limpo and VARIAVEL_ELEVENLABS in limpo


def test_redigir_sem_chave_nao_mexe_no_texto() -> None:
    assert redigir("nada a esconder", []) == "nada a esconder"


def test_as_variaveis_do_dono_sao_as_registradas() -> None:
    assert VARIAVEIS == (
        VARIAVEL_GROQ,
        VARIAVEL_ELEVENLABS,
        "OPENROUTER_API_KEY",
        "BRAVE_SEARCH_API_KEY",  # a busca na web pela API (ADR-0033)
        "OPENAI_API_KEY",  # os provedores de modelo (ADR-0056)
        "ANTHROPIC_API_KEY",
        "JARVIS_COMPATIVEL_API_KEY",
    )
    assert VARIAVEL_GROQ == "JARVIS_GROQ_API_KEY"
    assert VARIAVEL_ELEVENLABS == "JARVIS_ELEVENLABS_API_KEY"


# --- proibição 3: nada de chave em argv --------------------------------------------------


def test_chave_em_argv_impede_subir() -> None:
    with pytest.raises(SegredoNaLinhaDeComando, match=VARIAVEL_GROQ):
        proibir_segredo_em_argv(
            ["jarvis-voz", "--motor", f"--chave={SEGREDO}"],
            ambiente={VARIAVEL_GROQ: SEGREDO},
        )


def test_a_recusa_de_argv_nao_repete_o_argumento() -> None:
    try:
        proibir_segredo_em_argv(["jarvis-voz", SEGREDO], ambiente={VARIAVEL_GROQ: SEGREDO})
    except SegredoNaLinhaDeComando as erro:
        assert SEGREDO not in str(erro)


def test_formato_de_chave_em_argv_e_recusado_sem_a_variavel_exportada() -> None:
    """Sem a variável não há valor para comparar: o que resta é o formato público (`gsk_`)."""
    with pytest.raises(SegredoNaLinhaDeComando, match="forma de uma chave"):
        proibir_segredo_em_argv(["jarvis-voz", f"--chave={SEGREDO}"], ambiente={})


def test_linha_de_comando_normal_passa() -> None:
    proibir_segredo_em_argv(
        ["jarvis-voz", "--diagnostico", "--asr", "asr-whisper-local"],
        ambiente={VARIAVEL_GROQ: SEGREDO},
    )


# --- proibição 1: nada de chave na configuração ------------------------------------------


def test_configuracao_com_campo_de_chave_e_recusada() -> None:
    with pytest.raises(SegredoNaConfiguracao, match="groq_api_key"):
        proibir_segredo_na_configuracao({"groq_api_key": SEGREDO}, arquivo="jarvis.toml")


def test_configuracao_com_chave_aninhada_e_recusada() -> None:
    with pytest.raises(SegredoNaConfiguracao):
        proibir_segredo_na_configuracao({"nuvem": {"token": "abc123def456"}})


def test_configuracao_com_valor_em_formato_de_chave_e_recusada() -> None:
    with pytest.raises(SegredoNaConfiguracao, match="forma de chave"):
        proibir_segredo_na_configuracao({"voz": SEGREDO_11})


def test_configuracao_sem_segredo_passa() -> None:
    proibir_segredo_na_configuracao(
        {"asr": "asr-whisper-local", "tts": "tts-piper-epitran", "nuvem_ligada": []}
    )


def test_campo_de_nome_suspeito_mas_vazio_passa() -> None:
    """O dono pode deixar o campo documentado e vazio; vazio não é segredo."""
    proibir_segredo_na_configuracao({"chave": ""})


# --- a varredura: um processo de verdade, e nada da chave em nenhuma saída ----------------


def test_a_chave_nao_aparece_em_nenhuma_saida(tmp_path: Path) -> None:
    """Roda um processo com a chave no ambiente, usa a chave e varre tudo o que ele escreveu.

    O processo faz o que o produto faz: lê a chave, monta o cabeçalho, erra de propósito
    (serviço inexistente), registra a falha na degradação e no log do barramento, imprime
    diagnóstico. Depois disso, `SEGREDO` não pode estar em lugar nenhum — e o teste também
    confere que a varredura **acharia** se estivesse (prova do próprio método).
    """
    roteiro = tmp_path / "usar_a_chave.py"
    roteiro.write_text(
        """
from __future__ import annotations

import json
import sys
from pathlib import Path

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.barramento.log import LogDeEventos
from jarvis.rede import AdaptadorRemoto, SondaInjetada, escrever_degradacao, ler_degradacao
from jarvis.voz.chaves import VARIAVEL_GROQ, Chave, redigir

raiz = Path(sys.argv[1])
chave = Chave.do_ambiente(VARIAVEL_GROQ)

# 1. o jeito certo de falar da chave em log
print("motor de nuvem pronto:", chave)
print("diagnostico:", repr({"chave": chave, "variavel": chave.variavel}))

# 2. o cabecalho montado (e nao impresso)
cabecalhos = {"Authorization": f"Bearer {chave.usar()}"}
print("cabecalhos montados:", sorted(cabecalhos))

# 3. uma falha de servico, com corpo de erro que repete a chave de volta
corpo_do_servico = json.dumps({"error": "invalid api key: " + chave.usar()})
print("erro do servico:", redigir(corpo_do_servico, [chave]), file=sys.stderr)

# 4. degradacao em arquivo (jarvis.rede) e evento no log encadeado
adaptador = AdaptadorRemoto(servico="Groq", raiz=raiz, sonda=SondaInjetada(ligada=False))
adaptador.chamar(lambda prazo: None, call_id="c-1", epoch=1)
print("degradacao:", ler_degradacao(raiz).frase)

log = LogDeEventos(raiz / "eventos.sqlite3")
log.anexar(
    Envelope(
        session_id="s-1",
        epoch=1,
        source="agentd",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.FINAL_TRANSCRIPT,
        payload={"text": "a chave nao entra aqui", "confidence": 1.0,
                 "t_start_ms": 0, "t_end_ms": 10},
    )
)
log.fechar()
escrever_degradacao(raiz, ler_degradacao(raiz))
""",
        encoding="utf-8",
    )
    sessao = tmp_path / "sessao"
    sessao.mkdir()

    concluido = subprocess.run(
        [sys.executable, str(roteiro), str(sessao)],
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(RAIZ / "src"),
            "CI": "1",
            VARIAVEL_GROQ: SEGREDO,
        },
    )
    assert concluido.returncode == 0, concluido.stdout + concluido.stderr

    escrito = [concluido.stdout, concluido.stderr]
    arquivos = [caminho for caminho in sessao.rglob("*") if caminho.is_file()]
    assert arquivos, "o processo não escreveu nada: a varredura não provaria nada"
    for caminho in arquivos:
        escrito.append(caminho.read_bytes().decode("utf-8", "replace"))

    for pedaco in escrito:
        assert SEGREDO not in pedaco, "a chave vazou"
    # A varredura acha o que está lá: prova de que a ausência acima não é cegueira do método.
    assert any(VARIAVEL_GROQ in pedaco for pedaco in escrito)
    assert any(SEGREDO in pedaco for pedaco in [SEGREDO])


def test_chave_com_a_forma_da_openai_tambem_e_recusada() -> None:
    """`sk-…` (OpenAI, OpenRouter, Anthropic; ADR-0056) tem a mesma recusa por forma."""
    for chave in ("sk-proj-abcdefghijklmnop", "sk-or-v1-abcdefghijklmnop", "sk-ant-abcdefghijklm"):
        with pytest.raises(SegredoNaLinhaDeComando):
            proibir_segredo_em_argv(["jarvis-voz", f"--x={chave}"], ambiente={})
