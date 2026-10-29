"""Os dois motores de conversa que já existiam, atrás da interface de provedor (ADR-0056).

- **eco** (local): repete o que o dono disse, sem rede e sem conta — o padrão (ADR-0025, D18);
- **CLI do Claude** (nuvem): o `claude -p` em stream (ADR-0018, ADR-0025), agora com o esforço do
  preset (`--effort`). A CLI não tem comando oficial de listar modelos: com `ANTHROPIC_API_KEY` a
  lista vem da API (`GET /v1/models`); sem ela, é a do registro (apelidos e ids atuais).

Nenhum dos dois mudou de comportamento: o motor é o mesmo objeto de antes, só que montado aqui.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.provedores.catalogo import modelos_da_resposta
from jarvis.provedores.interface import ESFORCOS, Capacidades, ListagemIndisponivel, Modelo
from jarvis.rede import ErroDeRede
from jarvis.s2.motor import MotorDeConversa
from jarvis.s2.motor_claude_cli import COMANDO_PADRAO, MotorClaudeCli
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.chaves import VARIAVEL_ANTHROPIC, Chave, SegredoAusente
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.nuvem import ClienteHttp, ErroDoServico, ServicoRecusou
from jarvis.voz.registro import Motor
from jarvis.voz.s2_provisorio import RespostaDeEco

NOME_DO_ECO = "eco (repete o que você disse)"
BASE_DA_ANTHROPIC = "https://api.anthropic.com/v1"


def converter_anthropic(item: object) -> dict[str, Any]:
    """Um modelo de `GET /v1/models` (platform.claude.com/docs/en/api/models/list): `id`,
    `display_name`, `max_input_tokens`, `max_tokens` e `capabilities` (`image_input`, `effort`)."""
    if not isinstance(item, Mapping) or item.get("lifecycle") == "retired":
        return {}
    capacidades = item.get("capabilities")
    capacidades = capacidades if isinstance(capacidades, Mapping) else {}
    imagem = capacidades.get("image_input")
    esforco = capacidades.get("effort")
    esforcos = (
        [
            nome
            for nome in ESFORCOS
            if isinstance(esforco.get(nome), Mapping) and esforco[nome].get("supported") is True
        ]
        if isinstance(esforco, Mapping)
        else None
    )
    return {
        "id": item.get("id"),
        "nome": item.get("display_name", ""),
        "capacidades": {
            "visao": imagem.get("supported") if isinstance(imagem, Mapping) else None,
            "esforcos": esforcos,
            "contexto": item.get("max_input_tokens"),
            "saida_maxima": item.get("max_tokens"),
        },
    }


@dataclass(slots=True)
class ProvedorEco:
    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)

    @property
    def id(self) -> str:
        return self.registro.id

    @property
    def onde(self) -> Onde:
        return Onde.LOCAL

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        return (
            Modelo(
                "eco",
                "repete o que você disse",
                Capacidades(visao=False, ferramentas=False, esforcos=()),
            ),
        )

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        eco = RespostaDeEco()
        return MotorRoteirizado(
            resposta=lambda contexto: eco.responder(contexto.turno), nome=NOME_DO_ECO
        )


@dataclass(slots=True)
class ProvedorClaudeCli:
    registro: Motor
    ambiente: Mapping[str, str] | None = None
    pasta_de_trabalho: Path = field(default_factory=Path)
    comando: Sequence[str] = COMANDO_PADRAO
    base_da_api: str = BASE_DA_ANTHROPIC

    @property
    def id(self) -> str:
        return self.registro.id

    @property
    def onde(self) -> Onde:
        return Onde.NUVEM

    def listar(self, *, cancelado: Cancelado = nunca_cancelado) -> tuple[Modelo, ...]:
        """A CLI não tem comando de listar; com `ANTHROPIC_API_KEY`, a lista vem da API da
        Anthropic (`GET /v1/models`), que diz quem vê imagem e que esforços cada modelo aceita."""
        try:
            chave = Chave.do_ambiente(VARIAVEL_ANTHROPIC, ambiente=self.ambiente)
        except SegredoAusente:
            raise ListagemIndisponivel(
                "a CLI do Claude não tem comando de listar modelos, e não há "
                f"{VARIAVEL_ANTHROPIC} para pedir a lista à API"
            ) from None
        try:
            cliente = ClienteHttp(base=self.base_da_api, prazo_s=10.0, ambiente=self.ambiente)
            dados = cliente.obter("/models?limit=1000", chave=chave).json()
        except (ServicoRecusou, ErroDoServico, ErroDeRede, OSError, ValueError) as erro:
            raise ListagemIndisponivel(str(erro)) from None
        itens = dados.get("data")
        modelos = modelos_da_resposta(
            [converter_anthropic(i) for i in itens] if isinstance(itens, list) else []
        )
        if not modelos:
            raise ListagemIndisponivel("a API da Anthropic devolveu a lista vazia")
        return modelos

    def motor(
        self, modelo: str = "", esforco: str = "", capacidades: Capacidades | None = None
    ) -> MotorDeConversa:
        self.pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
        return MotorClaudeCli(
            pasta_de_trabalho=self.pasta_de_trabalho,
            comando=self.comando,
            modelo=modelo,
            esforco=esforco,
            ambiente=self.ambiente,
        )


__all__ = ["NOME_DO_ECO", "ProvedorClaudeCli", "ProvedorEco"]
