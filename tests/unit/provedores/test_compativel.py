"""Os provedores de API (OpenAI, OpenRouter, Groq, compatíveis e a lista da Anthropic) contra um
servidor HTTP local, com `CI=1`: nada sai da máquina e nenhuma cota é gasta."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.imagem import Imagem
from jarvis.provedores.catalogo import Catalogo, Origem
from jarvis.provedores.compativel import FiltroDePensamento
from jarvis.provedores.interface import ListagemIndisponivel, ProvedorIndisponivel
from jarvis.provedores.nucleo import Provedores
from jarvis.provedores.registro import (
    CLAUDE_CLI,
    COMPATIVEL_LOCAL,
    COMPATIVEL_NUVEM,
    abrir,
    provedor_registrado,
)
from jarvis.s2.motor import Contexto, Mensagem, Modo, Raciocinio, Texto
from jarvis.voz.chaves import (
    VARIAVEL_ANTHROPIC,
    VARIAVEL_GROQ,
    VARIAVEL_OPENAI,
    VARIAVEL_OPENROUTER,
)
from jarvis.voz.interface import nunca_cancelado
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

SEGREDO = "sk-proj-chave_de_teste_que_nao_pode_vazar_0123456789"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02" + b"\x00" * 16


def ambiente(variavel: str) -> dict[str, str]:
    return {"CI": "1", variavel: SEGREDO}


def provedores(
    servico: ServicoFalso, ligados: tuple[str, ...], variavel: str, tmp: Path
) -> Provedores:
    """A fachada com a base de cada provedor apontada para o servidor falso."""
    bases = {i: servico.base + "/v1" for i in ligados}
    return Provedores(
        ligados=frozenset(ligados),
        ambiente=ambiente(variavel),
        pasta_de_trabalho=tmp,
        catalogo=Catalogo(tmp / "cache"),
        bases=bases,
    )


def sse(*eventos: object) -> bytes:
    return ("".join(f"data: {json.dumps(e)}\n\n" for e in eventos) + "data: [DONE]\n\n").encode()


def test_openai_lista_ids_sem_os_que_nao_conversam(tmp_path: Path) -> None:
    lista = {
        "data": [
            {"id": "gpt-6.1-terra", "object": "model", "owned_by": "openai"},
            {"id": "text-embedding-3-small"},
            {"id": "whisper-1"},
            {"id": "gpt-6-astra"},
        ]
    }
    with ServicoFalso(Roteiro(corpo=json.dumps(lista).encode())) as servico:
        conjunto = provedores(servico, ("conversa-openai",), VARIAVEL_OPENAI, tmp_path)
        listagem = conjunto.listar("conversa-openai")

    assert listagem.origem is Origem.PROVEDOR
    assert [m.id for m in listagem.modelos] == ["gpt-6-astra", "gpt-6.1-terra"]
    terra = listagem.modelo("gpt-6.1-terra")
    assert terra is not None
    assert terra.capacidades.visao is True  # do registro: a listagem da OpenAI não diz
    assert terra.capacidades.esforcos == ("none", "low", "medium", "high", "xhigh", "max")
    pedido = servico.pedidos[0]
    assert pedido.caminho == "/v1/models"
    assert pedido.autorizacao == f"Bearer {SEGREDO}"


def test_openrouter_lista_o_que_informa_e_pede_sem_coleta_de_dados(tmp_path: Path) -> None:
    lista = {
        "data": [
            {
                "id": "qualquer/visao-1",
                "name": "Visão 1",
                "context_length": 200000,
                "pricing": {"prompt": "0.0000015", "completion": "0.000006"},
                "architecture": {"input_modalities": ["text", "image"]},
                "top_provider": {"max_completion_tokens": 8192},
                "supported_parameters": ["tools", "reasoning", "max_tokens"],
            },
            {
                "id": "qualquer/texto-1",
                "architecture": {"input_modalities": ["text"]},
                "supported_parameters": ["max_tokens"],
            },
        ]
    }
    with ServicoFalso(Roteiro(corpo=json.dumps(lista).encode())) as servico:
        conjunto = provedores(servico, ("conversa-openrouter",), VARIAVEL_OPENROUTER, tmp_path)
        listagem = conjunto.listar("conversa-openrouter")
        visao = listagem.modelo("qualquer/visao-1")
        texto = listagem.modelo("qualquer/texto-1")
        assert visao is not None and texto is not None
        assert visao.capacidades.visao is True and visao.capacidades.ferramentas is True
        assert visao.capacidades.contexto == 200000 and visao.capacidades.saida_maxima == 8192
        assert visao.capacidades.preco_entrada == 1.5 and visao.capacidades.preco_saida == 6.0
        assert visao.capacidades.esforcos is not None and "high" in visao.capacidades.esforcos
        assert texto.capacidades.visao is False and texto.capacidades.esforcos == ()

        servico.roteiro = Roteiro(corpo=sse({"choices": [{"delta": {"content": "oi"}}]}))
        motor = conjunto.motor("conversa-openrouter", "qualquer/visao-1", "low")
        list(motor.gerar(contexto(), Modo.RAPIDO, nunca_cancelado))
    corpo = json.loads(servico.pedidos[-1].corpo)
    assert corpo["provider"] == {"data_collection": "deny"}
    assert corpo["reasoning"] == {"effort": "low"}
    assert servico.pedidos[0].caminho == "/v1/models?limit=1000"


def test_groq_pula_inativo_e_a_imagem_so_vai_a_quem_ve(tmp_path: Path) -> None:
    lista = {
        "data": [
            {"id": "qwen/qwen3.8-27b", "active": True, "context_window": 131072},
            {"id": "velho-1", "active": False},
            {"id": "openai/gpt-oss-20b", "active": True},
        ]
    }
    imagem = Imagem(id="tela:1", tipo="image/png", dados=PNG, largura=2, altura=2)
    com_imagem = Contexto(
        sistema="persona", mensagens=(Mensagem("dono", "o que tem na tela?"),), imagens=(imagem,)
    )
    with ServicoFalso(Roteiro(corpo=json.dumps(lista).encode())) as servico:
        conjunto = provedores(servico, ("conversa-groq",), VARIAVEL_GROQ, tmp_path)
        listagem = conjunto.listar("conversa-groq")
        assert [m.id for m in listagem.modelos] == ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]
        servico.roteiro = Roteiro(corpo=sse({"choices": [{"delta": {"content": "um botão"}}]}))
        ve = conjunto.motor("conversa-groq", "qwen/qwen3.8-27b")
        nao_ve = conjunto.motor("conversa-groq", "openai/gpt-oss-20b")
        assert getattr(ve, "aceita_imagem", False) is True
        assert getattr(nao_ve, "aceita_imagem", False) is False
        list(ve.gerar(com_imagem, Modo.RAPIDO, nunca_cancelado))
        list(nao_ve.gerar(com_imagem, Modo.RAPIDO, nunca_cancelado))
    com, sem = (json.loads(p.corpo) for p in servico.pedidos[1:])
    partes = com["messages"][1]["content"]
    assert partes[-1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert isinstance(sem["messages"][1]["content"], str)


def test_lista_da_anthropic_so_com_a_chave_e_diz_esforcos_e_visao(tmp_path: Path) -> None:
    lista = {
        "data": [
            {
                "id": "claude-sonnet-5-5",
                "display_name": "Claude Sonnet 5.5",
                "max_input_tokens": 1000000,
                "max_tokens": 64000,
                "capabilities": {
                    "image_input": {"supported": True},
                    "effort": {
                        "low": {"supported": True},
                        "high": {"supported": True},
                        "max": {"supported": False},
                    },
                },
            },
            {"id": "claude-antigo", "lifecycle": "retired"},
        ]
    }
    registro = provedor_registrado(CLAUDE_CLI)
    assert registro is not None
    sem_chave = abrir(CLAUDE_CLI, ambiente={"CI": "1"}, pasta_de_trabalho=tmp_path)
    with pytest.raises(ListagemIndisponivel, match=VARIAVEL_ANTHROPIC):
        sem_chave.listar()
    with ServicoFalso(Roteiro(corpo=json.dumps(lista).encode())) as servico:
        provedor = abrir(
            CLAUDE_CLI,
            ambiente=ambiente(VARIAVEL_ANTHROPIC),
            pasta_de_trabalho=tmp_path,
            extras={"base_da_api": servico.base + "/v1"},
        )
        modelos = provedor.listar()
    assert [m.id for m in modelos] == ["claude-sonnet-5-5"]
    assert modelos[0].capacidades.esforcos == ("low", "high")
    assert modelos[0].capacidades.visao is True and modelos[0].capacidades.contexto == 1000000


def test_compativel_local_so_aceita_base_desta_maquina(tmp_path: Path) -> None:
    with pytest.raises(ProvedorIndisponivel, match="desta máquina"):
        abrir(
            COMPATIVEL_LOCAL,
            ambiente={},
            pasta_de_trabalho=tmp_path,
            extras={"base": "http://192.168.0.10:11434/v1"},
        )
    with ServicoFalso(Roteiro(corpo=json.dumps({"data": [{"id": "qwen3:8b"}]}).encode())) as s:
        local = abrir(
            COMPATIVEL_LOCAL,
            ambiente={"CI": "1"},
            pasta_de_trabalho=tmp_path,
            extras={"base": s.base},
        )
        assert [m.id for m in local.listar()] == ["qwen3:8b"]
    assert not s.pedidos[0].tem_cabecalho("Authorization")  # local, sem chave


def test_compativel_de_nuvem_sem_base_e_sem_modelo_diz_o_que_falta(tmp_path: Path) -> None:
    provedor = abrir(COMPATIVEL_NUVEM, ambiente={}, pasta_de_trabalho=tmp_path)
    with pytest.raises(ProvedorIndisponivel, match="endereço"):
        provedor.motor("algum-modelo")
    with pytest.raises(ListagemIndisponivel, match="endereço"):
        provedor.listar()
    openrouter = abrir("conversa-openrouter", ambiente={}, pasta_de_trabalho=tmp_path)
    with pytest.raises(ProvedorIndisponivel, match="escolha um modelo"):
        openrouter.motor("")


@pytest.mark.parametrize(
    ("pedacos", "falado", "pensado"),
    [
        (["<think>vou ver</think>São dez."], "São dez.", "vou ver"),
        (["<th", "ink>a", "b</thi", "nk>ok"], "ok", "ab"),
        (["sem marca nenhuma"], "sem marca nenhuma", ""),
        (["a < b e c <thinker"], "a < b e c <thinker", ""),
    ],
)
def test_filtro_de_pensamento(pedacos: list[str], falado: str, pensado: str) -> None:
    filtro = FiltroDePensamento()
    deltas = [d for p in pedacos for d in filtro.alimentar(p)] + list(filtro.fechar())
    assert "".join(d.texto for d in deltas if isinstance(d, Texto)) == falado
    assert "".join(d.texto for d in deltas if isinstance(d, Raciocinio)) == pensado


def contexto() -> Contexto:
    return Contexto(sistema="persona", mensagens=(Mensagem("dono", "oi"),))
