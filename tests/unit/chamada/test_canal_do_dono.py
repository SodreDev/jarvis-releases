"""O canal do dono (ADR-0074; decisão do dono de 2026-11-17): o agente acha o chat do dono no
WhatsApp Web LENDO a lista, manda a ação pendente com o código, e só a resposta do dono no chat
dele confirma. Página falsa, motor roteirizado, relógio falso: nada real."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.chamada.acoes import AcoesPendentes
from jarvis.chamada.agente import PEDIR_ACAO, AgenteDaChamada
from jarvis.chamada.canal_do_dono import (
    ABRIR,
    AVISAR_JARVIS,
    CABECALHO,
    CONFIRMAR,
    ENVIAR,
    INSPECIONAR,
    POR_HORA,
    RECUSAR,
    AgenteDoCanalDoDono,
    GuardaDoCanal,
    LinhaDaLista,
    ObservadorDoChat,
    PaginaFalsa,
    ligar_ao_agente_da_chamada,
)
from jarvis.chamada.config import ConfiguracaoDaChamada
from jarvis.s2.laco import QUEM_CANAL_DO_DONO, observar
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.social.envio import (
    CONTATO_DO_CANAL,
    AjusteDoEnvio,
    EnvioRecusado,
    Guardiao,
    HistoricoDeEnvios,
    Pausas,
    PedidoDeEnvio,
    Permitido,
    Registro,
)
from tests.unit.chamada.test_agente import AVISO, Mundo

TARDE = datetime(2026, 11, 17, 14, 0).timestamp()
DONO = "Marcos Souza (você)"


def linhas() -> list[LinhaDaLista]:
    return [
        LinhaDaLista("c1", "Carlos Mendes", "valeu, até amanhã"),
        LinhaDaLista("c2", "Família Souza", "foto", grupo=True),
        LinhaDaLista("c3", DONO, "lista do mercado"),
        LinhaDaLista("c4", "Ana", "ok"),
    ]


def _codigo(contexto: Contexto) -> str:
    achado = re.search(r"CÓDIGO DA AÇÃO PENDENTE \(sistema\): (\w+)", contexto.mensagens[0].texto)
    return achado.group(1) if achado else ""


class Canal:
    def __init__(
        self,
        tmp_path: Path,
        roteiro: Callable[[Contexto], Sequence[Parte]] | None,
        *,
        contato: str = DONO,
        pagina: PaginaFalsa | None = None,
    ) -> None:
        self.relogio = [TARDE]
        self.config = ConfiguracaoDaChamada(contato_do_dono_whatsapp=contato)
        self.eventos: list[dict[str, Any]] = []
        self.contextos: list[Contexto] = []
        self.pagina = pagina or PaginaFalsa(linhas())
        self.historico = HistoricoDeEnvios(tmp_path / "envios.jsonl")
        self.acoes = AcoesPendentes(
            prazo_min=lambda: self.config.acao_expira_min,
            canais=lambda: self.config.canais_de_confirmacao,
            ao_mudar=self.eventos.append,
            relogio=lambda: self.relogio[0],
        )
        self.chamadas_ao_motor = 0
        motor = None
        if roteiro is not None:

            def responder(contexto: Contexto) -> Sequence[Parte]:
                self.chamadas_ao_motor += 1
                self.contextos.append(contexto)
                return roteiro(contexto)

            motor = MotorRoteirizado(resposta=responder, conta_eventos=False)
        self.agente = AgenteDoCanalDoDono(
            motor=lambda: motor,
            configuracao=lambda: self.config,
            pagina=self.pagina,
            guarda=GuardaDoCanal(
                self.historico, Pausas(tmp_path / "pausas.json"), relogio=lambda: self.relogio[0]
            ),
            acoes=self.acoes,
            ao_avisar_jarvis=self.eventos.append,
        )

    def propor(self) -> str:
        pendente = self.acoes.propor(
            "mandar o contrato à Ana",
            "hoje",
            interlocutor="Bruno",
            app="Meet",
            dono_reconhecido=False,
        )
        assert pendente is not None
        return pendente.codigo

    def evento_da_acao(self) -> dict[str, Any]:
        return next(e for e in self.eventos if e["tipo"] == "acao_da_chamada_pendente")


def passos(*rodadas: Sequence[Parte] | Callable[[Contexto], Sequence[Parte]]) -> Any:
    fila = list(rodadas)

    def responder(contexto: Contexto) -> Sequence[Parte]:
        if not fila:
            return []
        proximo = fila.pop(0)
        return proximo(contexto) if callable(proximo) else proximo

    return responder


def enviar_com_codigo(contexto: Contexto) -> Sequence[Parte]:
    return [
        PedidoDeTool(
            ENVIAR,
            {
                "texto": "Jarvis: pediram na chamada mandar o contrato à Ana. Código "
                f"{_codigo(contexto)}, vale 10 min. Responda com o código para confirmar ou "
                "recusar."
            },
        )
    ]


CAMINHO_CERTO = (
    [PedidoDeTool(INSPECIONAR, {})],
    [PedidoDeTool(ABRIR, {"id": "c3"})],
    [PedidoDeTool(CABECALHO, {})],
    enviar_com_codigo,
)


def test_acha_o_chat_do_dono_lendo_a_lista_e_envia_com_o_codigo(tmp_path: Path) -> None:
    canal = Canal(tmp_path, passos(*CAMINHO_CERTO))
    codigo = canal.propor()
    quem: list[str] = []
    desligar = observar(lambda q, _c: quem.append(q))
    try:
        resultado = canal.agente.enviar(canal.evento_da_acao())
    finally:
        desligar()
    assert set(quem) == {QUEM_CANAL_DO_DONO}
    assert resultado.enviou and not resultado.falhou
    ((conversa, texto),) = canal.pagina.enviadas
    assert conversa == "c3" and codigo in texto
    assert canal.agente.chat_do_dono == DONO
    (registro,) = canal.historico.registros()
    assert (registro.contato, registro.resultado) == (CONTATO_DO_CANAL, "enviado")
    # A lista chega ao modelo como dado entre os marcadores desta rodada.
    lista = canal.contextos[1].mensagens[-1].texto
    assert "Carlos Mendes" in lista and "conversas na lista" in lista


def test_sem_o_nome_configurado_o_canal_nao_roda(tmp_path: Path) -> None:
    canal = Canal(tmp_path, passos(*CAMINHO_CERTO), contato="")
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    assert resultado.motivo == "canal_desligado" and canal.chamadas_ao_motor == 0
    assert canal.pagina.enviadas == []


def test_conversa_errada_recusa_e_o_agente_corrige(tmp_path: Path) -> None:
    canal = Canal(
        tmp_path,
        passos(
            [PedidoDeTool(INSPECIONAR, {})],
            [PedidoDeTool(ABRIR, {"id": "c1"})],
            [PedidoDeTool(CABECALHO, {})],
            enviar_com_codigo,
            [PedidoDeTool(ABRIR, {"id": "c3"})],
            [PedidoDeTool(CABECALHO, {})],
            enviar_com_codigo,
        ),
    )
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    recusa = next(f for f in resultado.feitos if f.ferramenta == ENVIAR)
    assert not recusa.aceita and "não é o chat do dono" in recusa.veredito
    assert [c for c, _ in canal.pagina.enviadas] == ["c3"]


@pytest.mark.parametrize(
    ("rodadas", "trecho"),
    [
        ([[PedidoDeTool(ABRIR, {"id": "c3"})]], "leia a lista"),
        (
            [
                [PedidoDeTool(INSPECIONAR, {})],
                [PedidoDeTool(ABRIR, {"id": "c3"})],
                [PedidoDeTool(ENVIAR, {"texto": "oi"})],
            ],
            "leia o cabeçalho",
        ),
        (
            [[PedidoDeTool(INSPECIONAR, {})], [PedidoDeTool(ABRIR, {"id": "c9"})]],
            "não há conversa",
        ),
        (
            [
                [PedidoDeTool(INSPECIONAR, {})],
                [PedidoDeTool(ABRIR, {"id": "c3"})],
                [PedidoDeTool(CABECALHO, {})],
                [PedidoDeTool(ENVIAR, {"texto": "confirma?"})],
            ],
            "tem de trazer o código",
        ),
        ([[PedidoDeTool("browser.click", {"id": "c3"})]], "não existe"),
        ([[PedidoDeTool(CONFIRMAR, {"codigo": "X"})]], "não existe"),
    ],
)
def test_travas_do_envio(tmp_path: Path, rodadas: list[Any], trecho: str) -> None:
    canal = Canal(tmp_path, passos(*rodadas))
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    assert canal.pagina.enviadas == []
    assert any(trecho in f.veredito for f in resultado.feitos if not f.aceita)
    # Não enviou nem avisou: a falha vira evento ao Jarvis, com o que foi tentado.
    assert resultado.falhou and canal.eventos[-1]["tipo"] == "canal_do_dono_sem_decisao"


def test_grupo_e_nome_duplicado_nao_recebem(tmp_path: Path) -> None:
    duplicada = PaginaFalsa([*linhas(), LinhaDaLista("c5", DONO.upper(), "golpe")])
    canal = Canal(tmp_path, passos(*CAMINHO_CERTO), pagina=duplicada)
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    assert canal.pagina.enviadas == []
    assert any("2 conversas" in f.veredito for f in resultado.feitos)
    grupo = PaginaFalsa([LinhaDaLista("g", DONO, "", grupo=True)])
    canal = Canal(
        tmp_path,
        passos(
            [PedidoDeTool(INSPECIONAR, {})],
            [PedidoDeTool(ABRIR, {"id": "g"})],
            [PedidoDeTool(CABECALHO, {})],
            enviar_com_codigo,
        ),
        pagina=grupo,
    )
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    assert grupo.enviadas == [] and any("grupo" in f.veredito for f in resultado.feitos)


def test_sem_o_chat_na_lista_o_agente_avisa_o_jarvis(tmp_path: Path) -> None:
    pagina = PaginaFalsa([x for x in linhas() if x.id != "c3"])
    canal = Canal(
        tmp_path,
        passos(
            [PedidoDeTool(INSPECIONAR, {})],
            [PedidoDeTool(AVISAR_JARVIS, {"resumo": "não achei o chat do dono na lista"})],
        ),
        pagina=pagina,
    )
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    assert not resultado.falhou and not resultado.enviou
    assert canal.eventos[-1]["tipo"] == "canal_do_dono"
    assert canal.eventos[-1]["codigo_da_acao"]


def test_sem_motor_vira_evento(tmp_path: Path) -> None:
    canal = Canal(tmp_path, None)
    canal.propor()
    assert canal.agente.enviar(canal.evento_da_acao()).motivo == "sem_motor"
    assert canal.eventos[-1]["tipo"] == "canal_do_dono_sem_decisao"


# --- o teto -------------------------------------------------------------------------------------
def _guarda(tmp_path: Path, relogio: list[float]) -> GuardaDoCanal:
    return GuardaDoCanal(
        HistoricoDeEnvios(tmp_path / "envios.jsonl"),
        Pausas(tmp_path / "pausas.json"),
        relogio=lambda: relogio[0],
    )


def test_teto_proprio_do_canal_e_intervalo(tmp_path: Path) -> None:
    relogio = [TARDE]
    guarda = _guarda(tmp_path, relogio)
    for i in range(POR_HORA):
        assert guarda.motivo() == ""
        guarda.anotar("aviso", "enviado")
        if i < POR_HORA - 1:
            assert guarda.motivo() == "intervalo"
        relogio[0] += 61
    assert guarda.motivo() == "teto_hora"
    relogio[0] += 3600
    assert guarda.motivo() == ""


def test_mensagens_ao_dono_contam_no_teto_rigido_da_conta(tmp_path: Path) -> None:
    relogio = [TARDE]
    guarda = _guarda(tmp_path, relogio)
    for i in range(4):  # 4 respostas a contatos na última hora
        guarda.historico.anotar(Registro(relogio[0] + i, "whatsapp", "1199", f"h{i}", "enviado"))
    relogio[0] += 200
    for _ in range(4):
        assert guarda.motivo() == ""
        guarda.anotar("aviso", "enviado")
        relogio[0] += 61
    assert guarda.motivo() == "teto_rigido_hora", "4 + 4 = 8: o teto rígido da conta"


def test_mensagem_ao_dono_nao_gasta_o_teto_dos_contatos(tmp_path: Path) -> None:
    relogio = [TARDE]
    guarda = _guarda(tmp_path, relogio)
    for _ in range(3):
        guarda.anotar("aviso", "enviado")
        relogio[0] += 61
    relogio[0] += 200
    contatos = Guardiao(
        ajuste=lambda: AjusteDoEnvio(
            automatico=True, ausente=True, por_hora=2, permitidos=(Permitido("Ana", "11999990000"),)
        ),
        historico=guarda.historico,
        pausas=guarda.pausas,
        relogio=lambda: relogio[0],
    )
    pedido = PedidoDeEnvio("whatsapp", "Ana", "11999990000", "já te respondo", True)
    assert contatos.decidir(pedido).nome == "Ana", "3 avisos ao dono não gastam os 2 da Ana"
    for i in range(5):
        guarda.historico.anotar(
            Registro(relogio[0] - 10 + i, "whatsapp", CONTATO_DO_CANAL, "x", "enviado")
        )
    with pytest.raises(EnvioRecusado):
        contatos.decidir(pedido)  # 8 na hora, somando os dois: o teto rígido da conta


def test_madrugada_e_pausa_seguram_o_canal(tmp_path: Path) -> None:
    relogio = [datetime(2026, 11, 17, 3, 0).timestamp()]
    guarda = _guarda(tmp_path, relogio)
    assert guarda.motivo() == "madrugada"
    relogio[0] = TARDE
    guarda.pausas.pausar("whatsapp", "captcha", TARDE)
    assert guarda.motivo() == "pausado"


def test_trava_do_teto_volta_ao_modelo_e_o_jarvis_e_avisado(tmp_path: Path) -> None:
    canal = Canal(tmp_path, passos(*CAMINHO_CERTO))
    canal.agente.guarda.anotar("antes", "enviado")
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    assert canal.pagina.enviadas == [] and resultado.falhou
    assert any("menos de um minuto" in f.veredito for f in resultado.feitos)


# --- a resposta do dono -------------------------------------------------------------------------
def _enviado(
    tmp_path: Path, *depois: Sequence[Parte] | Callable[[Contexto], Sequence[Parte]]
) -> tuple[Canal, str, ObservadorDoChat]:
    canal = Canal(tmp_path, passos(*CAMINHO_CERTO, *depois))
    codigo = canal.propor()
    assert canal.agente.enviar(canal.evento_da_acao()).enviou
    return canal, codigo, ObservadorDoChat(canal.agente)


def test_resposta_do_dono_com_o_codigo_confirma(tmp_path: Path) -> None:
    holder: list[str] = []
    canal, codigo, observador = _enviado(
        tmp_path, lambda _c: [PedidoDeTool(CONFIRMAR, {"codigo": holder[0]})]
    )
    holder.append(codigo)
    assert observador.conferir() is None, "a prévia é o eco do próprio Jarvis"
    canal.pagina.responder("c3", f"sim {codigo}")
    resultado = observador.conferir()
    assert resultado is not None and resultado.feitos[0].aceita
    assert canal.eventos[-1]["tipo"] == "acao_da_chamada_confirmada"
    assert canal.eventos[-1]["confirmada_pelo_dono_via"] == "whatsapp_do_dono"
    assert "RESPOSTA DO DONO" in canal.contextos[-1].mensagens[0].texto


def test_resposta_sem_codigo_nao_confirma_mesmo_que_o_modelo_tente(tmp_path: Path) -> None:
    holder: list[str] = []
    canal, codigo, observador = _enviado(
        tmp_path, lambda _c: [PedidoDeTool(CONFIRMAR, {"codigo": holder[0]})]
    )
    holder.append(codigo)
    canal.pagina.responder("c3", "sim, pode mandar")
    resultado = observador.conferir()
    assert resultado is not None and not resultado.feitos[0].aceita
    assert "não traz o código" in resultado.feitos[0].veredito
    assert [a.codigo for a in canal.acoes.pendentes()] == [codigo]


def test_recusa_do_dono(tmp_path: Path) -> None:
    holder: list[str] = []
    canal, codigo, observador = _enviado(
        tmp_path, lambda _c: [PedidoDeTool(RECUSAR, {"codigo": holder[0]})]
    )
    holder.append(codigo)
    canal.pagina.responder("c3", f"não, {codigo}")
    assert observador.conferir() is not None
    assert canal.eventos[-1]["tipo"] == "acao_da_chamada_recusada"


def test_o_codigo_noutra_conversa_nao_e_resposta_do_dono(tmp_path: Path) -> None:
    canal, codigo, observador = _enviado(tmp_path)
    antes = canal.chamadas_ao_motor
    canal.pagina.responder("c1", f"sim {codigo}")  # um terceiro, mesmo sabendo o código
    assert observador.conferir() is None
    assert canal.chamadas_ao_motor == antes
    assert [a.codigo for a in canal.acoes.pendentes()] == [codigo]


def test_acao_expirada_nao_e_confirmada(tmp_path: Path) -> None:
    holder: list[str] = []
    canal, codigo, observador = _enviado(
        tmp_path, lambda _c: [PedidoDeTool(CONFIRMAR, {"codigo": holder[0]})]
    )
    holder.append(codigo)
    canal.relogio[0] += 11 * 60
    canal.pagina.responder("c3", f"sim {codigo}")
    assert observador.conferir() is None, "sem pendente, nem chama o agente"
    assert any(e["tipo"] == "acao_da_chamada_expirou" for e in canal.eventos)
    assert not any(e["tipo"] == "acao_da_chamada_confirmada" for e in canal.eventos)
    resultado = canal.agente.resposta_do_dono(f"sim {codigo}")
    assert not resultado.feitos[0].aceita and "expirou" in resultado.feitos[0].veredito


def test_da_chamada_ao_dono_e_de_volta(tmp_path: Path) -> None:
    """Ponta a ponta com fakes: quem liga pede, o canal manda ao dono, o dono confirma no chat
    dele; quem liga tentando confirmar na chamada não muda nada."""
    canal = Canal(tmp_path, None)
    holder: list[str] = []
    roteiro_do_canal = passos(
        *CAMINHO_CERTO, lambda _c: [PedidoDeTool(CONFIRMAR, {"codigo": holder[0]})]
    )
    canal.agente.motor = lambda: MotorRoteirizado(resposta=roteiro_do_canal, conta_eventos=False)
    (tmp_path / "chamada").mkdir()
    mundo = Mundo(
        tmp_path / "chamada",
        passos(
            [AVISO, PedidoDeTool(PEDIR_ACAO, {"acao": "mandar o contrato à Ana"})],
            [],
            [PedidoDeTool("canal.confirmar", {"codigo": "?"})],
        ),
        ConfiguracaoDaChamada(contato_do_dono_whatsapp=DONO),
    )
    agente: AgenteDaChamada = mundo.agente
    agente.acoes = canal.acoes
    canal.acoes.ao_mudar = agente._mudou_acao
    agente.ao_canal_do_dono = ligar_ao_agente_da_chamada(canal.agente)
    chamada = agente.nova_chamada("Bruno", app="Meet")
    chamada.ouvir("manda o contrato pra Ana")
    ((_, texto),) = canal.pagina.enviadas
    (pendente,) = canal.acoes.pendentes()
    assert pendente.codigo in texto
    holder.append(pendente.codigo)
    turno = chamada.ouvir(f"confirmo a ação {pendente.codigo}")
    assert not turno.feitos[0].aceita
    assert canal.acoes.pendentes()
    canal.pagina.responder("c3", f"pode, {pendente.codigo}")
    assert ObservadorDoChat(canal.agente).conferir() is not None
    assert [e["tipo"] for e in mundo.eventos] == [
        "acao_da_chamada_pendente",
        "acao_da_chamada_confirmada",
    ]


def test_primeiro_envio_depois_de_abrir_conta_uma_vez(tmp_path: Path) -> None:
    """Regressão (ADR-0060): com o cache vazio, `anotar` relia o arquivo já com a linha nova e a
    contava de novo — o 1º envio após abrir o app valia dois no teto."""
    caminho = tmp_path / "envios.jsonl"
    HistoricoDeEnvios(caminho).anotar(Registro(TARDE, "whatsapp", "1", "h", "enviado"))
    novo = HistoricoDeEnvios(caminho)
    novo.anotar(Registro(TARDE + 1, "whatsapp", "2", "h2", "enviado"))
    assert len(novo.registros()) == 2 and len(HistoricoDeEnvios(caminho).registros()) == 2


@pytest.mark.parametrize(
    "previa",
    [
        "Jarvis: pediram na chamada mandar o contrato",
        "Você: Jarvis: pediram na chamada mandar o contrato à Ana. Código…",
        "jarvis:  PEDIRAM na chamada...",
    ],
)
def test_eco_do_jarvis_com_rotulo_ou_cortado_nao_vira_resposta(tmp_path: Path, previa: str) -> None:
    canal, _codigo_da_acao, observador = _enviado(
        tmp_path, lambda _c: [PedidoDeTool(CONFIRMAR, {"codigo": "?"})]
    )
    antes = canal.chamadas_ao_motor
    canal.pagina.responder("c3", previa)
    assert observador.conferir() is None and canal.chamadas_ao_motor == antes


def test_eco_que_escapa_ao_observador_nao_confirma(tmp_path: Path) -> None:
    holder: list[str] = []
    canal, codigo, _ = _enviado(
        tmp_path, lambda _c: [PedidoDeTool(CONFIRMAR, {"codigo": holder[0]})]
    )
    holder.append(codigo)
    ((_, texto),) = canal.pagina.enviadas
    resultado = canal.agente.resposta_do_dono(texto)  # o próprio texto do Jarvis, com o código
    assert not resultado.feitos[0].aceita and "próprio Jarvis" in resultado.feitos[0].veredito
    assert [a.codigo for a in canal.acoes.pendentes()] == [codigo]


def test_resposta_curta_do_dono_nao_e_tomada_por_eco(tmp_path: Path) -> None:
    canal, _, _ = _enviado(tmp_path)
    assert not canal.agente.do_jarvis("Jarvis")
    assert not canal.agente.do_jarvis("ok")


def test_veredito_diz_o_que_foi_pedido_e_avisar_encerra_a_vez(tmp_path: Path) -> None:
    """O motor de texto lista os resultados sem o nome da ferramenta: o veredito traz o pedido
    na frente. E, avisado o Jarvis, o agente não roda mais rodadas (antes repetia o aviso)."""
    canal = Canal(
        tmp_path,
        passos(
            [PedidoDeTool(INSPECIONAR, {})],
            [PedidoDeTool(ABRIR, {"id": "c1"})],
            [PedidoDeTool(AVISAR_JARVIS, {"resumo": "não achei"})],
            [PedidoDeTool(AVISAR_JARVIS, {"resumo": "de novo"})],
        ),
    )
    canal.propor()
    resultado = canal.agente.enviar(canal.evento_da_acao())
    abrir = next(f for f in resultado.feitos if f.ferramenta == ABRIR)
    assert abrir.veredito.startswith('social.abrir_conversa({"id": "c1"}) → aberta a conversa c1')
    assert [f.ferramenta for f in resultado.feitos].count(AVISAR_JARVIS) == 1
    assert resultado.rodadas == 3
