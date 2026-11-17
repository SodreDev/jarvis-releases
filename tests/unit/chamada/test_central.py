"""A central da chamada (ADR-0074, fatia A): a chave mestra desligada por padrão, os eventos ao
Jarvis, o tique do observador e a confirmação por clique no PC. Fakes e relógio falso."""

from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from typing import Any

from jarvis.chamada.acoes import Origem
from jarvis.chamada.agente import FALAR, PEDIR_ACAO, SaidaEmLista
from jarvis.chamada.canal_do_dono import (
    ABRIR,
    CABECALHO,
    CONFIRMAR,
    INSPECIONAR,
    GuardaDoCanal,
    LinhaDaLista,
    PaginaFalsa,
)
from jarvis.chamada.central import CentralDaChamada
from jarvis.chamada.config import ConfiguracaoDaChamada
from jarvis.chamada.memoria import MemoriaDosInterlocutores, Recados
from jarvis.chamada.totp import EstadoDoTotp, GuardaEmMemoria, Verificador
from jarvis.s2.motor import PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.social.envio import HistoricoDeEnvios, Pausas
from tests.unit.chamada.test_agente import AVISO
from tests.unit.chamada.test_canal_do_dono import TARDE, enviar_com_codigo

SEGREDO = base64.b32encode(b"segredo-de-teste-160b").decode().rstrip("=")


class Mundo:
    def __init__(self, tmp_path: Path, *, ativa: bool = True, contato: str = "Você") -> None:
        self.relogio = [TARDE]
        self.config = ConfiguracaoDaChamada(chamadas_ativas=ativa, contato_do_dono_whatsapp=contato)
        self.eventos: list[dict[str, Any]] = []
        self.mudou = 0
        self.pagina = PaginaFalsa(
            [LinhaDaLista("c1", "Carlos", "oi"), LinhaDaLista("c2", "Você", "nota")]
        )
        self.saida = SaidaEmLista()
        self.roteiro_canal: list[Any] = []
        self.roteiro_chamada: list[Any] = []
        motor_canal = MotorRoteirizado(
            resposta=lambda c: self._proximo(self.roteiro_canal, c), conta_eventos=False
        )
        motor_chamada = MotorRoteirizado(
            resposta=lambda c: self._proximo(self.roteiro_chamada, c), conta_eventos=False
        )

        def motor() -> Any:
            # O mesmo motor nos dois papéis, como no app: distingue pelas ferramentas.
            return _PorPapel(motor_canal, motor_chamada)

        self.central = CentralDaChamada(
            configuracao=lambda: self.config,
            motor=motor,
            ao_evento=self.eventos.append,
            guarda=GuardaDoCanal(
                HistoricoDeEnvios(tmp_path / "envios.jsonl"),
                Pausas(tmp_path / "pausas.json"),
                relogio=lambda: self.relogio[0],
            ),
            verificador=Verificador(
                guarda=GuardaEmMemoria(SEGREDO),
                estado=EstadoDoTotp.ler(tmp_path / "totp.json"),
                relogio=lambda: self.relogio[0],
            ),
            memoria=MemoriaDosInterlocutores(),
            recados=Recados(),
            pagina=self.pagina,
            saida=self.saida,
            relogio=lambda: self.relogio[0],
            ao_mudar=self._contar,
        )

    def _contar(self) -> None:
        self.mudou += 1

    @staticmethod
    def _proximo(fila: list[Any], contexto: Any) -> Any:
        if not fila:
            return []
        item = fila.pop(0)
        return item(contexto) if callable(item) else item

    def tipos(self) -> list[str]:
        return [str(e["tipo"]) for e in self.eventos]


class _PorPapel:
    def __init__(self, canal: MotorRoteirizado, chamada: MotorRoteirizado) -> None:
        self._canal, self._chamada = canal, chamada

    def gerar(self, contexto: Any, modo: Any, cancelado: Any) -> Any:
        ids = {str(f["id"]) for f in contexto.ferramentas}
        alvo = self._chamada if FALAR in ids else self._canal
        return alvo.gerar(contexto, modo, cancelado)


def test_desligada_por_padrao_nada_roda(tmp_path: Path) -> None:
    assert ConfiguracaoDaChamada().chamadas_ativas is False
    mundo = Mundo(tmp_path, ativa=False)
    assert mundo.central.nova_chamada("Bruno") is None
    mundo.central.tique()
    assert mundo.eventos == [] and mundo.pagina.enviadas == []


def test_da_chamada_ao_chat_do_dono_e_o_jarvis_recebe_cada_evento(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path)
    mundo.roteiro_chamada = [[AVISO, PedidoDeTool(PEDIR_ACAO, {"acao": "mandar a planilha"})]]
    mundo.roteiro_canal = [
        [PedidoDeTool(INSPECIONAR, {})],
        [PedidoDeTool(ABRIR, {"id": "c2"})],
        [PedidoDeTool(CABECALHO, {})],
        enviar_com_codigo,
    ]
    chamada = mundo.central.nova_chamada("Bruno", app="WhatsApp Web")
    assert chamada is not None
    chamada.ouvir("manda a planilha pra Lúcia")
    ((conversa, texto),) = mundo.pagina.enviadas
    (pendente,) = mundo.central.pendentes()
    assert conversa == "c2" and pendente["codigo"] in texto
    assert mundo.tipos() == ["acao_da_chamada_pendente"]
    assert all(e["origem"] == "chamada" and e["de_terceiros"] for e in mundo.eventos)
    assert mundo.mudou == 1
    # O dono responde no chat dele; o tique lê a prévia e o agente confirma.
    mundo.roteiro_canal = [[PedidoDeTool(CONFIRMAR, {"codigo": pendente["codigo"]})]]
    mundo.pagina.responder("c2", f"sim {pendente['codigo']}")
    mundo.central.tique()
    assert mundo.tipos()[-1] == "acao_da_chamada_confirmada"
    assert mundo.eventos[-1]["confirmada_pelo_dono_via"] == "whatsapp_do_dono"


def test_confirmacao_por_clique_no_pc_e_expiracao_pelo_tique(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path, contato="")  # sem o chat: só o PC
    acoes = mundo.central.acoes
    um = acoes.propor("a", "", interlocutor="x", app="", dono_reconhecido=False)
    dois = acoes.propor("b", "", interlocutor="x", app="", dono_reconhecido=False)
    assert um is not None and dois is not None and mundo.pagina.enviadas == []
    assert mundo.central.confirmar_no_pc(um.codigo).aceita
    assert mundo.eventos[-1]["confirmada_pelo_dono_via"] == Origem.SESSAO_DO_PC.value
    mundo.relogio[0] += 11 * 60
    mundo.central.tique()
    assert mundo.tipos()[-1] == "acao_da_chamada_expirou"
    assert mundo.central.recusar_no_pc(dois.codigo).motivo == "expirada"


def test_canal_ligado_sem_pagina_vira_evento_e_nao_envia(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path)
    mundo.central.pagina = None
    mundo.central.acoes.propor("a", "", interlocutor="x", app="", dono_reconhecido=False)
    assert mundo.tipos() == ["acao_da_chamada_pendente", "canal_do_dono_sem_decisao"]
    assert mundo.eventos[-1]["motivo"] == "sem_pagina"


def test_desligar_a_chave_para_o_canal_mas_o_pc_ainda_confirma(tmp_path: Path) -> None:
    mundo = Mundo(tmp_path)
    mundo.config = replace(mundo.config, chamadas_ativas=False)
    pendente = mundo.central.acoes.propor("a", "", interlocutor="x", app="", dono_reconhecido=False)
    assert pendente is not None and mundo.pagina.enviadas == []
    assert mundo.central.confirmar_no_pc(pendente.codigo).aceita
