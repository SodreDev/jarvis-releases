"""O roteador do cérebro (ADR-0056): segue o preset ativo, manda a imagem a quem vê e nunca troca
de provedor sozinho. Provedor de nuvem só contra servidor HTTP local, com `CI=1`."""

from __future__ import annotations

import json
from pathlib import Path

from jarvis.imagem import Imagem
from jarvis.provedores.catalogo import Catalogo
from jarvis.provedores.nucleo import Provedores
from jarvis.provedores.presets import FonteDePresets, Preset
from jarvis.provedores.roteador import MotorDosPresets
from jarvis.s2.motor import Contexto, Fim, Mensagem, Modo, MotivoDoFim, Texto
from jarvis.voz.chaves import VARIAVEL_GROQ
from jarvis.voz.config import Configuracao
from jarvis.voz.interface import Onde, nunca_cancelado
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

SEGREDO = "gsk_chave_de_teste_que_nao_pode_vazar_0123456789"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02" + b"\x00" * 16
GROQ_QUE_VE = Preset("visão groq", "visao", "conversa-groq", "qwen/qwen3.8-27b")
SSE = ('data: {"choices": [{"delta": {"content": "um botão azul"}}]}\n\ndata: [DONE]\n\n').encode()


def roteador(
    tmp_path: Path, *, ligados: frozenset[str] = frozenset(), base: str = ""
) -> MotorDosPresets:
    return MotorDosPresets(
        fonte=FonteDePresets(pasta=tmp_path / "config", configuracao=Configuracao(s2="eco")),
        provedores=Provedores(
            ligados=ligados,
            ambiente={"CI": "1", VARIAVEL_GROQ: SEGREDO},
            pasta_de_trabalho=tmp_path / "conversa",
            catalogo=Catalogo(tmp_path / "cache"),
            bases={"conversa-groq": base + "/v1"} if base else {},
        ),
    )


def texto(motor: MotorDosPresets, contexto: Contexto) -> tuple[str, Fim]:
    deltas = list(motor.gerar(contexto, Modo.RAPIDO, nunca_cancelado))
    fim = deltas[-1]
    assert isinstance(fim, Fim)
    return "".join(d.texto for d in deltas if isinstance(d, Texto)), fim


def pedido(com_imagem: bool = False) -> Contexto:
    imagens = (Imagem(id="tela:1", tipo="image/png", dados=PNG, largura=2, altura=2),)
    return Contexto(
        sistema="persona",
        mensagens=(Mensagem("dono", "o que tem na tela?"),),
        imagens=imagens if com_imagem else (),
    )


def test_sem_preset_do_dono_vale_o_da_configuracao(tmp_path: Path) -> None:
    motor = roteador(tmp_path)
    falado, fim = texto(motor, pedido())
    assert falado == "Você disse: o que tem na tela?"
    assert fim.motivo is MotivoDoFim.CONCLUIDO
    assert motor.nome == "eco (repete o que você disse)" and motor.onde is Onde.LOCAL
    assert motor.aceita_imagem is False


def test_a_troca_de_preset_vale_no_pedido_seguinte(tmp_path: Path) -> None:
    with ServicoFalso(Roteiro(corpo=SSE, tipo="text/event-stream")) as servico:
        motor = roteador(tmp_path, ligados=frozenset({"conversa-groq"}), base=servico.base)
        assert texto(motor, pedido())[0].startswith("Você disse")
        presets = motor.fonte.atuais().com_preset(
            Preset("rápido", "cerebro", "conversa-groq", "openai/gpt-oss-20b", "low")
        )
        motor.fonte.gravar(presets.com_ativo("cerebro", "rápido"))

        falado, _ = texto(motor, pedido())

    assert falado == "um botão azul"
    corpo = json.loads(servico.pedidos[0].corpo)
    assert corpo["model"] == "openai/gpt-oss-20b" and corpo["reasoning_effort"] == "low"
    assert motor.onde is Onde.NUVEM


def test_imagem_vai_ao_preset_de_visao_quando_o_cerebro_nao_ve(tmp_path: Path) -> None:
    rotas: list[str] = []
    with ServicoFalso(Roteiro(corpo=SSE, tipo="text/event-stream")) as servico:
        motor = roteador(tmp_path, ligados=frozenset({"conversa-groq"}), base=servico.base)
        motor.ao_rotear = rotas.append
        motor.fonte.gravar(
            motor.fonte.atuais().com_preset(GROQ_QUE_VE).com_ativo("visao", "visão groq")
        )
        assert motor.aceita_imagem is True

        sem_imagem, _ = texto(motor, pedido())
        com_imagem, _ = texto(motor, pedido(com_imagem=True))

    assert sem_imagem.startswith("Você disse")  # o cérebro (eco) continua o do texto
    assert com_imagem == "um botão azul"
    (enviado,) = servico.pedidos
    partes = json.loads(enviado.corpo)["messages"][1]["content"]
    assert partes[-1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert rotas == ["Groq · qwen/qwen3.8-27b"]


def test_sem_rota_que_ve_a_imagem_fica_de_fora(tmp_path: Path) -> None:
    with ServicoFalso(Roteiro(corpo=SSE, tipo="text/event-stream")) as servico:
        motor = roteador(tmp_path, base=servico.base)  # a Groq não foi ligada pelo dono
        motor.fonte.gravar(
            motor.fonte.atuais().com_preset(GROQ_QUE_VE).com_ativo("visao", "visão groq")
        )
        assert motor.aceita_imagem is False
        falado, fim = texto(motor, pedido(com_imagem=True))
    assert falado.startswith("Você disse") and fim.motivo is MotivoDoFim.CONCLUIDO
    assert servico.pedidos == []  # nada saiu para um provedor que o dono não ligou


def test_preset_que_nao_pode_rodar_diz_por_que_e_nao_troca_de_provedor(tmp_path: Path) -> None:
    motor = roteador(tmp_path)
    presets = motor.fonte.atuais().com_preset(Preset("rápido", "cerebro", "conversa-groq", "x-1"))
    motor.fonte.gravar(presets.com_ativo("cerebro", "rápido"))

    falado, fim = texto(motor, pedido())

    assert falado == ""
    assert fim.motivo is MotivoDoFim.ERRO
    assert "rápido" in fim.detalhe and "desligado" in fim.detalhe
