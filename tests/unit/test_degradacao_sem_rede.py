"""Cartão F1-14: sem rede, cai para PTT e **diz** isso — com os cinco aceites.

"Degradar é obrigatório; degradar em silêncio é defeito." Os testes aqui são sobre as duas
metades disso: a degradação acontece **na mesma volta** em que a chamada cai, e ela é **dita**
— na tela e, uma vez só, por voz. Mais o que o cartão cobra e é fácil de esquecer: a volta da
rede não pode ressuscitar pedido velho (§3.3 regra 5).
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from jarvis.agentd.aviso import avisos_falados, falar_aviso
from jarvis.agentd.turno_completo import PONTOS, TurnoCompleto
from jarvis.barramento.envelope import Envelope, Tipo, uuid7
from jarvis.microfone import Modo
from jarvis.processo import Processo
from jarvis.rede import (
    PRAZO_DA_SONDA_S,
    PRAZO_PADRAO_S,
    VARIAVEL_ARQUIVO,
    VARIAVEL_BACKEND,
    VARIAVEL_DISPONIVEL,
    AdaptadorRemoto,
    Degradacao,
    RedeProibidaEmCI,
    ServicoIndisponivel,
    SondaDeSocket,
    SondaInjetada,
    frase_de_queda,
    frase_de_volta,
    ler_degradacao,
    sonda_do_ambiente,
)
from jarvis.s2.__main__ import call_id_do_turno, reacao_com_rede, reagir
from jarvis.ui.painel import PainelDoMicrofone
from tests.fabricas import evento

SERVICO = "o serviço de raciocínio"


def uma_frase(texto: str) -> bool:
    """Aceite (b): **uma** frase — sem quebra de linha, com um ponto final só."""
    return "\n" not in texto and texto.endswith(".") and texto.count(".") == 1


def montar(tmp_path: Path, *, ligada: bool = True) -> tuple[AdaptadorRemoto, SondaInjetada]:
    sonda = SondaInjetada(ligada=ligada)
    return AdaptadorRemoto(servico=SERVICO, raiz=tmp_path, sonda=sonda), sonda


def test_queda_no_meio_do_turno_cai_para_ptt_na_mesma_volta(tmp_path: Path) -> None:
    """Aceite (a): a degradação é da chamada que caiu, não de um `timeout` daqui a um minuto."""
    adaptador, sonda = montar(tmp_path)
    painel = PainelDoMicrofone(raiz=tmp_path, modo=Modo.ESCUTA)
    assert adaptador.chamar(lambda _p: "resposta", call_id="c-1") == "resposta"
    assert painel.aplicar_degradacao().ativa is False

    sonda.ligada = False
    caiu = adaptador.chamar(lambda _p: "resposta", call_id="c-2")
    degradacao = painel.aplicar_degradacao()

    assert caiu is None, "pedido que cai não devolve resposta inventada"
    assert degradacao.ativa and degradacao.servico == SERVICO
    assert painel.modo is Modo.PTT, "a escuta contínua sai e o PTT entra, na mesma volta"
    assert painel.degradado is True
    assert painel.aviso == degradacao.frase
    assert ler_degradacao(tmp_path).descartados == ("c-2",)


def test_a_mensagem_diz_em_uma_frase_o_que_deixou_de_funcionar(tmp_path: Path) -> None:
    """Aceite (b)."""
    adaptador, sonda = montar(tmp_path, ligada=False)
    adaptador.chamar(lambda _p: "resposta", call_id="c-1")

    frase = ler_degradacao(tmp_path).frase

    assert frase == frase_de_queda(SERVICO)
    assert uma_frase(frase) and uma_frase(frase_de_volta(SERVICO))
    assert SERVICO in frase
    assert "computador" in frase, "a frase diz também o que CONTINUA funcionando"
    assert sonda.consultas == 1


def test_o_prazo_e_nosso_e_chega_a_quem_faz_a_chamada(tmp_path: Path) -> None:
    """Aceite (a), "nenhum timeout longo herdado": o prazo desce como argumento."""
    adaptador, _ = montar(tmp_path)
    prazos: list[float] = []

    adaptador.chamar(lambda prazo: prazos.append(prazo), call_id="c-1")

    assert prazos == [PRAZO_PADRAO_S]
    assert PRAZO_PADRAO_S <= 2.0 and PRAZO_DA_SONDA_S <= 0.5


def test_resposta_fora_do_prazo_conta_como_queda(tmp_path: Path) -> None:
    """Chegou depois do prazo é informação velha — a mesma regra do orçamento do S1 (F1-08)."""
    agora = [0.0]
    adaptador = AdaptadorRemoto(
        servico=SERVICO,
        raiz=tmp_path,
        sonda=SondaInjetada(ligada=True),
        agora=lambda: agora[0],
    )

    def devagar(prazo: float) -> str:
        agora[0] += prazo * 2
        return "resposta que chegou tarde"

    resultado = adaptador.chamar(devagar, call_id="c-1")

    assert resultado is None, "resposta fora do prazo não vira resultado"
    assert adaptador.degradado is True


def test_erro_do_servico_nao_vira_excecao_para_cima(tmp_path: Path) -> None:
    adaptador, _ = montar(tmp_path)

    def cai(_prazo: float) -> str:
        raise ServicoIndisponivel("500 do outro lado")

    assert adaptador.chamar(cai, call_id="c-1") is None
    assert adaptador.degradado is True


def test_rede_de_volta_nao_ressuscita_pedido_nem_dispara_tool(tmp_path: Path) -> None:
    """Aceite (c): regra 5 em forma de estrutura, não de disciplina."""
    adaptador, sonda = montar(tmp_path, ligada=False)
    efeitos: list[str] = []

    def tool_de_efeito(_prazo: float) -> str:
        efeitos.append("apagou arquivo")
        return "feito"

    adaptador.chamar(tool_de_efeito, call_id="c-7")
    assert efeitos == [], "a tool nem foi chamada: a rede estava fora"

    sonda.ligada = True
    voltou = adaptador.conferir()
    repetido = adaptador.chamar(tool_de_efeito, call_id="c-7")
    novo = adaptador.chamar(tool_de_efeito, call_id="c-8")

    assert voltou.ativa is False
    assert repetido is None, "pedido descartado não volta nem sendo pedido com o mesmo id"
    assert adaptador.recusas_por_descarte == 1
    assert novo == "feito", "pedido NOVO funciona: a volta não deixa o sistema inútil"
    assert efeitos == ["apagou arquivo"], "só o pedido novo disparou efeito"
    assert ler_degradacao(tmp_path).descartados == ("c-7",), (
        "a lista de descartados sobrevive à volta da rede — é ela que impede o ressuscitar"
    )


def test_a_volta_restaura_o_modo_de_antes_e_confirma_na_tela(tmp_path: Path) -> None:
    adaptador, sonda = montar(tmp_path, ligada=False)
    painel = PainelDoMicrofone(raiz=tmp_path, modo=Modo.ESCUTA)
    adaptador.chamar(lambda _p: "x", call_id="c-1")
    painel.aplicar_degradacao()
    # Em local: `assert painel.modo is Modo.PTT` estreitaria o atributo e o mypy
    # (warn_unreachable) chamaria o resto do teste de inalcançável.
    modo_degradado = painel.modo

    sonda.ligada = True
    adaptador.conferir()
    degradacao = painel.aplicar_degradacao()

    assert modo_degradado is Modo.PTT
    assert painel.modo is Modo.ESCUTA, "a volta restaura o modo de antes, não inventa"
    assert painel.degradado is False
    assert painel.aviso == frase_de_volta(SERVICO)
    assert degradacao.ativa is False


def test_kill_switch_vence_a_degradacao(tmp_path: Path) -> None:
    """O dono desligou o microfone: cair a rede não o religa em PTT."""
    adaptador, _ = montar(tmp_path, ligada=False)
    painel = PainelDoMicrofone(raiz=tmp_path, modo=Modo.ESCUTA)
    painel.desligar()

    adaptador.chamar(lambda _p: "x", call_id="c-1")
    painel.aplicar_degradacao()

    assert painel.modo is Modo.DESLIGADO
    assert painel.tick().quer_fonte_aberta is False


def test_aviso_por_voz_sai_uma_vez_por_episodio(tmp_path: Path) -> None:
    """Aceite (e): o aviso não se repete em loop, nem com a chamada caindo 50 vezes."""
    adaptador, sonda = montar(tmp_path, ligada=False)
    for i in range(50):
        adaptador.chamar(lambda _p: "x", call_id=f"c-{i}")
        falar_aviso(tmp_path, epoch=1)

    falados = avisos_falados(tmp_path)

    assert len(falados) == 1, f"o Jarvis falou {len(falados)} vezes a mesma coisa"
    assert falados[0].frase == frase_de_queda(SERVICO)
    assert falados[0].amostras > 0, "o aviso foi sintetizado de verdade, não só registrado"
    assert ler_degradacao(tmp_path).avisado_por_voz is True

    # Episódio NOVO (voltou e caiu de novo) pode avisar de novo: o que não pode é repetir.
    sonda.ligada = True
    adaptador.conferir()
    sonda.ligada = False
    adaptador.chamar(lambda _p: "x", call_id="c-100")
    falar_aviso(tmp_path, epoch=2)

    assert len(avisos_falados(tmp_path)) == 2


def test_aviso_nao_sai_quando_nao_ha_degradacao(tmp_path: Path) -> None:
    assert falar_aviso(tmp_path) is None
    assert avisos_falados(tmp_path) == []


def test_degradacao_ilegivel_nao_inventa_aviso(tmp_path: Path) -> None:
    (tmp_path / "degradacao.json").write_text("{isto não é json", encoding="utf-8")

    assert ler_degradacao(tmp_path) == Degradacao()
    assert PainelDoMicrofone(raiz=tmp_path).aplicar_degradacao().ativa is False


def test_sonda_de_socket_recusa_abrir_rede_no_ci() -> None:
    """Aceite (d), a parte estrutural: a recusa mora no código de produção."""
    sonda = SondaDeSocket(host="exemplo.invalido", porta=443)

    with pytest.raises(RedeProibidaEmCI):
        sonda.disponivel()


def test_sonda_vem_do_ambiente(tmp_path: Path) -> None:
    arquivo = tmp_path / "rede"
    injetada = sonda_do_ambiente(
        ambiente={VARIAVEL_BACKEND: "injetada", VARIAVEL_ARQUIVO: str(arquivo)}
    )
    assert isinstance(injetada, SondaInjetada)
    sem_arquivo = sonda_do_ambiente(ambiente={VARIAVEL_DISPONIVEL: "0"})
    de_socket = sonda_do_ambiente(
        host="exemplo.invalido", porta=443, ambiente={VARIAVEL_BACKEND: "socket"}
    )

    arquivo.write_text("0", encoding="utf-8")
    fora = injetada.disponivel()
    arquivo.write_text("1", encoding="utf-8")

    assert (fora, injetada.disponivel()) == (False, True)
    assert sem_arquivo.disponivel() is False
    assert isinstance(de_socket, SondaDeSocket)
    with pytest.raises(ValueError, match="não existe"):
        sonda_do_ambiente(ambiente={VARIAVEL_BACKEND: "pombo-correio"})


def test_sonda_sem_arquivo_e_sem_processo_conta_como_rede_fora(tmp_path: Path) -> None:
    sonda = SondaInjetada(arquivo=tmp_path / "nao-existe")

    assert sonda.disponivel() is False, "na dúvida, degradado: não é hora de prometer rede"


def test_a_cascata_local_inteira_roda_sem_socket_externo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Aceite (d): o turno inteiro (VAD → percepção → S1 → TTS → playback) roda offline.

    A proibição é de verdade: qualquer `connect` para `AF_INET`/`AF_INET6` levanta. O socket de
    domínio do barramento continua permitido — ele é local, e é o que a §2 usa.
    """
    conectar_de_verdade = socket.socket.connect

    def sem_rede(self: socket.socket, endereco: Any) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"a cascata local tentou abrir socket externo: {endereco!r}")
        conectar_de_verdade(self, endereco)

    monkeypatch.setattr(socket.socket, "connect", sem_rede)
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError(f"create_connection não pode acontecer offline: {a!r}")
        ),
    )

    resultado = TurnoCompleto().rodar()
    por_ponto = [TurnoCompleto().rodar(ponto.nome) for ponto in PONTOS[:5]]

    assert resultado.fala.amostras_sintetizadas > 0, "a cascata local fala sem rede nenhuma"
    assert resultado.amostras_tocadas > 0
    assert all(r.invariantes_ok for r in por_ponto), "cancelar offline mantém as invariantes"


# --- achado 5: dois escritores no mesmo arquivo -----------------------------------
def test_dois_escritores_ao_mesmo_tempo_nao_perdem_call_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Achado 5 da revisão F0+F1: o par ler→escrever de `degradacao.json` não era trancado.

    O arquivo tem dois escritores reconhecidos (o `s2` e o `agentd`), e `escrever_atomico`
    impede bytes intercalados, não perda de atualização: A lê, B lê, A escreve, B escreve, e o
    `call_id` que A acrescentou **some**. Quando a rede volta, esse pedido pode ser refeito —
    exatamente o que a regra 5 do epoch existe para proibir.

    A escrita lenta não inventa defeito: ela alarga a janela que já existe entre a leitura e a
    troca atômica, para a corrida ser determinística em vez de sorte.
    """
    import jarvis.rede as rede

    escrita_original = rede.escrever_degradacao

    def escrita_lenta(raiz: Path, degradacao: Degradacao) -> None:
        time.sleep(0.05)
        escrita_original(raiz, degradacao)

    monkeypatch.setattr(rede, "escrever_degradacao", escrita_lenta)

    esperados = set()
    linhas = []
    for nome in ("s2", "agentd"):
        adaptador = AdaptadorRemoto(servico=SERVICO, raiz=tmp_path, sonda=SondaInjetada(False))
        ids = [f"{nome}-{i}" for i in range(3)]
        esperados |= set(ids)

        def cair(adaptador: AdaptadorRemoto = adaptador, ids: list[str] = ids) -> None:
            for call_id in ids:
                adaptador.chamar(lambda _prazo: None, call_id=call_id)

        linhas.append(threading.Thread(target=cair, name=nome))
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join(timeout=30.0)

    descartados = set(ler_degradacao(tmp_path).descartados)
    assert esperados <= descartados, f"perdidos: {sorted(esperados - descartados)}"


# --- repetição do F1-14: a identidade do pedido é a do turno -------------------------
SESSAO = "01a15c68-0000-7000-8000-000000000000"
JANELA_DO_UUID7_MS = 1 << 16
"""Os 8 primeiros dígitos de um uuid7 são os 32 bits altos do milissegundo: 65,5 s."""
DISTANCIAS = {
    "mesmo milissegundo": 0,
    "mesma janela do uuid7": 1_000,
    "janela seguinte do uuid7": JANELA_DO_UUID7_MS,
}


def transcricao_no_milissegundo(epoch: int, ms: int) -> Envelope:
    """Um `FinalTranscript` com o relógio do uuid7 fixado; o aleatório continua do gerador.

    É o que torna a corrida determinística: a janela que o defeito precisava (dois turnos na
    mesma janela de 65,5 s, ou um de cada lado da virada) deixa de depender da hora do teste.
    """
    tempo = f"{ms:012x}"
    return replace(
        evento(Tipo.FINAL_TRANSCRIPT, SESSAO, epoch=epoch),
        event_id=f"{tempo[:8]}-{tempo[8:]}-{uuid7()[14:]}",
    )


@pytest.mark.parametrize("distancia_ms", DISTANCIAS.values(), ids=DISTANCIAS.keys())
def test_a_volta_atende_turno_novo_e_nunca_o_que_caiu(tmp_path: Path, distancia_ms: int) -> None:
    """Aceite (c) pela identidade do pedido, no caminho de verdade do `s2` — sem processo e sem
    `sleep`.

    O defeito: o `call_id` era `c-{event_id[:8]}`, igual para todo turno da mesma janela de
    65,5 s. Depois da queda, turno **novo** da janela era recusado como descartado; quando a
    janela virava entre a queda e a volta, ele passava. O teste de integração só via isso uma
    vez em vinte. Aqui as três posições da janela são forçadas, e o resultado tem de ser o
    mesmo nas três: o que caiu fica morto, e o que é novo é atendido.
    """
    adaptador, sonda = montar(tmp_path)
    processo = Processo(nome="s2", raiz=tmp_path, reacao=reagir, session_id=SESSAO)
    reagir_com_rede = reacao_com_rede(adaptador)
    inicio = (0x01A15C68 << 16) + 100

    def ouvir(transcricao: Envelope) -> list[Envelope]:
        # O que `Processo.recebidos` faz antes da reação: o epoch segue o maior entregue.
        processo.epoch = max(processo.epoch, transcricao.epoch)
        return reagir_com_rede(processo, transcricao, "aceitar")

    com_rede = transcricao_no_milissegundo(1, inicio)
    que_caiu = transcricao_no_milissegundo(2, inicio + distancia_ms)
    novo = transcricao_no_milissegundo(3, inicio + 2 * distancia_ms)
    mesma_janela = distancia_ms < JANELA_DO_UUID7_MS
    assert (que_caiu.event_id[:8] == novo.event_id[:8]) is mesma_janela, "a janela está forçada"

    atendido = ouvir(com_rede)
    sonda.ligada = False
    assert ouvir(que_caiu) == [], "sem rede, o pedido cai e não entra no barramento"
    sonda.ligada = True
    adaptador.conferir(epoch=processo.epoch)
    reentregue = ouvir(que_caiu)
    depois_da_volta = ouvir(novo)

    pedido_com_rede = atendido[0].payload["call_id"]
    descartados = ler_degradacao(tmp_path).descartados
    assert descartados == (call_id_do_turno(que_caiu),), "o que caiu é o turno, pela identidade"
    assert pedido_com_rede not in descartados, "pedido atendido não divide id com o que caiu"
    assert reentregue == [], "a mesma transcrição reentregue depois da volta continua morta"
    assert adaptador.recusas_por_descarte == 1
    assert len(depois_da_volta) == 1, (
        "turno novo depois da volta é atendido: a escuta não volta surda"
    )
    pedido_novo = depois_da_volta[0]
    assert pedido_novo.type is Tipo.TOOL_CALL_REQUESTED
    assert pedido_novo.epoch == novo.epoch > que_caiu.epoch
    assert pedido_novo.payload["call_id"] == call_id_do_turno(novo)
    assert len({pedido_com_rede, *descartados, pedido_novo.payload["call_id"]}) == 3


def test_sem_rede_tambem_cada_turno_tem_o_seu_pedido(tmp_path: Path) -> None:
    """Sem o adaptador, o mesmo defeito fazia o executor engolir o segundo turno da janela: ele
    não roda duas vezes o mesmo `call_id` (idempotência). Turno novo, id novo; a mesma
    transcrição, o mesmo id — e aí a idempotência acerta."""
    processo = Processo(nome="s2", raiz=tmp_path, reacao=reagir, session_id=SESSAO, epoch=2)
    primeiro = transcricao_no_milissegundo(2, 0x01A15C68 << 16)
    segundo = transcricao_no_milissegundo(2, 0x01A15C68 << 16)

    ids = [reagir(processo, t, "aceitar")[0].payload["call_id"] for t in (primeiro, segundo)]
    de_novo = reagir(processo, primeiro, "aceitar")[0].payload["call_id"]

    assert primeiro.event_id[:8] == segundo.event_id[:8], "a janela do defeito está forçada"
    assert ids[0] != ids[1]
    assert de_novo == ids[0]
