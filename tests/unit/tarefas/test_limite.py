"""ADR-0070: o limite da tarefa é uma notificação ao motor, e a decisão é dele."""

from __future__ import annotations

from jarvis.executor.ferramentas import ResultadoDeFerramenta
from jarvis.tarefas.limite import (
    MARCA_DA_NOTIFICACAO,
    PASSOS_NA_NOTIFICACAO,
    DecisaoNoLimite,
    MotivoDoLimite,
    ler_decisao,
    notificacao,
)

TODAS = ("continuar", "perguntar", "encerrar")


def test_a_notificacao_traz_o_estado_real_e_nenhuma_frase_ao_dono() -> None:
    feitos = [
        ResultadoDeFerramenta("browser.read", "ok"),
        ResultadoDeFerramenta(
            "browser.click", "erro", motivo="o botão não existe", causa="sem_alvo"
        ),
    ]
    aviso = notificacao(
        MotivoDoLimite.PASSOS, "mande oi pra Ana", feitos, segundos=42.4, bloco=50, proximo="x.y"
    )

    texto = aviso.para_o_motor()
    assert texto.startswith(MARCA_DA_NOTIFICACAO)
    assert "mande oi pra Ana" in texto and "42 s" in texto
    assert "browser.click → erro [sem_alvo]: o botão não existe" in texto
    assert "1 deram certo, 1 falharam" in texto
    assert "x.y" in texto
    assert '"decisao"' in texto and "de 1 a 50" in texto
    assert "Parei" not in texto and "Não consegui" not in texto
    assert aviso.em_poucas_palavras() == "teto_de_passos: 2 passo(s), 1 certo(s), 1 falha(s), 42 s"


def test_a_notificacao_leva_so_os_ultimos_passos() -> None:
    feitos = [ResultadoDeFerramenta(f"t.{i}", "ok") for i in range(30)]
    aviso = notificacao(MotivoDoLimite.TEMPO, "p", feitos, segundos=1, bloco=5)
    assert len(aviso.passos) == PASSOS_NA_NOTIFICACAO and aviso.passos[-1].startswith("t.29")
    assert aviso.passos_dados == 30


def test_ler_a_decisao_do_motor() -> None:
    assert ler_decisao(
        'pensei. {"decisao": "continuar", "passos": 7, "estrategia": "usar a busca"}', TODAS, 50
    ) == DecisaoNoLimite("continuar", 7, "usar a busca", "")
    assert ler_decisao('{"decisao": "continuar", "passos": 900}', TODAS, 50).passos == 50
    assert ler_decisao('{"decisao": "perguntar", "texto": "Sigo?"}', TODAS, 50).texto == "Sigo?"


def test_sem_json_o_texto_do_motor_e_o_fim_dele() -> None:
    decisao = ler_decisao("Li tudo e parei aqui.", TODAS, 50)
    assert decisao.acao == "encerrar" and decisao.texto == "Li tudo e parei aqui."


def test_decisao_fora_das_opcoes_nao_continua() -> None:
    sem_continuar = ("perguntar", "encerrar")
    assert ler_decisao('{"decisao": "continuar"}', sem_continuar, 50).acao == "encerrar"
    assert (
        ler_decisao('{"decisao": "continuar", "texto": "Sigo?"}', sem_continuar, 50).acao
        == "perguntar"
    )
    assert ler_decisao('{"decisao": "perguntar"}', TODAS, 50).acao == "encerrar", "sem pergunta"
