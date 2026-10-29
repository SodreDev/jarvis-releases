"""Provedores com a API de Chat Completions da OpenAI: OpenAI, OpenRouter, Groq e compatíveis.

Um desenho só, porque o formato é um só: `GET {base}/models` lista, `POST {base}/chat/completions`
com `stream: true` responde em SSE (`choices[0].delta.content`, `data: [DONE]` no fim). O que muda
de um para outro é pouco e fica em cada classe:

- **o que a listagem informa**: a OpenAI só dá o id; a Groq dá a janela de contexto; o OpenRouter
  dá contexto, preço, modalidades de entrada (visão) e os parâmetros aceitos (`tools`,
  `reasoning`). O que faltar o registro completa (`[[capacidade]]`), e o resto fica "não
  informado";
- **o nome do esforço**: `reasoning_effort` (OpenAI, Groq) ou `reasoning: {effort}` (OpenRouter);
- **o raciocínio que volta**: `delta.reasoning` (OpenRouter, Groq) ou `delta.reasoning_content`
  — vira `Raciocinio`, **nunca** `Texto` (ADR-0031): não vai à voz nem à tela.

A conversa vai como o cérebro a monta para todo motor (`Contexto.como_texto`, o prompt de sistema
com o catálogo de ferramentas pelo protocolo de texto da ADR-0038): o modelo propõe, o PDP decide,
igual para qualquer provedor. A imagem da tela (ADR-0032) só vai a modelo que vê.
"""

from __future__ import annotations

import contextlib
import json
import re
import urllib.request
from collections.abc import Generator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Final
from urllib.parse import urlparse

from jarvis.provedores.catalogo import modelos_da_resposta
from jarvis.provedores.interface import (
    ESFORCOS,
    Capacidades,
    ListagemIndisponivel,
    Modelo,
    ProvedorIndisponivel,
    esforco_do_modo,
    limpar_texto,
)
from jarvis.provedores.stream import StreamCancelado, StreamSemPrazo, eventos_sse, linhas
from jarvis.rede import ErroDeRede
from jarvis.s2.motor import (
    Contexto,
    Delta,
    Fim,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    Raciocinio,
    Texto,
)
from jarvis.s2.motor_claude_cli import sistema_com_ferramentas
from jarvis.voz.chaves import Chave, SegredoAusente
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.nuvem import (
    AGENTE_DO_USUARIO,
    ClienteHttp,
    ErroDoServico,
    ServicoRecusou,
    proibir_nuvem_real_em_ci,
)
from jarvis.voz.registro import Motor

PRAZO_DA_LISTAGEM_S: Final = 10.0
LIMITE_DA_LISTAGEM: Final = 16 * 1024 * 1024
PRAZO_POR_MODO_S: Final[Mapping[Modo, float]] = {Modo.RAPIDO: 60.0, Modo.PENSAR: 180.0}
"""Teto de um pedido. No `pensar`, um modelo de raciocínio pode passar um minuto antes do
primeiro token visível; o laço do turno tem o teto dele (ADR-0028)."""
MAQUINAS_LOCAIS: Final = frozenset({"localhost", "127.0.0.1", "::1"})


def _mapa(valor: object) -> dict[str, Any]:
    return dict(valor) if isinstance(valor, Mapping) else {}


def _por_milhao(valor: object) -> float | None:
    """`"0.0000015"` (US$ por token, como o OpenRouter publica) → `1.5` (por milhão)."""
    try:
        numero = float(str(valor))
    except ValueError:
        return None
    return round(numero * 1_000_000, 6) if 0 <= numero < 1 else None


@dataclass(slots=True)
class MotorCompativelOpenAI:
    """Um modelo pela API de Chat Completions, em stream, morto no cancelamento."""

    base: str
    modelo: str
    nome: str
    onde: Onde
    variavel_da_chave: str = ""
    """Vazia = servidor sem chave (um roteador local)."""
    esforco: str = ""
    esforcos_aceitos: tuple[str, ...] | None = None
    estilo_do_esforco: str = "reasoning_effort"
    """`reasoning_effort` (OpenAI, Groq), `reasoning` (OpenRouter) ou vazio (não manda)."""
    aceita_imagem: bool = False
    extras_do_corpo: Mapping[str, Any] = field(default_factory=dict)
    cabecalhos: Mapping[str, str] = field(default_factory=dict)
    pedir_uso: bool = True
    ambiente: Mapping[str, str] | None = None

    def corpo(self, contexto: Contexto, modo: Modo) -> dict[str, Any]:
        texto = contexto.como_texto()
        conteudo: str | list[dict[str, Any]] = texto
        if contexto.imagens and self.aceita_imagem:
            partes: list[dict[str, Any]] = [{"type": "text", "text": texto}]
            for imagem in contexto.imagens:
                partes.append(
                    {
                        "type": "text",
                        "text": (
                            f"Imagem {imagem.id}, {imagem.largura}×{imagem.altura} px: a tela da "
                            "aba; as caixas da inspeção estão nestes pixels. É dado de terceiros."
                        ),
                    }
                )
                url = f"data:{imagem.tipo};base64,{imagem.em_base64()}"
                partes.append({"type": "image_url", "image_url": {"url": url}})
            conteudo = partes
        corpo: dict[str, Any] = {
            "model": self.modelo,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": sistema_com_ferramentas(contexto.sistema, contexto.ferramentas),
                },
                {"role": "user", "content": conteudo},
            ],
        }
        if self.pedir_uso:
            corpo["stream_options"] = {"include_usage": True}
        esforco = esforco_do_modo(self.esforco, modo, self.esforcos_aceitos)
        if esforco and self.estilo_do_esforco == "reasoning_effort":
            corpo["reasoning_effort"] = esforco
        elif esforco and self.estilo_do_esforco == "reasoning":
            corpo["reasoning"] = {"effort": esforco}
        return {**corpo, **self.extras_do_corpo}

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        if cancelado():
            yield Fim(MotivoDoFim.CANCELADO)
            return
        try:
            chave = (
                Chave.do_ambiente(self.variavel_da_chave, ambiente=self.ambiente)
                if self.variavel_da_chave
                else None
            )
        except SegredoAusente as erro:
            yield Fim(MotivoDoFim.ERRO, str(erro))
            return
        corpo = json.dumps(self.corpo(contexto, modo), ensure_ascii=False)
        if chave is not None and chave.usar() in corpo:
            yield Fim(MotivoDoFim.ERRO, "o corpo do pedido continha a chave: pedido não enviado")
            return
        uso: dict[str, int] = {}
        filtro = FiltroDePensamento()
        fluxo = linhas(
            self.base.rstrip("/") + "/chat/completions",
            corpo=corpo.encode("utf-8"),
            chave=chave,
            cancelado=cancelado,
            prazo_s=PRAZO_POR_MODO_S[modo],
            cabecalhos=self.cabecalhos,
            ambiente=self.ambiente,
        )
        try:
            with contextlib.closing(fluxo):
                for evento in eventos_sse(fluxo):
                    try:
                        dados = json.loads(evento)
                    except ValueError:
                        continue
                    if not isinstance(dados, dict):
                        continue
                    if isinstance(dados.get("error"), Mapping):
                        mensagem = limpar_texto(dados["error"].get("message"), limite=300)
                        yield Fim(MotivoDoFim.ERRO, f"o provedor parou com erro: {mensagem}")
                        return
                    uso.update(_uso(dados.get("usage")))
                    for delta in _deltas(dados):
                        if isinstance(delta, Texto):
                            yield from filtro.alimentar(delta.texto)
                        else:
                            yield delta
            yield from filtro.fechar()
        except StreamCancelado:
            yield Fim(MotivoDoFim.CANCELADO)
            return
        except StreamSemPrazo:
            yield Fim(MotivoDoFim.PRAZO, f"{self.nome} passou de {PRAZO_POR_MODO_S[modo]:.0f} s")
            return
        except ServicoRecusou as erro:
            yield Fim(MotivoDoFim.ERRO, f"o provedor recusou: {erro}")
            return
        except (ErroDoServico, ErroDeRede) as erro:
            yield Fim(MotivoDoFim.ERRO, str(erro))
            return
        yield Fim(MotivoDoFim.CONCLUIDO, uso=uso)


def _deltas(dados: Mapping[str, Any]) -> Generator[Delta, None, None]:
    escolhas = dados.get("choices")
    if not isinstance(escolhas, list) or not escolhas or not isinstance(escolhas[0], Mapping):
        return
    delta = escolhas[0].get("delta")
    if not isinstance(delta, Mapping):
        return
    for campo in ("reasoning", "reasoning_content"):
        pensado = delta.get(campo)
        if isinstance(pensado, str) and pensado:
            yield Raciocinio(pensado)
    detalhes = delta.get("reasoning_details")
    if isinstance(detalhes, list) and not delta.get("reasoning"):
        for detalhe in detalhes:
            if isinstance(detalhe, Mapping):
                pensado = detalhe.get("text") or detalhe.get("summary")
                if isinstance(pensado, str) and pensado:
                    yield Raciocinio(pensado)
    texto = delta.get("content")
    if isinstance(texto, str) and texto:
        yield Texto(texto)


@dataclass(slots=True)
class FiltroDePensamento:
    """Tira do texto o bloco `<think>…</think>` que alguns modelos abertos escrevem no meio da
    resposta (Qwen, DeepSeek, pelos roteadores e pelo Ollama): ele vira `Raciocinio`, nunca fala.
    A marca pode chegar partida entre deltas, então o fim do pedaço que pode ser começo de marca
    espera o próximo."""

    dentro: bool = False
    pendente: str = ""

    def alimentar(self, texto: str) -> Generator[Delta, None, None]:
        resto = self.pendente + texto
        self.pendente = ""
        while resto:
            marca = FIM_DO_PENSAMENTO if self.dentro else INICIO_DO_PENSAMENTO
            achado = resto.find(marca)
            if achado < 0:
                guardar = _sufixo_de_marca(resto, marca)
                pronto = resto[: len(resto) - guardar] if guardar else resto
                self.pendente = resto[len(pronto) :]
                if pronto:
                    yield Raciocinio(pronto) if self.dentro else Texto(pronto)
                return
            if achado:
                antes = resto[:achado]
                yield Raciocinio(antes) if self.dentro else Texto(antes)
            resto = resto[achado + len(marca) :]
            self.dentro = not self.dentro

    def fechar(self) -> Generator[Delta, None, None]:
        if self.pendente:
            yield Raciocinio(self.pendente) if self.dentro else Texto(self.pendente)
        self.pendente = ""


INICIO_DO_PENSAMENTO: Final = "<think>"
FIM_DO_PENSAMENTO: Final = "</think>"


def _sufixo_de_marca(texto: str, marca: str) -> int:
    """Quantos caracteres do fim de `texto` podem ser o começo de `marca`."""
    for tamanho in range(min(len(marca) - 1, len(texto)), 0, -1):
        if marca.startswith(texto[-tamanho:]):
            return tamanho
    return 0


def _uso(bruto: object) -> dict[str, int]:
    if not isinstance(bruto, Mapping):
        return {}
    saida: dict[str, int] = {}
    for nosso, deles in (("entrada", "prompt_tokens"), ("saida", "completion_tokens")):
        valor = bruto.get(deles)
        if isinstance(valor, int) and not isinstance(valor, bool):
            saida[nosso] = valor
    return saida


NAO_CONVERSA: Final[re.Pattern[str]] = re.compile(
    r"embedding|whisper|tts|transcribe|moderation|dall-e|gpt-image|sora|davinci|babbage|playai"
)
"""Famílias que a listagem traz e que não conversam (embedding, voz, imagem, moderação): ficam
fora da escolha do cérebro. Só o nome diz isso, porque a OpenAI e a Groq não dizem mais nada."""


@dataclass(slots=True)
class ProvedorCompativel:
    """A base: lista `GET {base}/models` e chama `POST {base}/chat/completions`."""

    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)
    base: str = ""
    """Vazia = o `endereco` do registro."""

    ESTILO_DO_ESFORCO: ClassVar[str] = "reasoning_effort"
    SERVICO_LOCAL: ClassVar[bool] = False
    CAMINHO_DA_LISTA: ClassVar[str] = "/models"
    FILTRAR_NAO_CONVERSA: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not self.base:
            self.base = self.registro.endereco
        if self.SERVICO_LOCAL and (urlparse(self.base).hostname or "") not in MAQUINAS_LOCAIS:
            raise ProvedorIndisponivel(
                f"{self.registro.id} é local: a base {self.base!r} tem de ser desta máquina "
                "(localhost, 127.0.0.1)"
            )

    @property
    def id(self) -> str:
        return self.registro.id

    @property
    def onde(self) -> Onde:
        return self.registro.onde

    @property
    def nome_do_servico(self) -> str:
        return self.registro.servico.split(" (")[0].strip() or self.registro.id

    def _chave(self) -> Chave | None:
        if not self.registro.variavel_da_chave:
            return None
        return Chave.do_ambiente(self.registro.variavel_da_chave, ambiente=self.ambiente)

    def _base_valida(self) -> None:
        if not self.base:
            raise ProvedorIndisponivel(
                f"{self.registro.id} não tem endereço: escreva a base na configuração"
            )

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        try:
            self._base_valida()
            proibir_nuvem_real_em_ci(self.base, self.ambiente)
            chave = self._chave()
            if chave is None:
                dados = _obter_sem_chave(self.base.rstrip("/") + self.CAMINHO_DA_LISTA)
            else:
                cliente = ClienteHttp(
                    base=self.base, prazo_s=PRAZO_DA_LISTAGEM_S, ambiente=self.ambiente
                )
                dados = cliente.obter(self.CAMINHO_DA_LISTA, chave=chave).json()
        except (SegredoAusente, ProvedorIndisponivel) as erro:
            raise ListagemIndisponivel(str(erro)) from None
        except (ServicoRecusou, ErroDoServico, ErroDeRede, OSError, ValueError) as erro:
            raise ListagemIndisponivel(str(erro)) from None
        itens = dados.get("data")
        if not isinstance(itens, list):
            raise ListagemIndisponivel("resposta fora do formato: sem `data`")
        convertidos = [self.converter(item) for item in itens]
        if self.FILTRAR_NAO_CONVERSA:
            convertidos = [
                c for c in convertidos if not NAO_CONVERSA.search(str(c.get("id", "")).lower())
            ]
        modelos = modelos_da_resposta(convertidos)
        if not modelos:
            raise ListagemIndisponivel("o provedor devolveu a lista vazia")
        return tuple(sorted(modelos, key=lambda m: m.id))

    def converter(self, item: object) -> dict[str, Any]:
        """Um item da listagem no formato do catálogo (`id`, `nome`, `capacidades`)."""
        if not isinstance(item, Mapping):
            return {}
        return {"id": item.get("id"), "nome": item.get("name", "")}

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        self._base_valida()
        escolhido = modelo or self.registro.modelo
        if not escolhido:
            raise ProvedorIndisponivel(
                f"{self.nome_do_servico} não tem modelo padrão: escolha um modelo no preset"
            )
        conhecidas = capacidades or Capacidades()
        return MotorCompativelOpenAI(
            base=self.base,
            modelo=escolhido,
            nome=f"{self.nome_do_servico} · {escolhido}",
            onde=self.registro.onde,
            variavel_da_chave=self.registro.variavel_da_chave,
            esforco=esforco,
            esforcos_aceitos=conhecidas.esforcos,
            estilo_do_esforco=self.ESTILO_DO_ESFORCO,
            aceita_imagem=conhecidas.visao is True,
            extras_do_corpo=self.extras_do_corpo(),
            pedir_uso=self.PEDIR_USO,
            ambiente=self.ambiente,
        )

    PEDIR_USO: ClassVar[bool] = True

    def extras_do_corpo(self) -> dict[str, Any]:
        return {}


@dataclass(slots=True)
class ProvedorOpenAI(ProvedorCompativel):
    """A API da OpenAI. A listagem só dá o id: o resto vem do registro."""

    FILTRAR_NAO_CONVERSA: ClassVar[bool] = True


@dataclass(slots=True)
class ProvedorGroq(ProvedorCompativel):
    """A Groq (`/openai/v1`): a listagem dá a janela de contexto e se o modelo está ativo."""

    FILTRAR_NAO_CONVERSA: ClassVar[bool] = True

    def converter(self, item: object) -> dict[str, Any]:
        if not isinstance(item, Mapping) or item.get("active") is False:
            return {}
        return {
            "id": item.get("id"),
            "nome": item.get("id", ""),
            "capacidades": {
                "contexto": item.get("context_window"),
                "saida_maxima": item.get("max_completion_tokens"),
            },
        }


@dataclass(slots=True)
class ProvedorOpenRouter(ProvedorCompativel):
    """O OpenRouter: a listagem mais rica (contexto, preço, entrada de imagem, parâmetros
    aceitos), o esforço em `reasoning.effort`, e todo pedido com `data_collection: deny` — só vai
    a provedor que não guarda o que recebe (openrouter.ai/docs/guides/routing/provider-selection).
    """

    ESTILO_DO_ESFORCO: ClassVar[str] = "reasoning"
    CAMINHO_DA_LISTA: ClassVar[str] = "/models?limit=1000"
    PEDIR_USO: ClassVar[bool] = False
    """O OpenRouter manda o uso no fim de todo stream, sem pedir."""

    def converter(self, item: object) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            return {}
        arquitetura = item.get("architecture")
        entrada = arquitetura.get("input_modalities") if isinstance(arquitetura, Mapping) else None
        parametros = item.get("supported_parameters")
        preco = _mapa(item.get("pricing"))
        topo = _mapa(item.get("top_provider"))
        return {
            "id": item.get("id"),
            "nome": item.get("name", ""),
            "capacidades": {
                "visao": "image" in entrada if isinstance(entrada, list) else None,
                "ferramentas": "tools" in parametros if isinstance(parametros, list) else None,
                "esforcos": (list(ESFORCOS) if "reasoning" in parametros else [])
                if isinstance(parametros, list)
                else None,
                "contexto": item.get("context_length"),
                "saida_maxima": topo.get("max_completion_tokens"),
                "preco_entrada": _por_milhao(preco.get("prompt")),
                "preco_saida": _por_milhao(preco.get("completion")),
            },
        }

    def extras_do_corpo(self) -> dict[str, Any]:
        return {"provider": {"data_collection": "deny"}}


@dataclass(slots=True)
class ProvedorCompativelLocal(ProvedorCompativel):
    """Um servidor desta máquina com a API da OpenAI (Ollama, LM Studio): nada sai daqui."""

    SERVICO_LOCAL: ClassVar[bool] = True
    PEDIR_USO: ClassVar[bool] = False


@dataclass(slots=True)
class ProvedorCompativelNuvem(ProvedorCompativel):
    """Um roteador de nuvem compatível (Together, DeepInfra…), com a base que o dono escreveu.
    Os termos dele não foram lidos: só chama com o dono aceitando em `nuvem_sem_termos`."""

    PEDIR_USO: ClassVar[bool] = False


def _obter_sem_chave(url: str) -> dict[str, Any]:
    """`GET` de catálogo num servidor **local** sem autenticação (Ollama, LM Studio)."""
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE_DO_USUARIO})  # noqa: S310
    if pedido.type not in {"http", "https"}:
        raise ErroDoServico(f"esquema {pedido.type!r} não é http(s)")
    with urllib.request.urlopen(pedido, timeout=PRAZO_DA_LISTAGEM_S) as resposta:  # noqa: S310
        dados = json.loads(resposta.read(LIMITE_DA_LISTAGEM).decode("utf-8", "replace"))
    return dados if isinstance(dados, dict) else {}
