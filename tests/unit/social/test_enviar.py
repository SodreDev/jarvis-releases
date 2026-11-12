"""O passo a passo do envio (ADR-0060, fatia D) contra uma ponte FALSA: nenhuma página, nenhum
navegador, nenhuma mensagem de verdade. Cada caso confere o que a ponte recebeu — e o que NÃO."""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.navegador.protocolo import validar_pedido
from jarvis.social.enviar import Enviador, EnvioCancelado
from jarvis.social.envio import (
    AjusteDoEnvio,
    EnvioRecusado,
    Guardiao,
    HistoricoDeEnvios,
    Pausas,
    PedidoDeEnvio,
    Permitido,
)

ANA = Permitido("Ana Souza", "+55 11 98888-7777")
MEIO_DIA = datetime(2026, 11, 12, 12, 0).timestamp()


class PonteDoEnvioFalsa:
    def __init__(self, cabecalhos: list[dict[str, Any]] | None = None) -> None:
        self.pedidos: list[tuple[str, dict[str, Any]]] = []
        self.cabecalhos = cabecalhos or [{"nome": "Ana Souza"}, {"nome": "Ana Souza"}]
        self.falhar_em = ""
        self.ambiguo = False

    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]:
        validar_pedido({"id": "e1", "method": metodo, "params": params})  # só pedido válido
        self.pedidos.append((metodo, params))
        if metodo == self.falhar_em:
            raise RuntimeError("a página não respondeu")
        if metodo == "social.cabecalho":
            return self.cabecalhos.pop(0) if self.cabecalhos else {"nome": ""}
        if metodo == "social.abrirConversa":
            return {"ambiguo": self.ambiguo}
        return {}

    def metodos(self) -> list[str]:
        return [m for m, _ in self.pedidos]


def _montar(
    tmp_path: Path, ponte: PonteDoEnvioFalsa, *, cancelado: Any = lambda: False
) -> tuple[Enviador, Guardiao, list[float]]:
    guardiao = Guardiao(
        ajuste=lambda: AjusteDoEnvio(automatico=True, ausente=True, permitidos=(ANA,)),
        historico=HistoricoDeEnvios(tmp_path / "envios.jsonl"),
        pausas=Pausas(tmp_path / "pausas.json"),
        relogio=lambda: MEIO_DIA,
    )
    dormido: list[float] = []
    enviador = Enviador(
        ponte,
        guardiao,
        familia=lambda: "chromium",
        aleatorio=random.Random(3),
        dormir=dormido.append,
        cancelado=cancelado,
    )
    return enviador, guardiao, dormido


def _pedido(texto: str = "Oi, Ana! Ele está fora e retorna à tarde.") -> PedidoDeEnvio:
    return PedidoDeEnvio("whatsapp", "Ana Souza", "11 98888-7777", texto, escreveu_primeiro=True)


def test_caminho_feliz_confere_antes_e_depois_e_solta_no_fim(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa()
    enviador, guardiao, dormido = _montar(tmp_path, ponte)
    assert enviador.enviar(_pedido()) == "enviado"
    metodos = ponte.metodos()
    assert metodos[0] == "social.abrirConversa" and metodos[1] == "social.cabecalho"
    assert metodos[-3:] == ["social.cabecalho", "social.enviar", "social.soltar"]
    digitados = "".join(p["texto"] for m, p in ponte.pedidos if m == "social.digitar")
    assert digitados == _pedido().texto, "tudo digitado, por pedaços, sem colar"
    assert all(
        len(p["atrasos"]) == len(p["texto"]) for m, p in ponte.pedidos if m == "social.digitar"
    )
    assert 20 <= sum(dormido) <= 90, "a reação antes de responder: dezenas de segundos"
    assert guardiao.historico.registros()[-1].resultado == "enviado"


def test_chat_de_outro_contato_nao_recebe_nada(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa([{"nome": "Ana Sousa"}])
    enviador, guardiao, _ = _montar(tmp_path, ponte)
    with pytest.raises(EnvioRecusado) as erro:
        enviador.enviar(_pedido())
    assert erro.value.codigo == "contato_divergente"
    assert "social.digitar" not in ponte.metodos() and "social.enviar" not in ponte.metodos()
    assert ponte.metodos()[-1] == "social.soltar", "solta o depurador mesmo recusando"
    assert guardiao.historico.registros()[-1].resultado == "recusado:contato_divergente"


def test_chat_que_muda_antes_do_enter_nao_envia(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa([{"nome": "Ana Souza"}, {"nome": "Bruno"}])
    enviador, _, _ = _montar(tmp_path, ponte)
    with pytest.raises(EnvioRecusado):
        enviador.enviar(_pedido())
    assert "social.digitar" in ponte.metodos() and "social.enviar" not in ponte.metodos()


@pytest.mark.parametrize(
    "cabecalho", [{"nome": "Ana Souza", "grupo": True}, {"nome": "Ana Souza", "ambiguo": True}]
)
def test_grupo_e_cabecalho_ambiguo_nao_enviam(tmp_path: Path, cabecalho: dict[str, Any]) -> None:
    ponte = PonteDoEnvioFalsa([cabecalho])
    enviador, _, _ = _montar(tmp_path, ponte)
    with pytest.raises(EnvioRecusado):
        enviador.enviar(_pedido())
    assert "social.enviar" not in ponte.metodos()


def test_homonimo_na_lista_de_conversas_nao_abre(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa()
    ponte.ambiguo = True
    enviador, _, _ = _montar(tmp_path, ponte)
    with pytest.raises(EnvioRecusado) as erro:
        enviador.enviar(_pedido())
    assert erro.value.codigo == "ambiguo"
    assert ponte.metodos() == ["social.abrirConversa", "social.soltar"]


def test_parar_durante_a_reacao_nao_toca_na_pagina(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa()
    vezes = iter([False, False, True])
    enviador, guardiao, _ = _montar(tmp_path, ponte, cancelado=lambda: next(vezes, True))
    with pytest.raises(EnvioCancelado):
        enviador.enviar(_pedido())
    assert ponte.pedidos == []
    assert guardiao.historico.registros()[-1].resultado == "recusado:cancelado"


def test_falha_da_pagina_nao_envia_e_solta(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa()
    ponte.falhar_em = "social.digitar"
    enviador, guardiao, _ = _montar(tmp_path, ponte)
    with pytest.raises(EnvioRecusado) as erro:
        enviador.enviar(_pedido())
    assert erro.value.codigo == "falha"
    assert ponte.metodos()[-1] == "social.soltar" and "social.enviar" not in ponte.metodos()
    assert guardiao.historico.registros()[-1].resultado == "recusado:falha"


def test_guardiao_que_recusa_nao_chama_a_extensao(tmp_path: Path) -> None:
    ponte = PonteDoEnvioFalsa()
    enviador, _, dormido = _montar(tmp_path, ponte)
    with pytest.raises(EnvioRecusado) as erro:
        enviador.enviar(_pedido("me passa o PIX"))
    assert erro.value.codigo == "dinheiro"
    assert ponte.pedidos == [] and dormido == []


@pytest.mark.parametrize(
    ("metodo", "params"),
    [
        ("social.digitar", {"rede": "instagram", "texto": "oi", "atrasos": [100, 100]}),
        ("social.digitar", {"rede": "whatsapp", "texto": "oi", "atrasos": [100]}),
        ("social.digitar", {"rede": "whatsapp", "texto": "o\n", "atrasos": [100, 100]}),
        ("social.digitar", {"rede": "whatsapp", "texto": "oi", "atrasos": [100, 5000]}),
        ("social.digitar", {"rede": "whatsapp", "texto": "x" * 81, "atrasos": [1] * 81}),
        ("social.digitar", {"rede": "whatsapp", "texto": "oi", "atrasos": [True, 1]}),
        ("social.enviar", {"rede": "discord"}),
        ("social.abrirConversa", {"rede": "whatsapp", "nome": "  "}),
        ("social.abrirConversa", {"rede": "whatsapp"}),
        ("social.enviar", {"rede": "whatsapp", "texto": "colado"}),
    ],
)
def test_pedidos_de_envio_fora_do_contrato_sao_recusados(
    metodo: str, params: dict[str, Any]
) -> None:
    from jarvis.navegador.protocolo import PedidoInvalido

    with pytest.raises(PedidoInvalido):
        validar_pedido({"id": "e1", "method": metodo, "params": params})
