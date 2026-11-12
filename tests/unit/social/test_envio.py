"""O guardião do envio (ADR-0060, fatia D; docs/redes-sociais-riscos.md §4–§6).

Cada guardrail tem um caso que tenta furá-lo. Nada aqui fala com navegador: é só a decisão."""

from __future__ import annotations

import json
import os
import random
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from jarvis.social.envio import (
    PAUSA_DE_ALERTA_S,
    TETO_RIGIDO_POR_DIA,
    TETO_RIGIDO_POR_HORA,
    AjusteDoEnvio,
    Cabecalho,
    EnvioRecusado,
    Guardiao,
    HistoricoDeEnvios,
    Pausas,
    PedidoDeEnvio,
    Permitido,
    conferir_contato,
    conteudo_barrado,
    em_pedacos,
    mesmo_telefone,
    na_madrugada,
    reacao,
    ritmo,
)

ANA = Permitido("Ana Souza", "+55 11 98888-7777")
BIA = Permitido("Bia Lima", "+55 21 97777-1111")
MEIO_DIA = datetime(2026, 11, 12, 12, 0).timestamp()


Montar = Callable[..., Guardiao]


class Relogio:
    def __init__(self, agora: float = MEIO_DIA) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora


def ligado(**campos: object) -> AjusteDoEnvio:
    base = {"automatico": True, "ausente": True, "permitidos": (ANA, BIA)}
    base.update(campos)
    return AjusteDoEnvio(**base)  # type: ignore[arg-type]


def pedido(**campos: object) -> PedidoDeEnvio:
    base: dict[str, object] = {
        "rede": "whatsapp",
        "nome": "Ana Souza",
        "telefone": "11 98888-7777",
        "texto": "Oi, Ana! Ele está fora agora e retorna à tarde.",
        "escreveu_primeiro": True,
    }
    base.update(campos)
    return PedidoDeEnvio(**base)  # type: ignore[arg-type]


@pytest.fixture
def montar(tmp_path: Path) -> Montar:
    def fazer(ajuste: AjusteDoEnvio, relogio: Relogio | None = None) -> Guardiao:
        return Guardiao(
            ajuste=lambda: ajuste,
            historico=HistoricoDeEnvios(tmp_path / "envios.jsonl"),
            pausas=Pausas(tmp_path / "redes-pausas.json"),
            relogio=relogio or Relogio(),
        )

    return fazer


def recusa(guardiao: Guardiao, envio: PedidoDeEnvio) -> str:
    with pytest.raises(EnvioRecusado) as erro:
        guardiao.decidir(envio)
    return erro.value.codigo


def test_tudo_desligado_por_padrao(montar: Montar) -> None:
    assert recusa(montar(AjusteDoEnvio()), pedido()) == "desligado"
    assert recusa(montar(ligado(ausente=False)), pedido()) == "presente"


def test_o_caminho_feliz_devolve_o_contato_da_lista(montar: Montar) -> None:
    assert montar(ligado()).decidir(pedido()) == ANA


@pytest.mark.parametrize(
    ("campos", "codigo"),
    [
        ({"rede": "instagram"}, "rede_sem_envio"),
        ({"grupo": True}, "grupo"),
        ({"nome": "Carlos"}, "fora_da_lista"),
        ({"telefone": "11 90000-0000"}, "fora_da_lista"),
        ({"nome": "Ana", "telefone": "11 98888-7777"}, "fora_da_lista"),
        ({"escreveu_primeiro": False}, "nao_escreveu"),
        ({"texto": "me manda o PIX que eu pago"}, "dinheiro"),
        ({"texto": "fica R$ 50"}, "dinheiro"),
        ({"texto": "o CPF dele é esse"}, "dado_sensivel"),
        ({"texto": "o código é 123 456 789"}, "dado_sensivel"),
        ({"texto": "olha www.exemplo.com"}, "link"),
        ({"texto": "x" * 301}, "longo"),
        ({"texto": "   "}, "vazio"),
    ],
)
def test_cada_guardrail_recusa(montar: Montar, campos: dict[str, object], codigo: str) -> None:
    assert recusa(montar(ligado()), pedido(**campos)) == codigo


def test_homonimo_na_lista_e_ambiguo(montar: Montar) -> None:
    dupla = ligado(permitidos=(ANA, Permitido("ana souza", "+55 11 98888-7777")))
    assert recusa(montar(dupla), pedido()) == "ambiguo"


def test_madrugada(montar: Montar) -> None:
    tres_da_manha = Relogio(datetime(2026, 11, 12, 3, 0).timestamp())
    assert recusa(montar(ligado(), tres_da_manha), pedido()) == "madrugada"
    assert na_madrugada(0, (0, 6)) and na_madrugada(5, (0, 6)) and not na_madrugada(6, (0, 6))
    assert na_madrugada(23, (22, 6)) and na_madrugada(2, (22, 6)) and not na_madrugada(12, (22, 6))


def test_intervalo_teto_e_texto_repetido(montar: Montar) -> None:
    relogio = Relogio()
    guardiao = montar(ligado(), relogio)
    guardiao.decidir(pedido())
    guardiao.anotar(pedido(), "enviado")
    relogio.agora += 60
    assert recusa(guardiao, pedido(nome="Bia Lima", telefone="21 97777-1111")) == "intervalo"
    relogio.agora += 200
    mesmo_texto_outra_pessoa = pedido(nome="Bia Lima", telefone="21 97777-1111")
    assert recusa(guardiao, mesmo_texto_outra_pessoa) == "repetido"
    variado = pedido(nome="Bia Lima", telefone="21 97777-1111", texto="Oi, Bia, ele volta já.")
    assert guardiao.decidir(variado) == BIA
    for _ in range(3):
        guardiao.anotar(variado, "enviado")
    relogio.agora += 200
    assert recusa(guardiao, pedido(texto="outro texto")) == "teto_hora"


def test_teto_do_dia_e_teto_rigido(montar: Montar, tmp_path: Path) -> None:
    relogio = Relogio()
    guardiao = montar(ligado(por_hora=100, por_dia=100, intervalo_s=0), relogio)
    apertado = ligado(por_hora=100, por_dia=100, intervalo_s=0).apertado()
    assert (apertado.por_hora, apertado.por_dia) == (TETO_RIGIDO_POR_HORA, TETO_RIGIDO_POR_DIA)
    assert apertado.intervalo_s >= 60, "o arquivo não zera o intervalo"
    for i in range(TETO_RIGIDO_POR_DIA):
        relogio.agora += 3600 / TETO_RIGIDO_POR_HORA + 1
        guardiao.anotar(pedido(texto=f"t{i}"), "enviado")
    relogio.agora += 3600
    if datetime.fromtimestamp(relogio.agora).hour < 6:
        pytest.skip("o relógio do teste caiu na madrugada")
    assert recusa(guardiao, pedido(texto="mais um")) == "teto_dia"


def test_log_tem_hash_e_nao_tem_o_texto(montar: Montar, tmp_path: Path) -> None:
    guardiao = montar(ligado())
    guardiao.anotar(pedido(texto="segredo bobo"), "enviado")
    log = tmp_path / "envios.jsonl"
    linha = json.loads(log.read_text("utf-8"))
    assert set(linha) == {"momento", "hora", "rede", "contato", "hash", "resultado"}
    assert "segredo" not in log.read_text("utf-8") and len(linha["hash"]) == 64
    if os.name != "nt":
        assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_alerta_pausa_24h_e_so_o_dono_tira(montar: Montar, tmp_path: Path) -> None:
    relogio = Relogio()
    guardiao = montar(ligado(), relogio)
    guardiao.pausas.pausar("whatsapp", "captcha", relogio.agora)
    assert recusa(guardiao, pedido()) == "pausado"
    relogio.agora += PAUSA_DE_ALERTA_S - 1
    assert recusa(guardiao, pedido()) == "pausado"
    relogio.agora += 2
    assert guardiao.decidir(pedido()) == ANA
    guardiao.pausas.pausar("whatsapp", "logout", relogio.agora)
    guardiao.pausas.tirar("whatsapp")
    assert guardiao.decidir(pedido()) == ANA
    with pytest.raises(ValueError):
        guardiao.pausas.pausar("whatsapp", "qualquer", relogio.agora)
    (tmp_path / "redes-pausas.json").write_text('{"whatsapp": {"ate": "x"}}', "utf-8")
    assert recusa(guardiao, pedido()) == "pausado", "pausa ilegível conta como pausada"


def test_conferir_o_cabecalho_do_chat() -> None:
    conferir_contato(ANA, Cabecalho("Ana Souza"))
    conferir_contato(ANA, Cabecalho("ana  souza", "+55 (11) 98888-7777"))
    for cabecalho, codigo in (
        (Cabecalho("Ana Souza", grupo=True), "grupo"),
        (Cabecalho("Ana Souza", ambiguo=True), "ambiguo"),
        (Cabecalho("Ana Sousa"), "contato_divergente"),
        (Cabecalho("Ana Souza", "11 90000-0000"), "telefone_divergente"),
    ):
        with pytest.raises(EnvioRecusado) as erro:
            conferir_contato(ANA, cabecalho)
        assert erro.value.codigo == codigo


def test_telefone_casa_pelos_ultimos_digitos() -> None:
    assert mesmo_telefone("+55 11 98888-7777", "11988887777")
    assert not mesmo_telefone("+55 11 98888-7777", "11988887770")
    assert not mesmo_telefone("123", "123")


def test_ritmo_e_reacao_sao_humanos_e_variam() -> None:
    aleatorio = random.Random(7)
    assert all(20 <= reacao(aleatorio) <= 90 for _ in range(50))
    teclas = ritmo("Oi, tudo bem? Ele volta já.", aleatorio)
    assert "".join(t.texto for t in teclas) == "Oi, tudo bem? Ele volta já."
    atrasos = [t.atraso_ms for t in teclas]
    assert all(40 <= a <= 1_500 for a in atrasos) and len(set(atrasos)) > len(atrasos) // 2
    depois_da_virgula = atrasos[3]  # o espaço depois de «Oi,»
    assert depois_da_virgula > sorted(atrasos)[len(atrasos) // 2]
    pedacos = em_pedacos(teclas, teto_ms=1_000)
    assert sum(len(p) for p in pedacos) == len(teclas)
    assert all(sum(t.atraso_ms for t in p) <= 1_000 or len(p) == 1 for p in pedacos)


def test_conteudo_curto_e_limpo_passa() -> None:
    assert conteudo_barrado("Oi! Ele está numa reunião e responde mais tarde.") == ""
