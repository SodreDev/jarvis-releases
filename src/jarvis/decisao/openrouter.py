"""O Jev pelo OpenRouter (`POST /api/alpha/decisions`) atrás da interface de decisão (ADR-0029).

Mesmas regras dos motores de nuvem de voz (ADR-0017): o registro manda (`decisao-jev-openrouter`),
nuvem desligada até o **dono** ligar, chave só do ambiente/chaveiro e **no cabeçalho** — nunca no
corpo, na URL ou em log —, base não local proibida sob `CI=1`, e prazo nosso. O que muda: aqui
quem sai da máquina é o **texto** da fala que o microfone transcreveu, e a falha nunca pode virar
uma ação — qualquer problema vira `DecisaoIndisponivel`, e quem pergunta decide não agir.

A rota é **alfa** (`/api/alpha`): o caminho pode mudar; o modelo vai fixado
(`typesafe/jev-1.13`) porque os limiares são calibrados nele e o alias `jev-latest` se move.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.decisao.interface import (
    DecisaoIndisponivel,
    DecisaoRecusada,
    Pergunta,
    PerguntaEscolha,
    PerguntaNoul,
    Resposta,
    RespostaEscolha,
    RespostaNota,
    RespostaNoul,
)
from jarvis.rede import ErroDeRede
from jarvis.voz.chaves import Chave
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado
from jarvis.voz.nuvem import ClienteHttp, ServicoRecusou, proibir_nuvem_real_em_ci
from jarvis.voz.registro import Motor, exigir_motor

BASE_PADRAO: Final = "https://openrouter.ai/api/alpha"
CAMINHO: Final = "/decisions"
MODELO_PADRAO: Final = "typesafe/jev-1.13"
REGISTRADO: Final = "decisao-jev-openrouter"
PRAZO_PADRAO_S: Final = 1.5
"""Teto de uma consulta. Medida de terceiros: ~350–530 ms de ponta a ponta (dryhurst.io,
2026-09-23); p95 0,63–0,69 s em outro teste (OpenRouter, 2026-09-19). O dobro disso é o limite
de quem espera para decidir se responde."""
SERVICO: Final = "OpenRouter/Jev"


def corpo_da_pergunta(pergunta: Pergunta) -> dict[str, Any]:
    if isinstance(pergunta, PerguntaNoul):
        return {
            "type": "noul",
            "instructions": pergunta.instrucoes,
            "criteria": {"true": pergunta.sim, "false": pergunta.nao},
        }
    if isinstance(pergunta, PerguntaEscolha):
        return {
            "type": "choice",
            "instructions": pergunta.instrucoes,
            "criteria": dict(pergunta.opcoes),
        }
    return {
        "type": "score",
        "instructions": pergunta.instrucoes,
        "criteria": list(pergunta.niveis),
    }


def _probabilidade(valor: object, onde: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not 0.0 <= valor <= 1.0:
        raise DecisaoIndisponivel(f"resposta fora do formato: {onde} não é probabilidade de 0 a 1")
    return float(valor)


def _ler_resposta(nome: str, pergunta: Pergunta, bruta: object) -> Resposta:
    if not isinstance(bruta, dict):
        raise DecisaoIndisponivel(f"resposta fora do formato: sem resposta para {nome!r}")
    if isinstance(pergunta, PerguntaNoul):
        return RespostaNoul(_probabilidade(bruta.get("noul"), f"{nome}.noul"))
    probabilidades = bruta.get("probabilidades", bruta.get("probabilities", {}))
    if not isinstance(probabilidades, dict):
        raise DecisaoIndisponivel(f"resposta fora do formato: {nome}.probabilities")
    confianca = _probabilidade(bruta.get("confidence", 0.0), f"{nome}.confidence")
    if isinstance(pergunta, PerguntaEscolha):
        escolha = bruta.get("choice")
        if escolha not in pergunta.opcoes:
            raise DecisaoIndisponivel(
                f"resposta fora do formato: {nome}.choice {escolha!r} não é uma opção"
            )
        return RespostaEscolha(
            escolha=str(escolha),
            confianca=confianca,
            probabilidades={
                str(k): _probabilidade(v, f"{nome}.probabilities")
                for k, v in probabilidades.items()
            },
        )
    nota = bruta.get("score")
    if isinstance(nota, bool) or not isinstance(nota, (int, float)):
        raise DecisaoIndisponivel(f"resposta fora do formato: {nome}.score")
    return RespostaNota(
        nota=float(nota),
        confianca=confianca,
        probabilidades={
            int(k): _probabilidade(v, f"{nome}.probabilities") for k, v in probabilidades.items()
        },
    )


@dataclass(slots=True)
class ClassificadorOpenRouter:
    modelo: str = MODELO_PADRAO
    registrado: str = REGISTRADO
    base: str = BASE_PADRAO
    nuvem_ligada: Collection[str] = ()
    """Os motores de nuvem que **o dono** ligou na configuração dele. Vazio = nada liga."""
    prazo_s: float = PRAZO_PADRAO_S
    ambiente: Mapping[str, str] | None = None
    nome: str = ""
    onde: Onde = Onde.NUVEM
    consultas: int = 0
    _motor: Motor | None = field(default=None, repr=False)
    _chave: Chave | None = field(default=None, repr=False)
    _cliente: ClienteHttp | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.nome:
            self.nome = f"openrouter@{self.modelo}"

    def abrir(self) -> Motor:
        """Portão → chave → cliente. Nenhum socket é aberto aqui (mesma ordem da ADR-0017)."""
        motor = exigir_motor(self.registrado, nuvem_ligada=self.nuvem_ligada)
        self._motor = motor
        proibir_nuvem_real_em_ci(self.base, self.ambiente)
        self._chave = Chave.do_ambiente(motor.variavel_da_chave, ambiente=self.ambiente)
        self._cliente = ClienteHttp(base=self.base, prazo_s=self.prazo_s, ambiente=self.ambiente)
        return motor

    @property
    def aviso(self) -> str:
        motor = self._motor or exigir_motor(self.registrado, nuvem_ligada=[self.registrado])
        return motor.frase_de_aviso

    def decidir(
        self,
        estado: str | Mapping[str, Any] | Sequence[Any],
        perguntas: Mapping[str, Pergunta],
        *,
        cancelado: Cancelado = nunca_cancelado,
    ) -> dict[str, Resposta]:
        if self._cliente is None or self._chave is None:
            self.abrir()
        cliente, chave = self._cliente, self._chave
        assert cliente is not None and chave is not None
        corpo = json.dumps(
            {
                "model": self.modelo,
                "state": estado,
                "questions": {nome: corpo_da_pergunta(p) for nome, p in perguntas.items()},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.consultas += 1
        try:
            resposta = cliente.postar(
                CAMINHO,
                corpo=corpo,
                tipo_do_corpo="application/json",
                chave=chave,
                cancelado=cancelado,
                prazo_s=self.prazo_s,
            )
        except ServicoRecusou as erro:
            raise DecisaoRecusada(str(erro)) from None
        except (ErroDeRede, OSError, TimeoutError) as erro:
            raise DecisaoIndisponivel(f"{type(erro).__name__}: {erro}") from None
        if resposta.cancelada:
            raise DecisaoIndisponivel("consulta cancelada antes de terminar")
        try:
            respostas = resposta.json().get("answers")
        except ValueError:
            raise DecisaoIndisponivel("resposta fora do formato: não é JSON") from None
        if not isinstance(respostas, dict):
            raise DecisaoIndisponivel("resposta fora do formato: sem `answers`")
        return {nome: _ler_resposta(nome, p, respostas.get(nome)) for nome, p in perguntas.items()}
